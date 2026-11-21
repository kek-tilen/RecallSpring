"""Many files at once: a ZIP of course material (folders inside become library folders) and the files found in a
ChatGPT data export. Every file passes the same checks as a single upload; files that do not fit are skipped with a
reason instead of failing the whole import.

ZIP safety: at most ``MAX_ENTRIES`` entries; names are reduced to plain path segments (no absolute paths, no
``..``), hidden and system entries are skipped, encrypted entries are skipped, and every member is copied through
``spool`` with its own size limit, so a member that inflates beyond its limit is stopped while it is read.
"""

from __future__ import annotations

import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..ingest.storage import (
    ALLOWED_EXTENSIONS,
    PACKAGE_KINDS,
    TEXT_KINDS,
    UNSUPPORTED_OFFICE,
    StorageError,
    check_office_package,
    check_text_encoding,
    sanitize_filename,
    sniff,
    spool,
    upload_limit,
)
from ..models import Source, User
from . import folders as folder_svc
from .events import audit
from .sources import create_source

MAX_ENTRIES = 2000
SKIPPED_DIRS = {"__macosx", ".git", "node_modules", "__pycache__", ".ipynb_checkpoints"}
REASONS = {
    "unsupported_file_type": "this type of file is not supported",
    "office_format_unsupported": "old Office format; save it as .docx/.pptx/.xlsx",
    "office_protected": "password-protected",
    "content_does_not_match_type": "the content does not match the file type",
    "file_too_large": "too large for its type",
    "unsupported_encoding": "not UTF-8 text",
    "office_unreadable": "could not be read",
    "document_too_large": "too large to read safely",
    "encrypted": "encrypted in the ZIP",
    "library_full": "the library is full",
    "storage_low": "the disk is almost full",
    "already_there": "already in this folder",
}


@dataclass
class Result:
    imported: list[Source] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def skip(self, name: str, code: str) -> None:
        self.skipped.append({"name": name, "reason": REASONS.get(code, code.replace("_", " "))})


def member_parts(name: str) -> list[str] | None:
    """Plain path segments of a ZIP member, or None when it must be skipped (directory, hidden, unsafe)."""
    if name.endswith("/") or name.endswith("\\"):
        return None
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("", "/")]
    if not parts or any(p in (".", "..") or p.startswith(".") or p.casefold() in SKIPPED_DIRS for p in parts):
        return None
    if parts[-1].casefold() in ("thumbs.db", "desktop.ini"):
        return None
    return parts


def ingest_member(
    db: Session,
    user: User,
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    filename: str,
    course_id: uuid.UUID,
    folder_id: uuid.UUID | None,
    category: str,
    origin: str,
    request_id: str,
    result: Result,
    label: str,
) -> Source | None:
    """Check one member like an upload and store it; on a problem record why it was skipped."""
    filename = sanitize_filename(filename)
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        result.skip(label, "unsupported_file_type")
        return None
    if info.flag_bits & 0x1:
        result.skip(label, "encrypted")
        return None
    limit = upload_limit(filename)
    if info.file_size > limit:
        result.skip(label, "file_too_large")
        return None
    try:
        with zf.open(info) as stream:
            tmp, sha256, size = spool(stream, limit)
    except StorageError as exc:
        result.skip(label, exc.code)
        return None
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError):
        result.skip(label, "office_unreadable")
        return None
    try:
        with tmp.open("rb") as fh:
            kind, mime = sniff(fh.read(16), filename)
        if kind in TEXT_KINDS or kind == "notebook":
            check_text_encoding(tmp, kind)
        elif kind in PACKAGE_KINDS:
            check_office_package(tmp, kind)
    except StorageError as exc:
        tmp.unlink(missing_ok=True)
        result.skip(label, exc.code)
        return None
    if already_there(db, user, course_id, folder_id, sha256):
        tmp.unlink(missing_ok=True)
        result.skip(label, "already_there")
        return None
    try:
        with db.begin_nested():
            source = create_source(
                db,
                user=user,
                course_id=course_id,
                tmp=tmp,
                sha256=sha256,
                size=size,
                filename=filename,
                kind=kind,
                mime=mime,
                origin=origin,
                request_id=request_id,
                category=category,
                folder_id=folder_id,
            )
    except ApiError as exc:
        tmp.unlink(missing_ok=True)
        if exc.code in ("library_full", "storage_low"):
            result.skip(label, exc.code)
            return None
        raise
    result.imported.append(source)
    return source


def already_there(
    db: Session, user: User, course_id: uuid.UUID, folder_id: uuid.UUID | None, sha256: str
) -> Source | None:
    """The same content already filed in this course and folder (importing the same ZIP twice adds nothing)."""
    return db.scalar(
        select(Source)
        .where(
            Source.user_id == user.id,
            Source.course_id == course_id,
            Source.sha256 == sha256,
            Source.deleted_at.is_(None),
            Source.folder_id.is_(None) if folder_id is None else Source.folder_id == folder_id,
        )
        .limit(1)
    )


def open_zip(path: Path, max_entries: int = MAX_ENTRIES) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ApiError(422, "not_a_zip", "This is not a ZIP file RecallSpring can read.") from exc
    if len(zf.infolist()) > max_entries:
        zf.close()
        raise ApiError(422, "zip_too_many_files", f"The ZIP holds more than {max_entries} entries; split it.")
    return zf


def _folder_for(
    db: Session,
    user: User,
    course_id: uuid.UUID,
    base: uuid.UUID | None,
    dirs: list[str],
    request_id: str,
    cache: dict[tuple[str, ...], uuid.UUID | None],
) -> uuid.UUID | None:
    """The library folder for a ZIP directory path below ``base``; levels beyond the nesting limit are joined."""
    if not dirs:
        return base
    key = tuple(dirs)
    if key in cache:
        return cache[key]
    t = folder_svc.tree(db, user.id)
    room = folder_svc.MAX_DEPTH - len(t.chain(base))
    if room <= 0:
        cache[key] = base
        return base
    names = dirs[: room - 1] + [" - ".join(dirs[room - 1 :])] if len(dirs) > room else dirs
    folder = folder_svc.resolve_path(db, user, course_id, " / ".join(names), request_id, base, via="import")
    cache[key] = folder.id if folder else base
    return cache[key]


def import_zip(
    db: Session,
    user: User,
    path: Path,
    *,
    course_id: uuid.UUID,
    folder_id: uuid.UUID | None,
    category: str,
    request_id: str,
) -> Result:
    """Every supported file of a ZIP into the course, keeping its folders (below ``folder_id`` when given)."""
    if folder_id is not None and folder_svc.get(db, user.id, folder_id).course_id != course_id:
        raise ApiError(409, "different_course", "The folder belongs to another course.")
    result = Result()
    cache: dict[tuple[str, ...], uuid.UUID | None] = {}
    with open_zip(path) as zf:
        for info in zf.infolist():
            parts = member_parts(info.filename)
            if parts is None:
                continue
            label = "/".join(parts)
            suffix = Path(parts[-1]).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                old_office = suffix in UNSUPPORTED_OFFICE
                result.skip(label, "office_format_unsupported" if old_office else "unsupported_file_type")
                continue
            target = _folder_for(db, user, course_id, folder_id, parts[:-1], request_id, cache)
            ingest_member(
                db,
                user,
                zf,
                info,
                filename=parts[-1],
                course_id=course_id,
                folder_id=target,
                category=category,
                origin="upload",
                request_id=request_id,
                result=result,
                label=label,
            )
    audit(
        db,
        actor_id=user.id,
        action="source.zip_imported",
        target_type="course",
        target_id=course_id,
        details={
            "folder_id": str(folder_id) if folder_id else None,
            "imported": len(result.imported),
            "skipped": len(result.skipped),
        },
        request_id=request_id,
    )
    return result


def result_view(db: Session, user: User, result: Result) -> dict[str, Any]:
    from .sources import source_view

    t = folder_svc.tree(db, user.id)
    return {"imported": [source_view(db, s, t) for s in result.imported], "skipped": result.skipped}
