"""Reviewing in the app and grading in one go (UI direction, 2026-11-27). Read-only; no model call, no migration.

* ``questions_for_review``: for each concept of a course that is due now, one open question the learner can answer
  from memory in the app. It reuses a question already linked to the concept (the one answered least recently, a
  never-answered one first); RecallSpring does not write questions itself. Concepts without an open question are
  listed apart, so the learner can review them with an assistant instead.
* ``waiting_answers``: saved answers that still wait for a grade, oldest first, so an assistant can grade them in one
  go (get_attempt, then record_assessment or record_assessments). An answer the learner self-assessed is included
  with that grade: it is provisional until an assistant checks it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Assessment, Attempt, Concept, Course, Question, QuestionConcept, User
from .reviews import review_queue

WAITING = ("saved_awaiting_evaluation", "evaluating")


def questions_for_review(db: Session, user: User, course: Course, now: datetime) -> dict[str, Any]:
    due = [concept for _, concept in review_queue(db, user, now, 0) if concept.course_id == course.id]
    items: list[dict[str, Any]] = []
    without: list[dict[str, Any]] = []
    for concept in due:
        question = _least_recent_question(db, user, concept)
        if question is None:
            without.append({"concept_id": str(concept.id), "term": concept.term})
            continue
        items.append(
            {
                "concept_id": str(concept.id),
                "term": concept.term,
                "question_id": str(question.id),
                "bloom_level": question.bloom_level,
            }
        )
    return {"course_id": str(course.id), "items": items, "without_question": without}


def _least_recent_question(db: Session, user: User, concept: Concept) -> Question | None:
    last = (
        select(Attempt.question_id, func.max(Attempt.submitted_at).label("at"))
        .where(Attempt.user_id == user.id)
        .group_by(Attempt.question_id)
        .subquery()
    )
    row = db.execute(
        select(Question)
        .join(QuestionConcept, QuestionConcept.question_id == Question.id)
        .outerjoin(last, last.c.question_id == Question.id)
        .where(
            QuestionConcept.concept_id == concept.id,
            Question.user_id == user.id,
            Question.question_type == "open",
        )
        .order_by(last.c.at.asc().nulls_first(), Question.created_at.desc())
        .limit(1)
    ).first()
    return row[0] if row else None


def waiting_answers(db: Session, user: User, course_id: uuid.UUID | None = None, limit: int = 50) -> dict[str, Any]:
    base = (
        select(Attempt, Question, Course)
        .join(Question, Question.id == Attempt.question_id)
        .join(Course, Course.id == Question.course_id)
        .where(Attempt.user_id == user.id, Attempt.status.in_(WAITING), Course.deleted_at.is_(None))
    )
    if course_id is not None:
        base = base.where(Course.id == course_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Attempt.submitted_at).limit(limit)).all()
    self_grades = _self_grades(db, [a.id for a, _, _ in rows])
    items = [
        {
            "attempt_id": str(attempt.id),
            "question_id": str(question.id),
            "course_id": str(course.id),
            "course_title": course.title,
            "quiz_id": str(attempt.quiz_id) if attempt.quiz_id else None,
            "prompt": question.prompt[:300],
            "unsure": attempt.guessing,
            "submitted_at": attempt.submitted_at.isoformat(),
            "self_grade": self_grades.get(attempt.id),
        }
        for attempt, question, course in rows
    ]
    return {"items": items, "total": total}


def _self_grades(db: Session, attempt_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not attempt_ids:
        return {}
    rows = db.execute(
        select(Assessment.attempt_id, Assessment.grade).where(
            Assessment.attempt_id.in_(attempt_ids), Assessment.evaluator_kind == "self"
        )
    ).all()
    return {attempt_id: grade for attempt_id, grade in rows if grade is not None}
