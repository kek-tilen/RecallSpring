"""Pomodoro focus time (docs/06 → Focus). The timer runs in the browser; finished blocks are saved here."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..models import Course, FocusSession
from ..schemas import FocusSessionIn
from ..services import focus
from ..services.events import learning_event
from ..services.ownership import owned

router = APIRouter(tags=["focus"])

MAX_AGE = timedelta(days=7)  # a block saved later than this (e.g. queued while offline) is refused
CLOCK_SLACK = timedelta(minutes=2)


def _find(db: Session, ctx: WriteCtx, payload: FocusSessionIn) -> FocusSession | None:
    return db.scalar(
        select(FocusSession).where(
            FocusSession.user_id == ctx.user.id, FocusSession.client_session_id == payload.client_session_id
        )
    )


def _existing(db: Session, s: FocusSession) -> JSONResponse:
    title = db.scalar(select(Course.title).where(Course.id == s.course_id)) if s.course_id else None
    return JSONResponse(focus.session_view(s, title), status_code=200, headers={"Idempotent-Replay": "true"})


@router.post("/focus-sessions", status_code=201)
def save_focus_session(
    payload: FocusSessionIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Save one finished (or stopped) focus block. Retrying with the same ``client_session_id`` is safe."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if payload.started_at.tzinfo is None or payload.ended_at.tzinfo is None:
        raise ApiError(422, "time_zone_required", "Times need a time zone offset.")
    now = clock.now()
    span = (payload.ended_at - payload.started_at).total_seconds()
    if span < 0:
        raise ApiError(422, "ended_before_start", "The block ends before it starts.")
    if payload.ended_at > now + CLOCK_SLACK or payload.started_at < now - MAX_AGE:
        raise ApiError(422, "focus_time_out_of_range", "This focus block is in the future or more than 7 days old.")
    if payload.focused_seconds > span + 5:
        raise ApiError(422, "focus_longer_than_block", "Focused time is longer than the block itself.")
    if (found := _find(db, ctx, payload)) is not None:
        return _existing(db, found)
    title = owned(db, Course, payload.course_id, ctx.user.id).title if payload.course_id else None
    s = FocusSession(
        user_id=ctx.user.id,
        course_id=payload.course_id,
        client_session_id=payload.client_session_id,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        planned_minutes=payload.planned_minutes,
        focused_seconds=payload.focused_seconds,
        completed=payload.completed,
    )
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        found = _find(db, ctx, payload)
        if found is None:
            raise
        return _existing(db, found)
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="focus_session",
        entity_id=s.id,
        event_type="focus.completed" if s.completed else "focus.stopped",
        payload={
            "minutes": round(s.focused_seconds / 60),
            "planned_minutes": s.planned_minutes,
            "course_id": str(s.course_id) if s.course_id else None,
        },
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 201, focus.session_view(s, title))


@router.get("/focus/summary")
def focus_summary(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Focus time today, over the last seven days (by day and by course) and the latest blocks."""
    return focus.summary(db, ctx.user, clock.now())
