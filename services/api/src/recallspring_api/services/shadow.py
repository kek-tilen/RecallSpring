"""FSRS-6 in shadow, stored (ADR-014 §5): ``review_shadow`` is rebuilt whenever a concept's review state is replayed.

Derived and never edited: the rows of a concept are deleted and written again from its evidence. The shadow never
changes what the learner sees: a failure here is logged (no learner data) and the review state is saved as usual.
Excluded from the shadow, as from mastery: provisional, low-confidence, ungraded and self-assessed grades, and
Check first answers (a green Check first result is a first review). No model calls.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..learning import fsrs_shadow
from ..learning.fsrs_shadow import ShadowExam, ShadowReview
from ..learning.scheduler import Deferral, Evidence, KnownFromCheck, exam_target
from ..models import Concept, ReviewShadow, User

log = logging.getLogger("recallspring.shadow")

# attempt id -> (evaluator kind of the effective assessment, Bloom level of the question)
Details = dict[uuid.UUID, tuple[str | None, int | None]]


def exams_for(db: Session, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ShadowExam]]:
    """Every study target (past or upcoming, not cancelled or deleted) whose scope holds each concept: the report
    looks back at exams that have passed."""
    from .targets import live_targets, scope_concepts  # targets reaches the review service through the planner

    out: dict[uuid.UUID, list[ShadowExam]] = {cid: [] for cid in concept_ids}
    if not concept_ids:
        return out
    course_of = dict(db.execute(select(Concept.id, Concept.course_id).where(Concept.id.in_(concept_ids))).all())
    for course_id in sorted(set(course_of.values()), key=str):
        for target in live_targets(db, course_id):
            if target.status == "cancelled":
                continue
            scope = scope_concepts(db, target)
            exam = ShadowExam(target.id, target.due_date, exam_target(target.goal, target.exam_retention))
            for concept_id, course in course_of.items():
                if course == course_id and concept_id in scope:
                    out[concept_id].append(exam)
    return out


def reviews_from(
    events: list[Evidence | KnownFromCheck | Deferral], details: Details, tz: ZoneInfo
) -> list[ShadowReview]:
    candidates: list[tuple[datetime, str, ShadowReview]] = []
    for ev in events:
        if isinstance(ev, Evidence):
            kind, bloom = details.get(ev.attempt_id, (None, None))
            if not ev.certain or kind == "self":
                continue
            review = ShadowReview(
                local_date=ev.occurred_at.astimezone(tz).date(),
                source="answer",
                attempt_id=ev.attempt_id,
                grade=ev.grade,
                bloom_level=bloom,
                evaluator_kind=kind,
                confidence=ev.confidence,
            )
            candidates.append((ev.occurred_at, str(ev.attempt_id), review))
        elif isinstance(ev, KnownFromCheck):
            review = ShadowReview(local_date=ev.occurred_at.astimezone(tz).date(), source="check_first")
            candidates.append((ev.occurred_at, str(ev.quiz_id), review))
    return fsrs_shadow.first_per_day(candidates)


def rebuild(
    db: Session,
    user: User,
    concept_id: uuid.UUID,
    events: list[Evidence | KnownFromCheck | Deferral],
    details: Details,
    exams: list[ShadowExam],
    now: datetime,
) -> None:
    """Replace the concept's shadow rows; any error leaves the review state untouched."""
    try:
        with db.begin_nested():
            _rebuild(db, user, concept_id, events, details, exams, now)
    except Exception as exc:  # the shadow must never stop an answer or a grade from being saved
        log.warning("review shadow not rebuilt for one concept (%s)", type(exc).__name__)


def _rebuild(
    db: Session,
    user: User,
    concept_id: uuid.UUID,
    events: list[Evidence | KnownFromCheck | Deferral],
    details: Details,
    exams: list[ShadowExam],
    now: datetime,
) -> None:
    db.execute(delete(ReviewShadow).where(ReviewShadow.user_id == user.id, ReviewShadow.concept_id == concept_id))
    reviews = reviews_from(events, details, ZoneInfo(user.timezone))
    for variant in fsrs_shadow.VARIANTS:
        for row in fsrs_shadow.run(concept_id, reviews, exams, variant):
            db.add(
                ReviewShadow(
                    user_id=user.id,
                    concept_id=concept_id,
                    variant=variant,
                    seq=row.seq,
                    source=row.review.source,
                    attempt_id=row.review.attempt_id,
                    local_date=row.review.local_date,
                    grade=row.review.grade,
                    rating=row.rating,
                    bloom_level=row.review.bloom_level,
                    evaluator_kind=row.review.evaluator_kind,
                    confidence=row.review.confidence,
                    elapsed_days=row.elapsed_days,
                    r_before=row.r_before,
                    s_before=row.s_before,
                    d_before=row.d_before,
                    s_after=row.s_after,
                    d_after=row.d_after,
                    fsrs_due=row.fsrs_due,
                    capped_due=row.capped_due,
                    target_id=row.exam.target_id if row.exam else None,
                    exam_date=row.exam.day if row.exam else None,
                    exam_target=row.exam.target if row.exam else None,
                    exam_r=row.exam_r,
                    library_version=fsrs_shadow.LIBRARY_VERSION,
                    params_hash=fsrs_shadow.PARAMS_HASH,
                    computed_at=now,
                )
            )
    db.flush()
