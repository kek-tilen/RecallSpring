"""Export: one learner's own material, notes and answers as plain files (BYOS step 1, decided 2026-11-27).

The worker builds a ZIP under ``storage_dir/exports/<user id>/<export id>.zip`` (no model calls):

    RecallSpring export <date>/
      README.txt
      <course>/material/<the learner's folders>/<file as uploaded>
      <course>/notes/<date> <title>.md        (the note's text exactly as saved)
      <course>/answers.csv                    (one row per answer, grade in force)
      answers.json                            (every answer with its question, sources and all assessments)

Only the learner's own, not deleted records; never another learner's, the audit log, tokens or settings. The ZIP is
not encrypted (it is the learner's copy) and is deleted 24 hours after it is ready. One export at a time per learner.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import new_session
from ..errors import ApiError
from ..ingest.storage import blob_path
from ..learning.grading import GRADE_NAMES
from ..models import (
    Assessment,
    Attempt,
    Concept,
    Course,
    Export,
    Note,
    Question,
    QuestionConcept,
    Source,
    SourceFolder,
    User,
)
from . import assistants
from .events import audit
from .reviews import effective_assessment

log = logging.getLogger("recallspring.export")

MAKE_EXPORT = "make_export"
KEEP_FOR = timedelta(hours=24)
ACTIVE = ("queued", "running")
BLOOM = {1: "Remember", 2: "Understand", 3: "Apply", 4: "Analyze", 5: "Evaluate", 6: "Create"}
STORED_KINDS = {"pdf", "image", "docx", "pptx", "xlsx", "odt", "odp", "ods"}  # already compressed
CSV_COLUMNS = [
    "answered_at",
    "course",
    "concept",
    "question",
    "bloom_level",
    "answer_kind",
    "your_answer",
    "grade",
    "grade_label",
    "provisional",
    "graded_by",
    "explanation",
    "overridden",
]
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


# ---------------------------------------------------------------- names


def safe_name(name: str | None, fallback: str = "untitled", limit: int = 120) -> str:
    """A file or folder name that works on Windows, macOS and Linux; the learner's words otherwise kept."""
    text = unicodedata.normalize("NFC", name or "")
    text = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in text)
    text = re.sub(r'[<>:"/\\|?*]', "-", text)
    text = re.sub(r"\s+", " ", text).strip().strip(". ")
    if not text:
        text = fallback
    if text.split(".")[0].upper() in _RESERVED:
        text = f"_{text}"
    if len(text) > limit:
        stem, dot, ext = text.rpartition(".")
        text = f"{stem[: limit - len(ext) - 1]}.{ext}" if dot and 0 < len(ext) <= 10 else text[:limit]
    return text


class Names:
    """Unique paths inside the ZIP (case-insensitive, as on Windows); a repeat becomes "name (2).ext"."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def take(self, folder: str, name: str) -> str:
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem:
            stem, ext = name, ""
        candidate, n = name, 1
        while f"{folder}/{candidate}".casefold() in self.used:
            n += 1
            candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
        path = f"{folder}/{candidate}"
        self.used.add(path.casefold())
        return path


# ---------------------------------------------------------------- what can be exported


def _courses(db: Session, user: User, course_ids: list[uuid.UUID] | None = None) -> list[Course]:
    query = select(Course).where(Course.user_id == user.id, Course.deleted_at.is_(None))
    if course_ids is not None:
        query = query.where(Course.id.in_(course_ids))
    return list(db.scalars(query.order_by(Course.title)))


def _sources(db: Session, user: User, course_ids: list[uuid.UUID]) -> list[Source]:
    return list(
        db.scalars(
            select(Source)
            .where(Source.user_id == user.id, Source.course_id.in_(course_ids), Source.deleted_at.is_(None))
            .order_by(Source.uploaded_at)
        )
    )


def _notes(db: Session, user: User, course_ids: list[uuid.UUID]) -> list[Note]:
    return list(
        db.scalars(
            select(Note)
            .where(Note.user_id == user.id, Note.course_id.in_(course_ids), Note.deleted_at.is_(None))
            .order_by(Note.saved_at)
        )
    )


def estimate(db: Session, user: User) -> list[dict[str, Any]]:
    """Per course: how many files and bytes of material, notes and answers an export would hold."""
    courses = _courses(db, user)
    ids = [c.id for c in courses]
    if not ids:
        return []
    files = dict(
        (cid, (n, b))
        for cid, n, b in db.execute(
            select(Source.course_id, func.count(), func.coalesce(func.sum(Source.byte_size), 0))
            .where(Source.user_id == user.id, Source.course_id.in_(ids), Source.deleted_at.is_(None))
            .group_by(Source.course_id)
        )
    )
    notes = dict(
        db.execute(
            select(Note.course_id, func.count())
            .where(Note.user_id == user.id, Note.course_id.in_(ids), Note.deleted_at.is_(None))
            .group_by(Note.course_id)
        ).all()
    )
    answers = dict(
        db.execute(
            select(Question.course_id, func.count())
            .join(Attempt, Attempt.question_id == Question.id)
            .where(Attempt.user_id == user.id, Question.course_id.in_(ids))
            .group_by(Question.course_id)
        ).all()
    )
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "files": int(files.get(c.id, (0, 0))[0]),
            "bytes": int(files.get(c.id, (0, 0))[1]),
            "notes": int(notes.get(c.id, 0)),
            "answers": int(answers.get(c.id, 0)),
        }
        for c in courses
    ]


# ---------------------------------------------------------------- rows and views


def folder(user_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / "exports" / str(user_id)


def zip_path(row: Export) -> Path:
    return folder(row.user_id) / f"{row.id}.zip"


def file_name(row: Export) -> str:
    return f"RecallSpring export {row.created_at:%Y-%m-%d}.zip"


def item(row: Export) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "state": row.state,
        "destination": row.destination,
        "options": row.options,
        "progress": row.progress or None,
        "counts": row.counts or None,
        "byte_size": row.byte_size,
        "file_name": file_name(row) if row.created_at else None,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "downloaded_at": row.downloaded_at.isoformat() if row.downloaded_at else None,
    }


def _latest(db: Session, user: User) -> Export | None:
    return db.scalar(select(Export).where(Export.user_id == user.id).order_by(Export.created_at.desc()).limit(1))


def view(db: Session, user: User) -> dict[str, Any]:
    latest = _latest(db, user)
    last_ready = db.scalar(
        select(func.max(Export.finished_at)).where(Export.user_id == user.id, Export.state.in_(("ready", "expired")))
    )
    return {
        "courses": estimate(db, user),
        "current": item(latest) if latest else None,
        "last_export_at": last_ready.isoformat() if last_ready else None,
        "keep_hours": int(KEEP_FOR.total_seconds() // 3600),
    }


def owned(db: Session, user: User, export_id: uuid.UUID) -> Export:
    row = db.get(Export, export_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "That export is not there any more.")
    return row


# ---------------------------------------------------------------- asking for one


def create(
    db: Session,
    user: User,
    *,
    course_ids: list[uuid.UUID] | None,
    material: bool,
    notes: bool,
    answers: bool,
    destination: str,
    request_id: str | None,
) -> Export:
    from ..ingest.jobs import enqueue

    if not (material or notes or answers):
        raise ApiError(422, "nothing_to_export", "Choose at least one of material, notes or answers.")
    busy = db.scalar(select(Export.id).where(Export.user_id == user.id, Export.state.in_(ACTIVE)))
    if busy:
        raise ApiError(409, "export_running", "An export is already being made. Wait for it or stop it.")
    courses = _courses(db, user, course_ids)
    if course_ids is not None and len(courses) != len(set(course_ids)):
        raise ApiError(404, "not_found", "One of those courses is not there any more.")
    if not courses:
        raise ApiError(422, "nothing_to_export", "There are no courses to export yet.")
    chosen = {str(c.id) for c in courses}
    need = sum(c["bytes"] for c in estimate(db, user) if c["id"] in chosen) if material else 0
    target = folder(user.id)
    target.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target).free < need + get_settings().min_free_disk_bytes:
        raise ApiError(507, "not_enough_space", "Not enough free disk space on the server for this export.")
    row = Export(
        user_id=user.id,
        state="queued",
        options={
            "course_ids": [str(c.id) for c in courses] if course_ids is not None else None,
            "material": material,
            "notes": notes,
            "answers": answers,
        },
        destination=destination,
    )
    db.add(row)
    db.flush()
    enqueue(db, user_id=user.id, type=MAKE_EXPORT, payload={"export_id": str(row.id)})
    audit(
        db,
        actor_id=user.id,
        action="export.created",
        target_type="export",
        target_id=row.id,
        details={
            "courses": len(courses),
            "material": material,
            "notes": notes,
            "answers": answers,
            "destination": destination,
        },
        request_id=request_id,
    )
    return row


def cancel(db: Session, user: User, export_id: uuid.UUID) -> Export:
    row = owned(db, user, export_id)
    if row.state in ACTIVE:
        row.state = "cancelled"
        row.finished_at = clock.now()
    elif row.state == "ready":  # removing a finished one deletes its file at once
        _remove_file(row)
        row.state, row.expires_at = "expired", clock.now()
    return row


def _remove_file(row: Export) -> None:
    for p in (zip_path(row), zip_path(row).with_suffix(".part")):
        try:
            p.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - locked on Windows; the next sweep retries
            log.warning("could not remove export %s", row.id)


# ---------------------------------------------------------------- building (worker)


class Cancelled(Exception):
    pass


def _local(dt: datetime, zone: ZoneInfo, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return dt.astimezone(zone).strftime(fmt)


def _readme(user: User, now: datetime, zone: ZoneInfo, options: dict[str, Any]) -> str:
    parts = []
    if options.get("material"):
        parts.append("  <course>/material/   your files as you uploaded them, in your own folders")
    if options.get("notes"):
        parts.append("  <course>/notes/      your notes as Markdown (.md), exactly as saved; named by date and title")
    if options.get("answers"):
        parts.append("  <course>/answers.csv one row per answer with the grade in force (opens in a spreadsheet)")
        parts.append("  answers.json         every answer with its question, sources and every assessment")
    return (
        f"RecallSpring export\n"
        f"Made {_local(now, zone)} ({user.timezone}) for {user.username}.\n\n"
        "What is in here:\n" + "\n".join(parts) + "\n\n"
        "Times are in your time zone. Grades: 0 No evidence, 1 Fragile, 2 Partial, 3 Solid, 4 Transfer.\n"
        "A grade is an AI (or your own) judgement of one answer against the course material. It is not a\n"
        "validated test score. 'provisional' marks grades given without enough evidence; 'overridden' marks\n"
        "grades you changed (answers.json keeps the original too).\n\n"
        "This export is not encrypted. Keep it where only you can open it.\n"
    )


def _answer_rows(
    db: Session, user: User, courses: list[Course], zone: ZoneInfo
) -> tuple[dict[uuid.UUID, list[dict[str, Any]]], list[dict[str, Any]]]:
    titles = {c.id: c.title for c in courses}
    pairs = list(
        db.execute(
            select(Attempt, Question)
            .join(Question, Question.id == Attempt.question_id)
            .where(Attempt.user_id == user.id, Question.course_id.in_(list(titles)))
            .order_by(Attempt.submitted_at, Attempt.id)
        ).all()
    )
    attempt_ids = [a.id for a, _ in pairs]
    question_ids = list({q.id for _, q in pairs})
    by_attempt: dict[uuid.UUID, list[Assessment]] = {}
    if attempt_ids:
        for row in db.scalars(
            select(Assessment).where(Assessment.attempt_id.in_(attempt_ids)).order_by(Assessment.created_at)
        ):
            by_attempt.setdefault(row.attempt_id, []).append(row)
    terms: dict[uuid.UUID, list[str]] = {}
    if question_ids:
        for qid, term in db.execute(
            select(QuestionConcept.question_id, Concept.term)
            .join(Concept, Concept.id == QuestionConcept.concept_id)
            .where(QuestionConcept.question_id.in_(question_ids))
            .order_by(Concept.term)
        ):
            terms.setdefault(qid, []).append(term)

    csv_rows: dict[uuid.UUID, list[dict[str, Any]]] = {}
    full: list[dict[str, Any]] = []
    for attempt, question in pairs:
        assessments = by_attempt.get(attempt.id, [])
        eff = effective_assessment(assessments)
        who = assistants.grader(eff.evaluator_kind, eff.provider, eff.model) if eff else None
        overridden = bool(eff and eff.evaluator_kind == "human" and eff.supersedes_id)
        concept = "; ".join(terms.get(question.id, []))
        csv_rows.setdefault(question.course_id, []).append(
            {
                "answered_at": _local(attempt.submitted_at, zone),
                "course": titles[question.course_id],
                "concept": concept,
                "question": question.prompt,
                "bloom_level": f"{question.bloom_level} {BLOOM.get(question.bloom_level, '')}".strip(),
                "answer_kind": attempt.kind,
                "your_answer": attempt.answer_text,
                "grade": "" if eff is None or eff.grade is None else eff.grade,
                "grade_label": GRADE_NAMES.get(eff.grade, "") if eff and eff.grade is not None else "Ungraded",
                "provisional": "yes" if eff and eff.status == "provisional" else "no",
                "graded_by": who["name"] if who else "",
                "explanation": eff.feedback if eff else "",
                "overridden": "yes" if overridden else "no",
            }
        )
        full.append(
            {
                "course": titles[question.course_id],
                "concepts": terms.get(question.id, []),
                "question": {
                    "prompt": question.prompt,
                    "bloom_level": question.bloom_level,
                    "type": question.question_type,
                    "options": question.options,
                    "sources": question.source_refs,
                },
                "answer": {
                    "text": attempt.answer_text,
                    "kind": attempt.kind,
                    "selected_option": attempt.selected_option,
                    "unsure": attempt.guessing,
                    "answered_at": attempt.submitted_at.isoformat(),
                    "mode": attempt.answer_mode,
                    "captured_via": attempt.captured_via,
                },
                "grade_in_force": (
                    {
                        "grade": eff.grade,
                        "label": GRADE_NAMES.get(eff.grade) if eff.grade is not None else "Ungraded",
                        "status": eff.status,
                        "graded_by": who,
                        "overridden": overridden,
                    }
                    if eff
                    else None
                ),
                "assessments": [
                    {
                        "graded_by": assistants.grader(a.evaluator_kind, a.provider, a.model),
                        "status": a.status,
                        "grade": a.grade,
                        "confidence": a.confidence,
                        "explanation": a.feedback,
                        "strengths": a.strengths,
                        "gaps": a.gaps,
                        "evidence": a.evidence_refs,
                        "at": a.created_at.isoformat(),
                        "replaces_earlier": bool(a.supersedes_id),
                    }
                    for a in assessments
                ],
            }
        )
    return csv_rows, full


def _csv(rows: list[dict[str, Any]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")  # the BOM lets spreadsheet apps read accented letters


def _folder_paths(db: Session, user: User, course_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    rows = {
        f.id: f
        for f in db.scalars(
            select(SourceFolder).where(
                SourceFolder.user_id == user.id,
                SourceFolder.course_id.in_(course_ids),
                SourceFolder.deleted_at.is_(None),
            )
        )
    }
    paths: dict[uuid.UUID, list[str]] = {}
    for fid in rows:
        chain, seen, cur = [], set(), rows.get(fid)
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            chain.append(safe_name(cur.name, "folder"))
            cur = rows.get(cur.parent_id) if cur.parent_id else None
        paths[fid] = list(reversed(chain))
    return paths


def _still_wanted(export_id: uuid.UUID) -> None:
    with new_session() as db:
        state = db.scalar(select(Export.state).where(Export.id == export_id))
    if state != "running":
        raise Cancelled()


def _progress(export_id: uuid.UUID, done: int, total: int) -> None:
    with new_session() as db:
        row = db.get(Export, export_id)
        if row is not None and row.state == "running":
            row.progress = {"done_files": done, "total_files": total}
            db.commit()


def build(export_id: uuid.UUID) -> None:
    """Make the ZIP. Never raises: failures end as state ``failed`` with a short code."""
    with new_session() as db:
        row = db.get(Export, export_id, with_for_update=True)
        if row is None or row.state not in ACTIVE:
            return
        row.state, row.progress, row.error = "running", {}, None
        db.commit()
    try:
        _build(export_id)
    except Cancelled:
        with new_session() as db:
            row = db.get(Export, export_id)
            if row is not None:
                _remove_file(row)
        log.info("export %s stopped", export_id)
    except Exception as exc:  # noqa: BLE001 - any failure is reported to the learner as one line
        code = "not_enough_space" if isinstance(exc, OSError) and exc.errno == 28 else "export_failed"
        log.exception("export %s failed", export_id)
        with new_session() as db:
            row = db.get(Export, export_id)
            if row is not None and row.state == "running":
                _remove_file(row)
                row.state, row.error, row.finished_at = "failed", code, clock.now()
                db.commit()


def _build(export_id: uuid.UUID) -> None:
    with new_session() as db:
        row = db.get(Export, export_id)
        assert row is not None
        user = db.get(User, row.user_id)
        assert user is not None
        options = dict(row.options)
        ids = [uuid.UUID(x) for x in options["course_ids"]] if options.get("course_ids") is not None else None
        courses = _courses(db, user, ids)
        course_ids = [c.id for c in courses]
        zone = ZoneInfo(user.timezone)
        now = clock.now()
        sources = _sources(db, user, course_ids) if options.get("material") else []
        notes = _notes(db, user, course_ids) if options.get("notes") else []
        csv_rows, full = _answer_rows(db, user, courses, zone) if options.get("answers") else ({}, [])
        folders = _folder_paths(db, user, course_ids) if sources else {}
        readme = _readme(user, now, zone, options)
        target = zip_path(row)
        root = f"RecallSpring export {now.astimezone(zone):%Y-%m-%d}"
        material = [(s.course_id, s.folder_id, s.filename, s.storage_key, s.kind) for s in sources]
        note_rows = [(n.course_id, n.title, n.body, n.saved_at) for n in notes]

    names = Names()
    course_dir: dict[uuid.UUID, str] = {}
    for c in courses:
        course_dir[c.id] = names.take(root, safe_name(c.title, "course"))
    total = len(material) + len(note_rows) + (len(csv_rows) + 1 if options.get("answers") else 0)
    done, last_tick = 0, time.monotonic()

    def tick() -> None:
        nonlocal done, last_tick
        done += 1
        if time.monotonic() - last_tick > 1.0 or done == total:
            _still_wanted(export_id)
            _progress(export_id, done, total)
            last_tick = time.monotonic()

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    counts = {"files": 0, "notes": 0, "answers": len(full)}
    with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr(f"{root}/README.txt", readme)
        for course_id, folder_id, filename, key, kind in material:
            sub = "/".join(["material", *folders.get(folder_id, [])]) if folder_id else "material"
            path = names.take(f"{course_dir[course_id]}/{sub}", safe_name(filename, "document", 160))
            source = blob_path(key)
            if source.exists():
                method = zipfile.ZIP_STORED if kind in STORED_KINDS else zipfile.ZIP_DEFLATED
                zf.write(source, path, compress_type=method)
                counts["files"] += 1
            tick()
        for course_id, title, body, saved_at in note_rows:
            label = f"{_local(saved_at, zone, '%Y-%m-%d')} {safe_name(title, 'note', 100)}"
            zf.writestr(names.take(f"{course_dir[course_id]}/notes", f"{label}.md"), body)
            counts["notes"] += 1
            tick()
        if options.get("answers"):
            for course_id, rows in csv_rows.items():
                zf.writestr(f"{course_dir[course_id]}/answers.csv", _csv(rows))
                tick()
            document = {
                "exported_at": now.isoformat(),
                "timezone": user.timezone,
                "note": "Grades are judgements of single answers, not validated test scores.",
                "grade_names": GRADE_NAMES,
                "answers": full,
            }
            zf.writestr(f"{root}/answers.json", json.dumps(document, ensure_ascii=False, indent=2))
            tick()
    _still_wanted(export_id)
    os.replace(part, target)
    size = target.stat().st_size
    with new_session() as db:
        row = db.get(Export, export_id, with_for_update=True)
        assert row is not None
        if row.state != "running":
            _remove_file(row)
            return
        finished = clock.now()
        row.state, row.finished_at, row.expires_at = "ready", finished, finished + KEEP_FOR
        row.byte_size, row.counts = size, counts
        row.progress = {"done_files": total, "total_files": total}
        db.commit()
    log.info("export %s ready: %s bytes", export_id, size)


# ---------------------------------------------------------------- after


def mark_downloaded(db: Session, user: User, row: Export, request_id: str | None) -> Path:
    if row.state != "ready" or not zip_path(row).exists():
        raise ApiError(410, "export_gone", "This export is no longer kept. Make a new one.")
    row.downloaded_at = clock.now()
    audit(
        db,
        actor_id=user.id,
        action="export.downloaded",
        target_type="export",
        target_id=row.id,
        details={"bytes": row.byte_size},
        request_id=request_id,
    )
    return zip_path(row)


def expire_all() -> int:
    """Delete finished exports past their 24 hours, and leftovers of stopped or failed ones. Never raises."""
    removed = 0
    try:
        with new_session() as db:
            now = clock.now()
            for row in db.scalars(select(Export).where(Export.state == "ready", Export.expires_at <= now)):
                _remove_file(row)
                row.state = "expired"
                removed += 1
            db.commit()
    except Exception:  # noqa: BLE001 - the worker must keep running
        log.exception("export sweep failed")
    return removed


def attention_item(db: Session, user: User) -> dict[str, Any] | None:
    """Today › Needs attention: a finished export waiting to be downloaded, or one that failed."""
    row = _latest(db, user)
    if row is None or row.destination != "download":
        return None
    base = {"kind": "export", "id": str(row.id), "course_id": None}
    if row.state == "ready" and row.downloaded_at is None and row.expires_at and row.expires_at > clock.now():
        return base | {
            "title": "Your export is ready",
            "text": "Download it in Settings → Data & backups → Export; it is kept for 24 hours.",
        }
    if row.state == "failed" and row.finished_at and clock.now() - row.finished_at < KEEP_FOR:
        return base | {"title": "Export failed", "text": "Try again in Settings → Data & backups → Export."}
    return None
