"""Study targets (kolokvij / izpit): scope resolution, active target and the study context Claude starts from."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import (
    Concept,
    ConceptSource,
    Course,
    Quiz,
    ReviewState,
    Source,
    SourceSection,
    StudyTarget,
    StudyTargetScope,
    SyllabusItem,
    TargetProfile,
    User,
)
from ..schemas import TargetIn, TargetScopeItem, TargetUpdateIn
from .events import audit
from .ownership import owned

SETUP_QUESTIONS = [
    "What are you preparing for: the 1st kolokvij, the 2nd kolokvij, or the exam (whole course or only a part, "
    "because you already passed something)?",
    "When is it (date)?",
    "From which material to which material (e.g. lectures 1-6, or pages 1-80 of the script)?",
    "Do you have an old kolokvij or exam paper I can use to match the question style?",
    "Anything special to know (allowed aids, only calculations, topics the lecturer emphasises, ...)?",
]


def live_targets(db: Session, course_id: uuid.UUID) -> list[StudyTarget]:
    return list(
        db.scalars(
            select(StudyTarget)
            .where(StudyTarget.course_id == course_id, StudyTarget.deleted_at.is_(None))
            .order_by(StudyTarget.due_date, StudyTarget.created_at)
        )
    )


def active_target(targets: list[StudyTarget], today: date) -> StudyTarget | None:
    """The nearest upcoming target that is today or later; a failed target stays relevant for the retake."""
    upcoming = [t for t in targets if t.status == "upcoming" and t.due_date >= today]
    return upcoming[0] if upcoming else None


def scope_concepts(db: Session, target: StudyTarget) -> set[uuid.UUID]:
    """Concepts covered by a target. No scope rows means the whole course."""
    rows = list(db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)))
    course_concepts = select(Concept.id).where(Concept.course_id == target.course_id, Concept.deleted_at.is_(None))
    if not rows:
        return set(db.scalars(course_concepts))
    concepts: set[uuid.UUID] = set()
    for row in rows:
        if row.kind == "concept" and row.concept_id:
            concepts.add(row.concept_id)
        elif row.kind == "topic" and row.syllabus_item_id:
            concepts |= set(db.scalars(course_concepts.where(Concept.syllabus_item_id == row.syllabus_item_id)))
        elif row.kind in ("source", "pages") and row.source_id:
            section_filter = [SourceSection.source_id == row.source_id]
            if row.kind == "pages":
                section_filter += [
                    SourceSection.page >= (row.page_from or 1),
                    SourceSection.page <= (row.page_to or 100_000),
                ]
            concepts |= set(
                db.scalars(
                    select(ConceptSource.concept_id)
                    .join(SourceSection, SourceSection.id == ConceptSource.section_id)
                    .where(*section_filter)
                )
            )
    return concepts


def scope_view(db: Session, target: StudyTarget) -> list[dict[str, Any]]:
    out = []
    for row in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)):
        item: dict[str, Any] = {"kind": row.kind}
        if row.source_id:
            src = db.get(Source, row.source_id)
            item["source_id"] = str(row.source_id)
            item["filename"] = src.filename if src else None
        if row.kind == "pages":
            item["pages"] = [row.page_from, row.page_to]
        if row.syllabus_item_id:
            item["topic_id"] = str(row.syllabus_item_id)
        if row.concept_id:
            item["concept_id"] = str(row.concept_id)
        out.append(item)
    return out


def latest_profile(db: Session, target_id: uuid.UUID) -> TargetProfile | None:
    return db.scalar(
        select(TargetProfile)
        .where(TargetProfile.target_id == target_id)
        .order_by(TargetProfile.created_at.desc())
        .limit(1)
    )


def profile_view(profile: TargetProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "id": str(profile.id),
        "source_id": str(profile.source_id) if profile.source_id else None,
        "item_types": profile.item_types,
        "bloom_mix": profile.bloom_mix,
        "topic_weights": profile.topic_weights,
        "example_items": profile.example_items,
        "notes": profile.notes,
        "derived_by": profile.model or "assistant",
        "created_at": profile.created_at.isoformat(),
    }


def target_view(db: Session, target: StudyTarget, today: date) -> dict[str, Any]:
    return {
        "id": str(target.id),
        "kind": target.kind,
        "name": target.name,
        "due_date": target.due_date.isoformat(),
        "days_left": (target.due_date - today).days,
        "status": target.status,
        "result": target.result,
        "goal": target.goal,
        "scope_description": target.scope_description,
        "scope": scope_view(db, target),
        "notes": target.notes,
        "concepts_in_scope": len(scope_concepts(db, target)),
        "profile": profile_view(latest_profile(db, target.id)),
    }


def study_context(db: Session, course: Course, today: date, style_percent: int = 75) -> dict[str, Any]:
    """Everything Claude needs at the start of a study session in one course, including whether to ask the
    learner what they are preparing for."""
    targets = live_targets(db, course.id)
    active = active_target(targets, today)
    stale = [t for t in targets if t.status == "upcoming" and t.due_date < today]
    passed = [t for t in targets if t.status == "passed"]
    reasons = []
    if active is None:
        reasons.append("no upcoming target is set for this course")
    if stale:
        reasons.append(
            "a target date has passed; ask whether it was passed, failed or moved: " + ", ".join(t.name for t in stale)
        )
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at.desc()).limit(5))
    return {
        "course": {"id": str(course.id), "title": course.title},
        "today": today.isoformat(),
        "active_target": target_view(db, active, today) if active else None,
        "other_targets": [target_view(db, t, today) for t in targets if t is not active],
        "passed_targets": [t.name for t in passed],
        "needs_setup": bool(reasons),
        "setup_reasons": reasons,
        "ask_learner": SETUP_QUESTIONS if active is None else [],
        "recent_simulations": [
            {
                "quiz_id": str(q.id),
                "title": q.title,
                "status": q.status,
                "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
            }
            for q in quizzes
        ],
        "learning": _learning_counts(db, active) if active else None,
        "rules": [
            "Learn first: concepts that are not_studied are taught (explain, then the learner summarises in the "
            "summary form) before any practice or simulation. RecallSpring refuses practice on unstudied concepts "
            "unless the learner says they already know them or asks for a diagnostic pre-test.",
            "Material of passed targets is in maintenance: keep reviewing it, but give priority to the active target.",
            f"About {style_percent} % of practice questions follow the style of the target's exam profile (past "
            f"papers); the other {100 - style_percent} % are deeper Bloom 4-5 questions for understanding.",
        ],
    }


def _learning_counts(db: Session, target: StudyTarget) -> dict[str, int]:
    from .learning import effective_status

    ids = scope_concepts(db, target)
    counts = {"not_studied": 0, "studied": 0, "known": 0}
    if not ids:
        return counts
    practised = set(db.scalars(select(ReviewState.concept_id).where(ReviewState.concept_id.in_(ids))))
    for concept in db.scalars(select(Concept).where(Concept.id.in_(ids))):
        counts[effective_status(concept, concept.id in practised)] += 1
    return counts


# ---------------------------------------------------------------- writes shared by Claude (connector) and the web app


def scope_rows(
    db: Session, user_id: uuid.UUID, course_id: uuid.UUID, items: list[TargetScopeItem]
) -> list[StudyTargetScope]:
    rows = []
    for item in items:
        if item.kind in ("source", "pages"):
            src = db.get(Source, item.source_id) if item.source_id else None
            if src is None or src.user_id != user_id or src.course_id != course_id or src.deleted_at:
                raise ApiError(422, "invalid_scope", "A scope entry refers to a source that is not in this course.")
            if item.kind == "pages" and (
                item.page_from is None or item.page_to is None or item.page_from > item.page_to
            ):
                raise ApiError(422, "invalid_scope", "A page range needs page_from <= page_to.")
        elif item.kind == "topic":
            topic = db.get(SyllabusItem, item.topic_id) if item.topic_id else None
            if topic is None or topic.user_id != user_id or topic.course_id != course_id:
                raise ApiError(422, "invalid_scope", "A scope entry refers to a topic that is not in this course.")
        else:
            concept = db.get(Concept, item.concept_id) if item.concept_id else None
            if concept is None or concept.user_id != user_id or concept.course_id != course_id:
                raise ApiError(422, "invalid_scope", "A scope entry refers to a concept that is not in this course.")
        rows.append(
            StudyTargetScope(
                kind=item.kind,
                source_id=item.source_id,
                page_from=item.page_from,
                page_to=item.page_to,
                syllabus_item_id=item.topic_id,
                concept_id=item.concept_id,
            )
        )
    return rows


def normalise(name: str) -> str:
    """Case-, space- and punctuation-insensitive form of a name ("1. Kolokvij " == "1 kolokvij")."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def is_same_exam(a: StudyTarget, name: str, kind: str, due: date) -> bool:
    """Two records describe the same exam when the names match, or the type and the date match."""
    return normalise(a.name) == normalise(name) or (a.kind == kind and a.due_date == due)


def find_duplicate(
    db: Session, course_id: uuid.UUID, name: str, kind: str, due: date, exclude: uuid.UUID | None = None
) -> StudyTarget | None:
    for t in live_targets(db, course_id):
        if t.id != exclude and t.status != "cancelled" and is_same_exam(t, name, kind, due):
            return t
    return None


def duplicate_groups(targets: list[StudyTarget]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """For each live target, the other targets of the same course that look like the same exam."""
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for a in targets:
        if a.status == "cancelled":
            continue
        for b in targets:
            if b.id != a.id and b.course_id == a.course_id and b.status != "cancelled":
                if is_same_exam(b, a.name, a.kind, a.due_date):
                    out.setdefault(a.id, []).append(b.id)
    return out


def _brief(t: StudyTarget) -> dict[str, Any]:
    return {"id": str(t.id), "name": t.name, "kind": t.kind, "due_date": t.due_date.isoformat(), "status": t.status}


def create_target(db: Session, user: User, payload: TargetIn, request_id: str, *, origin: str) -> StudyTarget:
    course = owned(db, Course, payload.course_id, user.id, for_update=True)  # serialises parallel chats
    existing = find_duplicate(db, course.id, payload.name, payload.kind, payload.due_date)
    if existing is not None:
        raise ApiError(
            409,
            "target_exists",
            f"{course.title} already has {existing.name} on {existing.due_date.isoformat()} "
            f"(target_id {existing.id}). Update that one instead of adding it again.",
            {"existing": _brief(existing)},
        )
    target = StudyTarget(
        user_id=user.id,
        course_id=payload.course_id,
        kind=payload.kind,
        name=payload.name,
        due_date=payload.due_date,
        scope_description=payload.scope_description,
        notes=payload.notes,
        goal=payload.goal,
    )
    db.add(target)
    db.flush()
    for row in scope_rows(db, user.id, payload.course_id, payload.scope):
        row.target_id = target.id
        db.add(row)
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.created",
        target_type="study_target",
        target_id=target.id,
        details={"name": payload.name, "due_date": payload.due_date.isoformat(), "origin": origin},
        request_id=request_id,
    )
    return target


def update_target(
    db: Session, user: User, target_id: uuid.UUID, payload: TargetUpdateIn, request_id: str, *, origin: str
) -> StudyTarget:
    """Move a date, rename, mark passed/failed, or refine the scope. Audited; nothing is deleted."""
    target = db.get(StudyTarget, target_id, with_for_update=True)
    if target is None or target.user_id != user.id or target.deleted_at is not None:
        raise ApiError(404, "not_found", "Study target not found.")
    changes: dict[str, Any] = {}
    for key in ("name", "kind", "goal", "due_date", "status", "result", "scope_description", "notes"):
        value = getattr(payload, key)
        if value is not None and value != getattr(target, key):
            changes[key] = {"from": str(getattr(target, key)), "to": str(value)}
            setattr(target, key, value)
    if payload.scope is not None:
        new_rows = scope_rows(db, user.id, target.course_id, payload.scope)
        for old in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)):
            db.delete(old)  # scope rows are a derived index of the learner's description, not learning evidence
        for row in new_rows:
            row.target_id = target.id
            db.add(row)
        changes["scope"] = {"entries": len(new_rows)}
    target.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.updated",
        target_type="study_target",
        target_id=target.id,
        details={**changes, "origin": origin},
        request_id=request_id,
    )
    return target


def _owned_target(db: Session, user: User, target_id: uuid.UUID, *, deleted: bool = False) -> StudyTarget:
    target = db.get(StudyTarget, target_id, with_for_update=True)
    if target is None or target.user_id != user.id or (target.deleted_at is not None) != deleted:
        raise ApiError(404, "not_found", "Study target not found.")
    return target


def delete_target(db: Session, user: User, target_id: uuid.UUID, request_id: str, now: Any) -> StudyTarget:
    """Soft delete: hidden from plans, the timeline and Claude; restorable. Simulations and answers are kept."""
    target = _owned_target(db, user, target_id)
    target.deleted_at = now
    target.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.deleted",
        target_type="study_target",
        target_id=target.id,
        details=_brief(target),
        request_id=request_id,
    )
    return target


def restore_target(db: Session, user: User, target_id: uuid.UUID, request_id: str) -> StudyTarget:
    target = _owned_target(db, user, target_id, deleted=True)
    target.deleted_at = None
    target.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.restored",
        target_type="study_target",
        target_id=target.id,
        details=_brief(target),
        request_id=request_id,
    )
    return target


def merge_targets(
    db: Session, user: User, source_id: uuid.UUID, into_id: uuid.UUID, request_id: str, now: Any
) -> StudyTarget:
    """Fold a duplicate into the target to keep: its exam profiles and simulations move over, its scope mapping is
    used when the kept one has none, and its own words are added to the kept one's notes. The duplicate is then
    soft-deleted (restorable)."""
    if source_id == into_id:
        raise ApiError(422, "same_target", "Choose two different exams to merge.")
    source = _owned_target(db, user, source_id)
    into = _owned_target(db, user, into_id)
    if source.course_id != into.course_id:
        raise ApiError(422, "different_courses", "Only exams of the same course can be merged.")
    moved_profiles = 0
    for profile in db.scalars(select(TargetProfile).where(TargetProfile.target_id == source.id)):
        profile.target_id = into.id
        moved_profiles += 1
    moved_quizzes = 0
    for quiz in db.scalars(select(Quiz).where(Quiz.target_id == source.id)):
        quiz.target_id = into.id
        moved_quizzes += 1
    copied_scope = 0
    if db.scalar(select(StudyTargetScope.id).where(StudyTargetScope.target_id == into.id).limit(1)) is None:
        for row in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == source.id)):
            db.add(
                StudyTargetScope(
                    target_id=into.id,
                    kind=row.kind,
                    source_id=row.source_id,
                    page_from=row.page_from,
                    page_to=row.page_to,
                    syllabus_item_id=row.syllabus_item_id,
                    concept_id=row.concept_id,
                )
            )
            copied_scope += 1
    extra = []
    if source.scope_description.strip() and source.scope_description.strip() != into.scope_description.strip():
        extra.append(f"Scope (from {source.name}): {source.scope_description.strip()}")
    if source.notes and source.notes.strip() and source.notes.strip() not in (into.notes or ""):
        extra.append(f"Notes (from {source.name}): {source.notes.strip()}")
    if extra:
        into.notes = "\n\n".join([*(p for p in [into.notes] if p), *extra])[:4000]
    into.revision += 1
    source.deleted_at = now
    source.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.merged",
        target_type="study_target",
        target_id=into.id,
        details={
            "merged": _brief(source),
            "profiles_moved": moved_profiles,
            "simulations_moved": moved_quizzes,
            "scope_rows_copied": copied_scope,
        },
        request_id=request_id,
    )
    return into
