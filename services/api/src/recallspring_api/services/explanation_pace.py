"""Explanation pace (2026-11-26; migration 0035).

How an assistant explains new material: step by step, balanced, in larger chunks, or auto (it adapts). The learner
sets a default in Settings and may choose another one for a course. A request in a chat holds for that conversation
only; the assistant offers once to save it, and saves it only on the learner's yes. Every pace still explains
completely and concretely; only the size of each part changes. Nothing here calls a model. (Not services/pace.py,
which estimates review minutes from answer timing.)
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.orm import Session

from ..models import Course, User
from .events import audit

Pace = Literal["step", "balanced", "chunks", "auto"]
PACES: tuple[str, ...] = ("step", "balanced", "chunks", "auto")
DEFAULT = "auto"

LABEL = {"step": "Step by step", "balanced": "Balanced", "chunks": "Larger chunks", "auto": "Auto"}
HOW = {
    "step": "One small part at a time (one idea with its example), then a quick check or a question before the "
    "next part.",
    "balanced": "One section at a time with its examples, then a short check before the next section.",
    "chunks": "A whole topic (several sections) in one go, complete, then the learner's questions and the checks.",
    "auto": "Choose per part: smaller steps for new, hard (difficulty 4-5) or weakly answered material, larger chunks "
    "for familiar material and reviews; say briefly when you change the size.",
}
HOW_TO_USE = (
    "How to pace explanations of new material. Every pace explains completely and concretely; only the size of each "
    "part changes. When the learner asks for another pace in the conversation, follow it for this conversation and "
    "offer once to save it, for this course or as their default; never save it without their yes."
)


def view(user: User, course: Course | None = None) -> dict[str, Any]:
    """The pace an assistant follows: the course's own choice, else the learner's default."""
    own = course.explanation_pace if course is not None else None
    default = user.explanation_pace or DEFAULT
    pace = own or default
    return {
        "pace": pace,
        "label": LABEL[pace],
        "source": "course" if own else "default",
        "default": default,
        "how": HOW[pace],
        "how_to_use": HOW_TO_USE,
    }


def set_default(db: Session, user: User, pace: str, request_id: str | None, origin: str) -> None:
    before = user.explanation_pace
    if pace == before:
        return
    user.explanation_pace = pace
    audit(
        db,
        actor_id=user.id,
        action="settings.explanation_pace",
        details={"from": before, "to": pace, "origin": origin},
        request_id=request_id,
    )


def set_for_course(
    db: Session, user_id: uuid.UUID, course: Course, pace: str | None, request_id: str | None, origin: str
) -> None:
    """``pace`` None: the course follows the learner's default again."""
    before = course.explanation_pace
    if pace == before:
        return
    course.explanation_pace = pace
    audit(
        db,
        actor_id=user_id,
        action="course.explanation_pace",
        target_type="course",
        target_id=course.id,
        details={"from": before, "to": pace, "origin": origin},
        request_id=request_id,
    )
