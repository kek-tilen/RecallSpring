"""Deleting a whole course (soft, restorable for 30 days) after the learner typed its exact name.

Everything that belongs to the course is hidden with it: its material, folders, concepts, topics, notes, exams and
midterms, ChatGPT conversations and focus blocks get the course's ``deleted_at`` stamp; questions, answers,
grades, simulations and reviews follow the course (lists and lookups skip a deleted course, and its concepts leave
the review queue). Restoring clears exactly that stamp, so things the learner had deleted on their own before stay
deleted. Nothing is removed from the database or the backups; uploaded files stay in storage.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError, not_found
from ..models import (
    AiConversation,
    Attempt,
    Concept,
    Course,
    FocusSession,
    Note,
    Question,
    Quiz,
    Source,
    SourceFolder,
    StudyTarget,
    SyllabusItem,
    User,
)
from .courses import ensure_new_title
from .events import audit, learning_event

RESTORE_DAYS = 30

# Rows with their own deleted_at that are hidden together with the course.
CASCADE = (Source, SourceFolder, Concept, SyllabusItem, Note, StudyTarget, AiConversation, FocusSession)


def contents(db: Session, course: Course) -> dict[str, int]:
    """What deleting the course hides, as counts for the confirmation dialog."""

    def n(model: Any) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(model).where(model.course_id == course.id, model.deleted_at.is_(None))
            )
            or 0
        )

    answers = (
        db.scalar(
            select(func.count())
            .select_from(Attempt)
            .join(Question, Question.id == Attempt.question_id)
            .where(Question.course_id == course.id)
        )
        or 0
    )
    return {
        "materials": n(Source),
        "folders": n(SourceFolder),
        "concepts": n(Concept),
        "notes": n(Note),
        "exams": n(StudyTarget),
        "simulations": db.scalar(select(func.count()).select_from(Quiz).where(Quiz.course_id == course.id)) or 0,
        "questions": db.scalar(select(func.count()).select_from(Question).where(Question.course_id == course.id)) or 0,
        "answers": answers,
        "conversations": n(AiConversation),
        "focus_blocks": n(FocusSession),
    }


def delete_course(db: Session, user: User, course_id: uuid.UUID, confirm_title: str, request_id: str) -> Course:
    course = db.scalar(
        select(Course)
        .where(Course.id == course_id, Course.user_id == user.id, Course.deleted_at.is_(None))
        .with_for_update()
    )
    if course is None:
        raise not_found("Course")
    if confirm_title != course.title:
        raise ApiError(422, "confirm_title_mismatch", "Type the course name exactly as it is shown to delete it.")
    counts = contents(db, course)
    now = clock.now()
    course.deleted_at = now
    course.revision += 1
    for model in CASCADE:
        db.execute(
            update(model)
            .where(model.course_id == course.id, model.deleted_at.is_(None))
            .values(deleted_at=now)
            .execution_options(synchronize_session=False)
        )
    db.flush()
    _record(db, user, course, "course.deleted", counts, request_id)
    return course


def deleted_courses(db: Session, user: User) -> list[Course]:
    since = clock.now() - timedelta(days=RESTORE_DAYS)
    return list(
        db.scalars(
            select(Course)
            .where(Course.user_id == user.id, Course.deleted_at.is_not(None), Course.deleted_at >= since)
            .order_by(Course.deleted_at.desc())
        )
    )


def restore_course(db: Session, user: User, course_id: uuid.UUID, request_id: str) -> Course:
    since = clock.now() - timedelta(days=RESTORE_DAYS)
    course = db.scalar(
        select(Course)
        .where(
            Course.id == course_id,
            Course.user_id == user.id,
            Course.deleted_at.is_not(None),
            Course.deleted_at >= since,
        )
        .with_for_update()
    )
    if course is None:
        raise not_found("Course")
    ensure_new_title(db, user.id, course.title)  # another course took the name meanwhile: 409, rename that one
    stamp: datetime = course.deleted_at  # type: ignore[assignment]
    course.deleted_at = None
    course.revision += 1
    for model in CASCADE:
        db.execute(
            update(model)
            .where(model.course_id == course.id, model.deleted_at == stamp)
            .values(deleted_at=None)
            .execution_options(synchronize_session=False)
        )
    db.flush()
    _record(db, user, course, "course.restored", contents(db, course), request_id)
    return course


def _record(db: Session, user: User, course: Course, action: str, counts: dict[str, int], request_id: str) -> None:
    audit(
        db,
        actor_id=user.id,
        action=action,
        target_type="course",
        target_id=course.id,
        details={"title": course.title, **counts},
        request_id=request_id,
    )
    learning_event(
        db,
        user_id=user.id,
        entity_type="course",
        entity_id=course.id,
        event_type=action,
        payload=counts,
        request_id=request_id,
    )
