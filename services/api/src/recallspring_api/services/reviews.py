"""Persisted review state: recomputed from immutable evidence whenever evidence or deferrals change."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..learning.scheduler import Deferral, Evidence, ReviewSchedule, local_day_start, replay
from ..models import Assessment, Attempt, Concept, QuestionConcept, Quiz, ReviewDeferral, ReviewState, User


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


def _evidence_for_concept(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID) -> list[Evidence | Deferral]:
    rows = db.execute(
        select(Attempt, Assessment)
        .join(QuestionConcept, QuestionConcept.question_id == Attempt.question_id)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(QuestionConcept.concept_id == concept_id, Attempt.user_id == user_id)
        # Diagnostic pre-tests show what is already known; they never drive the review schedule (ADR-006).
        .where(or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"))
    ).all()
    by_attempt: dict[uuid.UUID, tuple[Attempt, list[Assessment]]] = {}
    grouped: dict[uuid.UUID, list[Assessment]] = defaultdict(list)
    for attempt, assessment in rows:
        by_attempt[attempt.id] = (attempt, grouped[attempt.id])
        grouped[attempt.id].append(assessment)
    events: list[Evidence | Deferral] = []
    for attempt, assessments in by_attempt.values():
        eff = effective_assessment(assessments)
        if eff is not None:
            events.append(Evidence(attempt.submitted_at, attempt.id, eff.grade, eff.status, eff.confidence))  # type: ignore[arg-type]
    deferrals = db.scalars(
        select(ReviewDeferral).where(ReviewDeferral.user_id == user_id, ReviewDeferral.concept_id == concept_id)
    )
    events.extend(Deferral(d.deferred_at, d.until) for d in deferrals)
    return events


def recompute(
    db: Session, user: User, concept_ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, ReviewSchedule | None]:
    tz = ZoneInfo(user.timezone)
    results: dict[uuid.UUID, ReviewSchedule | None] = {}
    db.flush()
    for concept_id in concept_ids:
        schedule = replay(_evidence_for_concept(db, user.id, concept_id), tz)
        row = db.get(ReviewState, (user.id, concept_id))
        if schedule is None:
            if row is not None:
                db.delete(row)
        else:
            values = dict(
                step=schedule.step,
                due_at=schedule.due_at,
                last_review_at=schedule.last_review_at,
                consecutive_successes=schedule.consecutive_successes,
                lapse_count=schedule.lapse_count,
                evidence_count=schedule.evidence_count,
                policy_version=schedule.policy_version,
                due_reason=schedule.reason.as_dict(),
                recomputed_at=now,
            )
            if row is None:
                db.add(ReviewState(user_id=user.id, concept_id=concept_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        results[concept_id] = schedule
    return results


def review_queue(db: Session, user: User, now: datetime, horizon_days: int) -> list[tuple[ReviewState, Concept]]:
    tz = ZoneInfo(user.timezone)
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
