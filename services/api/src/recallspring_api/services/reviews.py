"""Persisted review state: recomputed from immutable evidence whenever evidence or deferrals change."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..learning.scheduler import (
    OVERLAY_CODES,
    Deferral,
    Evidence,
    ExamDate,
    KnownFromCheck,
    ReviewSchedule,
    exam_target,
    local_day_start,
    schedule,
)
from ..models import (
    Assessment,
    Attempt,
    Concept,
    Question,
    QuestionConcept,
    Quiz,
    ReviewDeferral,
    ReviewState,
    User,
)
from . import shadow


def effective_assessment(assessments: list[Assessment]) -> Assessment | None:
    """A learner correction (human) wins over any AI/deterministic evaluation; otherwise the latest one. A
    self-assessment counts only until any other grade exists (an assistant's check replaces it)."""
    if not assessments:
        return None
    humans = [a for a in assessments if a.evaluator_kind == "human"]
    checked = [a for a in assessments if a.evaluator_kind != "self"]
    pool = humans or checked or assessments
    return max(pool, key=lambda a: (a.created_at, str(a.id)))


def concept_ids_for_question(db: Session, question_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == question_id)))


def _evidence_for_concept(
    db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, details: shadow.Details | None = None
) -> list[Evidence | KnownFromCheck | Deferral]:
    """The concept's evidence and deferrals. ``details`` (for the FSRS-6 shadow) gets each graded attempt's
    evaluator kind and Bloom level."""
    rows = db.execute(
        select(Attempt, Assessment, Question.bloom_level)
        .join(QuestionConcept, QuestionConcept.question_id == Attempt.question_id)
        .join(Question, Question.id == Attempt.question_id)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(QuestionConcept.concept_id == concept_id, Attempt.user_id == user_id)
        # Diagnostic pre-tests show what is already known; they never drive the review schedule (ADR-006).
        .where(or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"))
    ).all()
    by_attempt: dict[uuid.UUID, tuple[Attempt, list[Assessment], int | None]] = {}
    grouped: dict[uuid.UUID, list[Assessment]] = defaultdict(list)
    for attempt, assessment, bloom_level in rows:
        by_attempt[attempt.id] = (attempt, grouped[attempt.id], bloom_level)
        grouped[attempt.id].append(assessment)
    events: list[Evidence | KnownFromCheck | Deferral] = []
    for attempt, assessments, bloom_level in by_attempt.values():
        eff = effective_assessment(assessments)
        if eff is not None:
            events.append(Evidence(attempt.submitted_at, attempt.id, eff.grade, eff.status, eff.confidence))  # type: ignore[arg-type]
            if details is not None:
                details[attempt.id] = (eff.evaluator_kind, bloom_level)
    deferrals = db.scalars(
        select(ReviewDeferral).where(ReviewDeferral.user_id == user_id, ReviewDeferral.concept_id == concept_id)
    )
    events.extend(Deferral(d.deferred_at, d.until) for d in deferrals)
    from . import check_first  # imports this module

    if (check := check_first.results(db, user_id, [concept_id]).get(concept_id)) and check["result"] == "green":
        # Shown in Check first: rare reviews only (scheduler v2); diagnostic answers stay out of the evidence.
        events.append(KnownFromCheck(datetime.fromisoformat(check["checked_at"]), uuid.UUID(check["quiz_id"])))
    return events


def exam_dates(db: Session, concept_ids: list[uuid.UUID], today: date) -> dict[uuid.UUID, list[ExamDate]]:
    """Upcoming exams (status upcoming, today or later) whose scope holds each concept (ADR-014 exam layer)."""
    from .targets import live_targets, scope_concepts  # targets reaches this module through the planner

    out: dict[uuid.UUID, list[ExamDate]] = {cid: [] for cid in concept_ids}
    if not concept_ids:
        return out
    course_of = dict(db.execute(select(Concept.id, Concept.course_id).where(Concept.id.in_(concept_ids))).all())
    for course_id in sorted(set(course_of.values()), key=str):
        for target in live_targets(db, course_id):
            if target.status != "upcoming" or target.due_date < today:
                continue
            scope = scope_concepts(db, target)
            exam = ExamDate(target.name, target.due_date, target.goal, exam_target(target.goal, target.exam_retention))
            for concept_id, course in course_of.items():
                if course == course_id and concept_id in scope:
                    out[concept_id].append(exam)
    return out


def recompute(
    db: Session, user: User, concept_ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, ReviewSchedule | None]:
    tz = ZoneInfo(user.timezone)
    results: dict[uuid.UUID, ReviewSchedule | None] = {}
    db.flush()
    exams = exam_dates(db, concept_ids, now.astimezone(tz).date())
    shadow_exams = shadow.exams_for(db, concept_ids)
    for concept_id in concept_ids:
        details: shadow.Details = {}
        events = _evidence_for_concept(db, user.id, concept_id, details)
        schedule_ = schedule(events, tz, exams[concept_id])
        row = db.get(ReviewState, (user.id, concept_id))
        if schedule_ is None:
            if row is not None:
                db.delete(row)
        else:
            values = dict(
                step=schedule_.step,
                due_at=schedule_.due_at,
                last_review_at=schedule_.last_review_at,
                consecutive_successes=schedule_.consecutive_successes,
                lapse_count=schedule_.lapse_count,
                evidence_count=schedule_.evidence_count,
                policy_version=schedule_.policy_version,
                due_reason=schedule_.reason.as_dict(),
                recomputed_at=now,
            )
            if row is None:
                db.add(ReviewState(user_id=user.id, concept_id=concept_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        # FSRS-6 in shadow (ADR-014 §5): stored beside the ladder, never shown and never used for dates.
        shadow.rebuild(db, user, concept_id, events, details, shadow_exams[concept_id], now)
        results[concept_id] = schedule_
    return results


def recompute_course(db: Session, user: User, course_id: uuid.UUID, now: datetime) -> None:
    """After a study target changed (date, goal, status, scope, deleted or restored): the exam layer of every
    concept of the course with a review state follows."""
    db.flush()
    concept_ids = list(
        db.scalars(
            select(ReviewState.concept_id)
            .join(Concept, Concept.id == ReviewState.concept_id)
            .where(ReviewState.user_id == user.id, Concept.course_id == course_id)
            .order_by(ReviewState.concept_id)
        )
    )
    if concept_ids:
        recompute(db, user, concept_ids, now)


def refresh_exam_overlays(db: Session, user: User, now: datetime) -> None:
    """A date the exam layer brought forward stops counting once its exam has passed: recompute those states so the
    ladder's own date (or the next exam) applies. Called before due reviews are read; deterministic, no model."""
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    stale = list(
        db.scalars(
            select(ReviewState.concept_id)
            .where(
                ReviewState.user_id == user.id,
                ReviewState.due_reason["code"].astext.in_(OVERLAY_CODES),
                ReviewState.due_reason["exam_date"].astext < today.isoformat(),
            )
            .order_by(ReviewState.concept_id)
        )
    )
    if stale:
        recompute(db, user, stale, now)


def review_queue(db: Session, user: User, now: datetime, horizon_days: int) -> list[tuple[ReviewState, Concept]]:
    tz = ZoneInfo(user.timezone)
    refresh_exam_overlays(db, user, now)
    # horizon 0: due right now; horizon N: everything due before the end of the N-th local day from today.
    window = (
        ReviewState.due_at <= now
        if horizon_days == 0
        else ReviewState.due_at < local_day_start(now, tz, horizon_days + 1)
    )
    rows = db.execute(
        select(ReviewState, Concept)
        .join(Concept, Concept.id == ReviewState.concept_id)
        .where(ReviewState.user_id == user.id, Concept.deleted_at.is_(None), window)
        .order_by(ReviewState.due_at, Concept.term)
    ).all()
    return [(state, concept) for state, concept in rows]
