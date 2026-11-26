"""Relearning before an exam (ADR-014 §2), worked out without a model call.

After a final, certain answer on a concept of an exam at most 7 days away, the grade response can carry ``relearn``:
on a weak answer (grade 0-2) the assistant gives feedback grounded in the material and asks again later in the
session with a varied question, until one Solid answer (two on the day before an exam-only exam), at most 4 tries
a day. The schedule brings a weak concept back the next day (the exam layer of ``rs-interval-v3``). Later answers on
the same day are evidence for the ladder as before; they are never presented as mastery.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..learning.scheduler import RELEARN_DAYS, day_label
from ..models import Assessment, Attempt, Concept, QuestionConcept, Quiz, User
from .reviews import concept_ids_for_question, effective_assessment, exam_dates

MAX_TRIES = 4


def _certain_grade(db: Session, attempt: Attempt) -> int | None:
    eff = effective_assessment(
        list(db.scalars(select(Assessment).where(Assessment.attempt_id == attempt.id).order_by(Assessment.created_at)))
    )
    if eff is None or eff.status != "final" or eff.grade is None or eff.confidence == "low":
        return None
    return eff.grade


def offer(db: Session, user: User, attempt: Attempt, now: datetime) -> dict[str, Any] | None:
    if attempt.quiz_id is not None:
        quiz = db.get(Quiz, attempt.quiz_id)
        if quiz is not None and quiz.mode == "diagnostic":
            return None  # Check first never drives reviews
    grade = _certain_grade(db, attempt)
    concept_ids = concept_ids_for_question(db, attempt.question_id)
    if grade is None or not concept_ids:
        return None
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    exams = exam_dates(db, concept_ids, today)
    ahead = sorted({e for cid in concept_ids for e in exams[cid] if e.day > today}, key=lambda e: (e.day, e.name))
    if not ahead or (ahead[0].day - today).days > RELEARN_DAYS:
        return None
    exam = ahead[0]
    days_left = (exam.day - today).days
    eve = days_left == 1
    needed = 2 if eve and exam.goal == "exam_only" else 1

    day_start = datetime.combine(today, time(0, 0), tzinfo=tz)
    found = list(
        db.scalars(
            select(Attempt)
            .join(QuestionConcept, QuestionConcept.question_id == Attempt.question_id)
            .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
            .where(
                Attempt.user_id == user.id,
                Attempt.kind == "answer",
                QuestionConcept.concept_id.in_(concept_ids),
                or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"),
            )
            .order_by(Attempt.submitted_at, Attempt.id)
        )
    )
    rows = list({a.id: a for a in found}.values())  # an answer linked to several of the concepts counts once
    before = [g for a in rows if a.submitted_at < day_start and (g := _certain_grade(db, a)) is not None]
    today_grades = [g for a in rows if a.submitted_at >= day_start and (g := _certain_grade(db, a)) is not None]
    tries = len(today_grades)
    solid = sum(1 for g in today_grades if g >= 3)
    weak = (bool(before) and before[-1] <= 2) or any(g <= 2 for g in today_grades)
    if not weak:
        return None

    terms = sorted(c.term for c in db.scalars(select(Concept).where(Concept.id.in_(concept_ids))))
    names = ", ".join(terms)
    when = f"{exam.name} on {day_label(exam.day)}"
    if grade <= 2:
        if tries >= MAX_TRIES:
            say = f"{tries} tries today on {names}: enough for today. Give feedback on the gaps from the material; " + (
                "the exam is tomorrow, so go over that feedback once more instead of another question."
                if eve
                else "RecallSpring brings it back tomorrow."
            )
        else:
            say = (
                f"{names} is not solid yet, {days_left} day{'s' if days_left != 1 else ''} before {when}. "
                "Give feedback on the gaps from the material (cite it), then ask about it again later in this "
                "session, after other questions, with a varied question (at Bloom 3 and above a new case, not the "
                "same prompt). Stop at "
                + ("two Solid answers today (the day before the exam)" if needed == 2 else "the first Solid answer")
                + f"; at most {MAX_TRIES} tries today ({tries} so far)."
            )
    elif solid < needed and tries < MAX_TRIES:
        say = (
            f"Solid. {exam.name} is tomorrow and {names} was weak: ask once more later in this session with a varied "
            "question; two Solid answers today are enough."
        )
    else:
        return None
    return {
        "concept_ids": [str(c) for c in sorted(concept_ids, key=str)],
        "terms": terms,
        "exam": exam.name,
        "exam_date": exam.day.isoformat(),
        "days_left": days_left,
        "tries_today": tries,
        "max_tries": MAX_TRIES,
        "solid_needed": needed,
        "solid_today": solid,
        "say": say,
    }
