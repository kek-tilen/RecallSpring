"""The learner's own folders in the library, and archiving material.

Folders are optional: material without a folder sits at the top level of its course, and the library also groups
everything by university, semester, course and kind on its own. Folders live inside one course and can be nested.
Archiving a file or a folder hides it from the library and from search; nothing is deleted, existing citations keep
working and everything can be restored. Only an empty folder can be removed (soft delete, audited).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError, not_found
from ..models import Course, CourseGroup, Source, SourceFolder, User
from .events import audit, learning_event
from .ownership import owned

MAX_DEPTH = 5
MAX_FOLDERS_PER_COURSE = 300
MAX_NAME = 120
_SPACES = re.compile(r"\s+")


def clean_name(name: str) -> str:
    """One line, no slashes (a slash separates folders in a path), at most 120 characters."""
    value = _SPACES.sub(" ", name.replace("/", "-").replace("\\", "-")).strip().strip(".")
    if not value:
        raise ApiError(422, "folder_name_required", "Give the folder a name.")
    return value[:MAX_NAME]


def _all(db: Session, user_id: uuid.UUID, course_id: uuid.UUID | None = None) -> list[SourceFolder]:
    stmt = select(SourceFolder).where(SourceFolder.user_id == user_id, SourceFolder.deleted_at.is_(None))
    if course_id is not None:
        stmt = stmt.where(SourceFolder.course_id == course_id)
    return list(db.scalars(stmt.order_by(SourceFolder.name)))


def get(db: Session, user_id: uuid.UUID, folder_id: uuid.UUID, *, lock: bool = False) -> SourceFolder:
    stmt = select(SourceFolder).where(
        SourceFolder.id == folder_id, SourceFolder.user_id == user_id, SourceFolder.deleted_at.is_(None)
    )
    folder = db.scalar(stmt.with_for_update() if lock else stmt)
    if folder is None:
        raise not_found("Folder")
    return folder


class Tree:
    """All folders of one learner, for paths, depth and the archived state inherited from parent folders."""

    def __init__(self, folders: Iterable[SourceFolder]) -> None:
        self.by_id = {f.id: f for f in folders}

    def chain(self, folder_id: uuid.UUID | None) -> list[SourceFolder]:
        """The folder and its parents, top first."""
        out: list[SourceFolder] = []
        seen: set[uuid.UUID] = set()
        while folder_id is not None and folder_id in self.by_id and folder_id not in seen:
            seen.add(folder_id)
            folder = self.by_id[folder_id]
            out.append(folder)
            folder_id = folder.parent_id
        return list(reversed(out))

    def path(self, folder_id: uuid.UUID | None) -> str | None:
        names = [f.name for f in self.chain(folder_id)]
        return " / ".join(names) if names else None

    def hidden(self, folder_id: uuid.UUID | None) -> bool:
        """True when the folder or one of its parents is archived."""
        return any(f.archived_at is not None for f in self.chain(folder_id))

    def descendants(self, folder_id: uuid.UUID) -> set[uuid.UUID]:
        out = {folder_id}
        changed = True
        while changed:
            changed = False
            for f in self.by_id.values():
                if f.parent_id in out and f.id not in out:
                    out.add(f.id)
                    changed = True
        return out

    def height(self, folder_id: uuid.UUID) -> int:
        """Levels from this folder down to its deepest subfolder (1 = no subfolders)."""
        children = [f.id for f in self.by_id.values() if f.parent_id == folder_id]
        return 1 + max((self.height(c) for c in children), default=0)

    def hidden_ids(self) -> set[uuid.UUID]:
        return {fid for fid in self.by_id if self.hidden(fid)}


def tree(db: Session, user_id: uuid.UUID) -> Tree:
    return Tree(_all(db, user_id))


def folder_view(folder: SourceFolder, t: Tree, files: int = 0) -> dict[str, Any]:
    return {
        "id": str(folder.id),
        "course_id": str(folder.course_id),
        "parent_id": str(folder.parent_id) if folder.parent_id else None,
        "name": folder.name,
        "path": t.path(folder.id),
        "archived": folder.archived_at is not None,
        "hidden": t.hidden(folder.id),
        "archived_at": folder.archived_at.isoformat() if folder.archived_at else None,
        "files": files,
        "revision": folder.revision,
        "created_at": folder.created_at.isoformat(),
    }


def _file_counts(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    counts: dict[uuid.UUID, int] = {}
    for fid in db.scalars(
        select(Source.folder_id).where(
            Source.user_id == user_id, Source.deleted_at.is_(None), Source.folder_id.is_not(None)
        )
    ):
        counts[fid] = counts.get(fid, 0) + 1
    return counts


def list_views(db: Session, user: User, course_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    t = tree(db, user.id)
    counts = _file_counts(db, user.id)
    rows = [f for f in t.by_id.values() if course_id is None or f.course_id == course_id]
    rows.sort(key=lambda f: (str(f.course_id), (t.path(f.id) or "").casefold()))
    return [folder_view(f, t, counts.get(f.id, 0)) for f in rows]


def _sibling(
    db: Session, user_id: uuid.UUID, course_id: uuid.UUID, parent_id: uuid.UUID | None, name: str
) -> SourceFolder | None:
    stmt = select(SourceFolder).where(
        SourceFolder.user_id == user_id,
        SourceFolder.course_id == course_id,
        SourceFolder.deleted_at.is_(None),
        SourceFolder.parent_id.is_(None) if parent_id is None else SourceFolder.parent_id == parent_id,
    )
    key = name.casefold()
    return next((f for f in db.scalars(stmt) if f.name.casefold() == key), None)


def _exists(existing: SourceFolder) -> ApiError:
    return ApiError(
        409,
        "folder_exists",
        f"A folder called “{existing.name}” is already there.",
        details={"folder_id": str(existing.id)},
    )


def create(
    db: Session,
    user: User,
    course_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    name: str,
    request_id: str | None,
    *,
    via: str = "web",
) -> SourceFolder:
    course = owned(db, Course, course_id, user.id)
    name = clean_name(name)
    t = tree(db, user.id)
    if parent_id is not None:
        parent = get(db, user.id, parent_id)
        if parent.course_id != course.id:
            raise ApiError(409, "different_course", "The parent folder belongs to another course.")
        if len(t.chain(parent.id)) + 1 > MAX_DEPTH:
            raise ApiError(422, "folder_too_deep", f"Folders can be nested at most {MAX_DEPTH} levels deep.")
    if sum(1 for f in t.by_id.values() if f.course_id == course.id) >= MAX_FOLDERS_PER_COURSE:
        raise ApiError(422, "too_many_folders", f"A course can hold at most {MAX_FOLDERS_PER_COURSE} folders.")
    if existing := _sibling(db, user.id, course.id, parent_id, name):
        raise _exists(existing)
    folder = SourceFolder(user_id=user.id, course_id=course.id, parent_id=parent_id, name=name)
    db.add(folder)
    db.flush()
    learning_event(
        db,
        user_id=user.id,
        entity_type="folder",
        entity_id=folder.id,
        event_type="folder.created",
        payload={
            "name": name,
            "course_id": str(course.id),
            "parent_id": str(parent_id) if parent_id else None,
            "via": via,
        },
        request_id=request_id,
    )
    return folder


def resolve_path(
    db: Session,
    user: User,
    course_id: uuid.UUID,
    path: str | None,
    request_id: str | None,
    base_id: uuid.UUID | None = None,
    *,
    via: str = "connector",
) -> SourceFolder | None:
    """A folder path such as "Lectures / Week 3" (slashes separate levels) below ``base_id`` (or the course's top
    level), created where missing. Used when Claude imports into a folder by name and for uploaded folders and ZIPs.
    A blank path means ``base_id`` itself."""
    owned(db, Course, course_id, user.id)
    base: SourceFolder | None = None
    if base_id is not None:
        base = get(db, user.id, base_id)
        if base.course_id != course_id:
            raise ApiError(409, "different_course", "The folder belongs to another course.")
    if path is None or not path.strip():
        return base
    parts = [p for p in (s.strip() for s in re.split(r"[/\\]", path)) if p]
    if not parts:
        return base
    above = len(tree(db, user.id).chain(base.id)) if base else 0
    if above + len(parts) > MAX_DEPTH:
        raise ApiError(422, "folder_too_deep", f"Folders can be nested at most {MAX_DEPTH} levels deep.")
    parent = base
    for part in parts:
        name = clean_name(part)
        found = _sibling(db, user.id, course_id, parent.id if parent else None, name)
        parent = found or create(db, user, course_id, parent.id if parent else None, name, request_id, via=via)
    return parent


def update(
    db: Session,
    user: User,
    folder: SourceFolder,
    *,
    name: str | None,
    move: bool,
    parent_id: uuid.UUID | None,
    request_id: str | None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    new_parent = folder.parent_id
    if move and parent_id != folder.parent_id:
        t = tree(db, user.id)
        if parent_id is not None:
            parent = get(db, user.id, parent_id)
            if parent.course_id != folder.course_id:
                raise ApiError(409, "different_course", "Folders can only move within their course.")
            if parent.id in t.descendants(folder.id):
                raise ApiError(409, "folder_cycle", "A folder cannot move into itself or one of its subfolders.")
            if len(t.chain(parent.id)) + t.height(folder.id) > MAX_DEPTH:
                raise ApiError(422, "folder_too_deep", f"Folders can be nested at most {MAX_DEPTH} levels deep.")
        new_parent = parent_id
        changes["parent_id"] = {"from": str(folder.parent_id), "to": str(parent_id)}
    new_name = clean_name(name) if name is not None else folder.name
    if new_name != folder.name:
        changes["name"] = {"from": folder.name, "to": new_name}
    if changes:
        existing = _sibling(db, user.id, folder.course_id, new_parent, new_name)
        if existing is not None and existing.id != folder.id:
            raise _exists(existing)
        folder.name, folder.parent_id = new_name, new_parent
        folder.revision += 1
        db.flush()
        learning_event(
            db,
            user_id=user.id,
            entity_type="folder",
            entity_id=folder.id,
            event_type="folder.updated",
            payload=changes,
            request_id=request_id,
        )
    return changes


def set_archived(db: Session, user: User, folder: SourceFolder, archived: bool, request_id: str | None) -> None:
    if (folder.archived_at is not None) == archived:
        return
    folder.archived_at = clock.now() if archived else None
    folder.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="folder.archived" if archived else "folder.restored",
        target_type="source_folder",
        target_id=folder.id,
        details={"name": folder.name, "course_id": str(folder.course_id)},
        request_id=request_id,
    )


def remove(db: Session, user: User, folder: SourceFolder, request_id: str | None) -> None:
    """Soft-delete an empty folder (no files, no subfolders). Folders with content are archived instead."""
    files = db.scalar(select(Source.id).where(Source.folder_id == folder.id, Source.deleted_at.is_(None)).limit(1))
    children = db.scalar(
        select(SourceFolder.id).where(SourceFolder.parent_id == folder.id, SourceFolder.deleted_at.is_(None)).limit(1)
    )
    if files is not None or children is not None:
        raise ApiError(
            409,
            "folder_not_empty",
            "Only an empty folder can be removed. Move its files out first, or archive the folder instead.",
        )
    folder.deleted_at = clock.now()
    folder.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="folder.removed",
        target_type="source_folder",
        target_id=folder.id,
        details={"name": folder.name, "course_id": str(folder.course_id)},
        request_id=request_id,
    )


def _sources(db: Session, user: User, source_ids: list[uuid.UUID]) -> list[Source]:
    rows = list(
        db.scalars(
            select(Source)
            .where(Source.user_id == user.id, Source.id.in_(source_ids), Source.deleted_at.is_(None))
            .with_for_update()
        )
    )
    if len(rows) != len(set(source_ids)):
        raise not_found("Source")
    return rows


def move_sources(
    db: Session, user: User, source_ids: list[uuid.UUID], folder_id: uuid.UUID | None, request_id: str | None
) -> list[Source]:
    """File material into a folder of its course, or back to the course's top level (``folder_id`` null)."""
    rows = _sources(db, user, source_ids)
    folder = get(db, user.id, folder_id) if folder_id is not None else None
    if folder is not None and any(s.course_id != folder.course_id for s in rows):
        raise ApiError(409, "different_course", "Material can only move into folders of its own course.")
    moved = [s for s in rows if s.folder_id != folder_id]
    for s in moved:
        learning_event(
            db,
            user_id=user.id,
            entity_type="source",
            entity_id=s.id,
            event_type="source.moved",
            payload={"from": str(s.folder_id) if s.folder_id else None, "to": str(folder_id) if folder_id else None},
            request_id=request_id,
        )
        s.folder_id = folder_id
    db.flush()
    return rows


def archive_sources(
    db: Session, user: User, source_ids: list[uuid.UUID], archived: bool, request_id: str | None
) -> list[Source]:
    rows = _sources(db, user, source_ids)
    now: datetime = clock.now()
    changed = [s for s in rows if (s.archived_at is not None) != archived]
    for s in changed:
        s.archived_at = now if archived else None
    db.flush()
    if changed:
        audit(
            db,
            actor_id=user.id,
            action="source.archived" if archived else "source.restored",
            target_type="source",
            target_id=changed[0].id if len(changed) == 1 else None,
            details={"sources": [str(s.id) for s in changed]},
            request_id=request_id,
        )
    return rows


def archived_view(db: Session, user: User) -> dict[str, Any]:
    """Everything archived in one place, each with what is needed to restore it."""
    from . import overview
    from .sources import source_view

    t = tree(db, user.id)
    counts = _file_counts(db, user.id)
    titles = {c.id: c for c in db.scalars(select(Course).where(Course.user_id == user.id, Course.deleted_at.is_(None)))}

    def course_ref(course_id: uuid.UUID) -> dict[str, Any]:
        c = titles.get(course_id)
        return {"id": str(course_id), "title": c.title if c else "", "color": c.color if c else None}

    groups = [
        overview.group_view(g, 0) | {"path": " › ".join(overview.group_path(db, g.id))}
        for g in db.scalars(
            select(CourseGroup)
            .where(CourseGroup.user_id == user.id, CourseGroup.deleted_at.is_(None), CourseGroup.status == "archived")
            .order_by(CourseGroup.archived_at.desc())
        )
    ]
    courses = [
        overview.course_view(c) | {"group_path": " › ".join(overview.group_path(db, c.group_id))}
        for c in sorted(titles.values(), key=lambda c: c.title.casefold())
        if c.status == "archived"
    ]
    folders = [
        folder_view(f, t, counts.get(f.id, 0)) | {"course": course_ref(f.course_id)}
        for f in sorted(t.by_id.values(), key=lambda f: f.archived_at or f.created_at, reverse=True)
        if f.archived_at is not None
    ]
    sources = [
        source_view(db, s, t) | {"course": course_ref(s.course_id)}
        for s in db.scalars(
            select(Source)
            .where(Source.user_id == user.id, Source.deleted_at.is_(None), Source.archived_at.is_not(None))
            .order_by(Source.archived_at.desc())
        )
    ]
    return {"groups": groups, "courses": courses, "folders": folders, "sources": sources}
