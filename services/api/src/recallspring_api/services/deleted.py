"""Everything the learner deleted in the last 30 days, in one list (Settings › Data & backups › Recently deleted).

Read-only: restoring uses each item's own endpoint. Items of a deleted course are not listed on their own; they come
back with the course (they carry its ``deleted_at`` stamp) and the course line says what it brings back. Explanation
versions stay with their explanation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import AiConversation, Course, FocusSession, Note, Source, StudyTarget, User

RESTORE_DAYS = 30


def _item(
    kind: str, id_: uuid.UUID, title: str, deleted_at: datetime, course: str | None, **extra: Any
) -> dict[str, Any]:
    return {
        "type": kind,
        "id": str(id_),
        "title": title,
        "course_title": course,
        "deleted_at": deleted_at.isoformat(),
        "restorable_until": (deleted_at + timedelta(days=RESTORE_DAYS)).isoformat(),
        **extra,
    }


def recently_deleted(db: Session, user: User) -> dict[str, Any]:
    since = clock.now() - timedelta(days=RESTORE_DAYS)
    gone = set(db.scalars(select(Course.id).where(Course.user_id == user.id, Course.deleted_at.is_not(None))))
    titles = {cid: name for cid, name in db.execute(select(Course.id, Course.title).where(Course.user_id == user.id))}
    items: list[dict[str, Any]] = []

    def brought(model: Any, course: Course) -> int:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.course_id == course.id, model.deleted_at == course.deleted_at)
        )
        return db.scalar(stmt) or 0

    for c in db.scalars(
        select(Course).where(Course.user_id == user.id, Course.deleted_at.is_not(None), Course.deleted_at >= since)
    ):
        with_ = {"notes": brought(Note, c), "exams": brought(StudyTarget, c), "materials": brought(Source, c)}
        assert c.deleted_at is not None
        items.append(_item("course", c.id, c.title, c.deleted_at, None, color=c.color, brings=with_))

    def recent(model: Any) -> list[Any]:
        stmt = select(model).where(model.user_id == user.id, model.deleted_at.is_not(None), model.deleted_at >= since)
        return [r for r in db.scalars(stmt) if r.course_id not in gone]

    for t in recent(StudyTarget):
        due = t.due_date.isoformat()
        items.append(_item("exam", t.id, t.name, t.deleted_at, titles.get(t.course_id), due_date=due))
    for n in recent(Note):
        items.append(_item("note", n.id, n.title, n.deleted_at, titles.get(n.course_id)))
    for f in recent(FocusSession):
        extra = {"started_at": f.started_at.isoformat(), "ended_at": f.ended_at.isoformat()}
        items.append(_item("focus", f.id, "Focus block", f.deleted_at, titles.get(f.course_id), **extra))
    for a in recent(AiConversation):
        items.append(_item("chat", a.id, a.title, a.deleted_at, titles.get(a.course_id)))

    items.sort(key=lambda i: i["deleted_at"], reverse=True)
    return {"restorable_days": RESTORE_DAYS, "items": items}
