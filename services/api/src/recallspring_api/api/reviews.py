from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..learning.scheduler import local_day_start
from ..models import Concept, Course, ReviewDeferral, ReviewState
from ..schemas import DeferIn, ReviewItemOut, ReviewQueueOut
from ..services.events import audit, learning_event
from ..services.ownership import owned
from ..services.review_now import questions_for_review, waiting_answers
from ..services.reviews import recompute, review_queue

router = APIRouter(tags=["reviews"])


def _item(state: ReviewState, concept: Concept, now) -> ReviewItemOut:  # type: ignore[no-untyped-def]
    return ReviewItemOut(
        concept_id=concept.id,
        course_id=concept.course_id,
        term=concept.term,
        due_at=state.due_at,
        is_due=state.due_at <= now,
        step=state.step,
        evidence_count=state.evidence_count,
        lapse_count=state.lapse_count,
        last_review_at=state.last_review_at,
        due_reason=state.due_reason,
        policy_version=state.policy_version,
    )


@router.get("/reviews/due", response_model=ReviewQueueOut)
def due_reviews(
    horizon_days: int = Query(default=0, ge=0, le=60, description="0 = due now; N = due within N local days"),
    ctx: Ctx = Depends(current_ctx),
    db: Session = Depends(get_db),
) -> ReviewQueueOut:
    now = clock.now()
    rows = review_queue(db, ctx.user, now, horizon_days)
    return ReviewQueueOut(items=[_item(s, c, now) for s, c in rows], generated_at=now)


@router.get("/reviews/questions")
def review_questions(
    course_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, object]:
    """Review now (2026-11-27): one open question per concept of the course that is due now, to answer from memory
    in the app; concepts without an open question are listed apart."""
    course = owned(db, Course, course_id, ctx.user.id)
    return questions_for_review(db, ctx.user, course, clock.now())


@router.get("/answers/waiting")
def answers_waiting(
    course_id: uuid.UUID | None = None, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, object]:
    """Saved answers that still wait for a grade, oldest first (Grade my answers in…, 2026-11-27)."""
    if course_id is not None:
        owned(db, Course, course_id, ctx.user.id)
    return waiting_answers(db, ctx.user, course_id)


@router.post("/reviews/{concept_id}/defer", response_model=ReviewItemOut)
def defer_review(
    concept_id: uuid.UUID, payload: DeferIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Explicit, audited deferral. Skipping is not deferring: skipped reviews stay due."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    concept = owned(db, Concept, concept_id, ctx.user.id)
    if db.get(ReviewState, (ctx.user.id, concept_id)) is None:
        raise ApiError(409, "not_scheduled", "This concept has no scheduled review yet.")
    now = clock.now()
    until = local_day_start(now, ZoneInfo(ctx.user.timezone), payload.days)
    db.add(
        ReviewDeferral(user_id=ctx.user.id, concept_id=concept_id, deferred_at=now, until=until, reason=payload.reason)
    )
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="concept",
        entity_id=concept_id,
        event_type="review.deferred",
        payload={"days": payload.days, "until": until.isoformat()},
        request_id=ctx.request_id,
    )
    audit(
        db,
        actor_id=ctx.user.id,
        action="review.defer",
        target_type="concept",
        target_id=concept_id,
        details={"days": payload.days},
        request_id=ctx.request_id,
    )
    recompute(db, ctx.user, [concept_id], now)
    db.flush()
    state = db.get(ReviewState, (ctx.user.id, concept_id))
    assert state is not None
    return commit_with_response(db, ctx, payload, 200, _item(state, concept, now).model_dump(mode="json"))
