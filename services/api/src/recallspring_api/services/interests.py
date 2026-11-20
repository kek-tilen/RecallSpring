"""Personal interests and the focus period, shared by the web app and Claude (ADR-007).

An *interest* is a course of kind ``interest``: learning without a deadline (e.g. data analysis or computer vision
in free time). It has a goal (its description) instead of exams and is not filed under a semester. The planner gives
interests the time left after university work unless the learner keeps a share of the day for them or chooses a
focus. Nothing here calls a model.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import Course, StudyTarget, User
from .events import audit
from .ownership import owned

MAX_FOCUS_DAYS = 60

INTEREST_QUESTIONS = [
    "What do you want to be able to do (e.g. analyse a dataset with pandas, train an image classifier)?",
    "What do you already know about it, and what is your level?",
    "Which material do you use: an online course, a book, notebooks, documentation? Import it or name it.",
    "How should it fit around your university work: only when your exams are on track (university first), a "
    "fixed share of each day, or a focus on it for a while?",
]


def user_today(user: User) -> date:
    return clock.now().astimezone(ZoneInfo(user.timezone)).date()


def refuse_interest_exam(course: Course) -> None:
    if course.kind == "interest":
        raise ApiError(
            422,
            "interest_has_no_exams",
            f"{course.title} is a personal interest, so it has no exams. To prepare for a dated exam or certificate, "
            "turn it into a course first (Courses → Edit → Type).",
        )


def refuse_interest_filing(course: Course) -> None:
    if course.kind == "interest":
        raise ApiError(
            422,
            "interest_not_filed",
            f"{course.title} is a personal interest; interests are not filed under a university or semester.",
        )


def change_kind(db: Session, course: Course, kind: str) -> dict[str, Any] | None:
    """Turn a course into an interest or back. An interest leaves its semester; a course with upcoming exams can
    not become an interest (the exams would lose their meaning)."""
    if kind == course.kind:
        return None
    if kind == "interest":
        upcoming = db.scalar(
            select(StudyTarget.name)
            .where(
                StudyTarget.course_id == course.id,
                StudyTarget.deleted_at.is_(None),
                StudyTarget.status == "upcoming",
            )
            .limit(1)
        )
        if upcoming is not None:
            raise ApiError(
                409,
                "course_has_exams",
                f"{course.title} still has upcoming exams ({upcoming}). Record their result, cancel or delete them "
                "before turning the course into an interest.",
            )
        course.group_id = None
    change = {"from": course.kind, "to": kind}
    course.kind = kind
    return change


def focus_view(db: Session, user: User) -> dict[str, Any] | None:
    from .planner import focus_course

    course = focus_course(db, user.id, user_today(user))
    if course is None or course.focus_until is None:
        return None
    return {
        "course_id": str(course.id),
        "course_title": course.title,
        "kind": course.kind,
        "until": course.focus_until.isoformat(),
    }


def set_focus(
    db: Session, user: User, course_id: Any, until: date | None, request_id: str, *, origin: str
) -> dict[str, Any] | None:
    """Make one course or interest come first until ``until`` (inclusive, default today), or end the focus when
    ``course_id`` is None. At most one focus exists; setting a new one ends the old one. Audited."""
    today = user_today(user)
    before = focus_view(db, user)
    course = None
    if course_id is not None:
        course = owned(db, Course, course_id, user.id, for_update=True)
        if course.status != "active":
            raise ApiError(422, "course_not_active", f"{course.title} is archived; restore it before focusing on it.")
        until = until or today
        if until < today:
            raise ApiError(422, "focus_in_past", "The focus must last until today or a later day.")
        if until > today + timedelta(days=MAX_FOCUS_DAYS):
            raise ApiError(
                422, "focus_too_long", f"A focus can last at most {MAX_FOCUS_DAYS} days; set it again later."
            )
    for other in db.scalars(
        select(Course).where(Course.user_id == user.id, Course.focus_until.is_not(None)).with_for_update()
    ):
        if course is None or other.id != course.id:
            other.focus_until = None
            other.revision += 1
    if course is not None:
        course.focus_until = until
        course.revision += 1
    db.flush()
    after = focus_view(db, user)
    audit(
        db,
        actor_id=user.id,
        action="study.focus_changed",
        target_type="course" if course is not None else None,
        target_id=course.id if course is not None else None,
        details={"from": before, "to": after, "origin": origin},
        request_id=request_id,
    )
    return after


def set_goal(db: Session, user: User, course_id: Any, goal: str, request_id: str) -> Course:
    """The learner's goal for an interest (kept as its description, in their own words). Audited."""
    course = owned(db, Course, course_id, user.id, for_update=True)
    if course.kind != "interest":
        raise ApiError(
            422,
            "not_an_interest",
            f"{course.title} is a university course; it is planned by its exams (set_study_target), not by a goal.",
        )
    old = course.description
    course.description = goal.strip()
    course.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="course.goal_changed",
        target_type="course",
        target_id=course.id,
        details={"from": old, "to": course.description, "origin": "connector"},
        request_id=request_id,
    )
    return course
