"""Course creation shared by the web app and Claude: one course per title, even from parallel chats."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import Course, User
from .targets import normalise


def ensure_new_title(db: Session, user_id, title: str) -> None:  # type: ignore[no-untyped-def]
    """Raise 409 course_exists when a course with the same title (ignoring case, spaces and punctuation) exists."""
    db.get(User, user_id, with_for_update=True)  # serialises course creation per learner
    wanted = normalise(title)
    for course in db.scalars(select(Course).where(Course.user_id == user_id, Course.deleted_at.is_(None))):
        if normalise(course.title) == wanted:
            raise ApiError(
                409,
                "course_exists",
                f"A course called {course.title} already exists (course_id {course.id}). "
                "Use it instead of adding it again.",
                {"existing": {"id": str(course.id), "title": course.title}},
            )
