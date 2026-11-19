"""Owner-scoped lookups. Every read of a learner record goes through these helpers (T-15)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import not_found
from ..models import Attempt, Concept, Course, Question, StudySession

_LABELS = {Course: "Course", Concept: "Concept", Question: "Question", Attempt: "Attempt", StudySession: "Session"}


def owned[T: (Course, Concept, Question, Attempt, StudySession)](
    db: Session, model: type[T], entity_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
) -> T:
    stmt = select(model).where(model.id == entity_id, model.user_id == user_id)
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))  # type: ignore[union-attr]
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        # Same response for "missing" and "someone else's" so IDs cannot be probed.
        raise not_found(_LABELS[model])
    return row
