"""Read-only overview for the web app: everything RecallSpring stores, owner session only.

Connector tokens never reach these routes (they only authenticate ``/api/v1/connector/*``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import not_found
from ..models import Concept, Course, Quiz
from ..schemas import QuizDraftIn, QuizSubmitIn
from ..services import calendar, overview
from ..services import quizzes as quiz_svc
from ..services.ownership import owned
from ..services.planner import today_plan
from ..services.quizzes import form_view, results_view

router = APIRouter(tags=["overview"])


def _quiz(db: Session, quiz_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> Quiz:
    stmt = select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == user_id)
    quiz = db.scalar(stmt.with_for_update() if lock else stmt)
    if quiz is None:
        raise not_found("Simulation")
    return quiz


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "plan": today_plan(db, ctx.user, clock.now(), None, None),
        "attention": overview.attention(db, ctx.user),
        "counts": overview.counts(db, ctx.user),
        "recent": overview.history(db, ctx.user, 12),
    }


@router.get("/overview/courses")
def courses_summary(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return overview.courses_summary(db, ctx.user)


@router.get("/courses/{course_id}/overview")
def course_overview(
    course_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return overview.course_overview(db, ctx.user, owned(db, Course, course_id, ctx.user.id))


@router.get("/concepts/{concept_id}/detail")
def concept_detail(
    concept_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return overview.concept_detail(db, ctx.user, owned(db, Concept, concept_id, ctx.user.id))


@router.get("/quizzes")
def list_quizzes(
    course_id: uuid.UUID | None = None, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    stmt = select(Quiz).where(Quiz.user_id == ctx.user.id).order_by(Quiz.created_at.desc())
    if course_id is not None:
        stmt = stmt.where(Quiz.course_id == course_id)
    return [overview.quiz_summary(db, q) for q in db.scalars(stmt)]


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Open simulations show questions only (no answer keys); submitted ones show answers, grades and keys."""
    quiz = _quiz(db, quiz_id, ctx.user.id)
    view = form_view(db, quiz) if quiz.status == "open" else results_view(db, quiz)
    return {"course_id": str(quiz.course_id), "created_at": quiz.created_at.isoformat(), **view}


@router.get("/attempts")
def list_attempts(
    course_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if course_id is not None:
        owned(db, Course, course_id, ctx.user.id)
    return overview.attempts_list(db, ctx.user, course_id, limit)


@router.get("/history")
def history(
    limit: int = Query(default=100, ge=1, le=500), ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return overview.history(db, ctx.user, limit)


# ---------------------------------------------------------------- answering a simulation in the web app


@router.post("/quizzes/{quiz_id}/open")
def open_quiz(quiz_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """The same form Claude opens: questions without answer keys; starts the clock on first open."""
    quiz = _quiz(db, quiz_id, ctx.user.id, lock=True)
    quiz_svc.mark_opened(quiz)
    db.flush()
    body = {"course_id": str(quiz.course_id), "created_at": quiz.created_at.isoformat(), **form_view(db, quiz)}
    db.commit()
    return JSONResponse(body)


@router.post("/quizzes/{quiz_id}/draft")
def save_quiz_draft(
    quiz_id: uuid.UUID, payload: QuizDraftIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    quiz = _quiz(db, quiz_id, ctx.user.id, lock=True)
    quiz_svc.save_draft(quiz, payload.answers)
    db.commit()
    return JSONResponse(
        {"saved_at": quiz.draft_saved_at.isoformat() if quiz.draft_saved_at else None, "revision": quiz.draft_revision}
    )


@router.post("/quizzes/{quiz_id}/submit")
def submit_quiz(
    quiz_id: uuid.UUID, payload: QuizSubmitIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Saves every answer exactly (captured in the web app), grades multiple-choice items from the key.
    Open answers wait for Claude: ask it to grade this simulation (the ID is shown to copy)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    quiz = _quiz(db, quiz_id, ctx.user.id, lock=True)
    quiz_svc.submit(
        db, ctx.user, quiz, payload.client_request_id, payload.answers, ctx.request_id, captured_via="app_ui"
    )
    db.flush()
    body = {"course_id": str(quiz.course_id), "created_at": quiz.created_at.isoformat(), **results_view(db, quiz)}
    return commit_with_response(db, ctx, payload, 200, body)


# ---------------------------------------------------------------- calendar export


@router.get("/calendar.ics")
def calendar_export(
    group_id: uuid.UUID | None = None, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> Response:
    """All upcoming exams and kolokviji as an iCalendar file (all-day events with a reminder the day before)."""
    body = calendar.exams_ics(db, ctx.user, group_id)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="recallspring-exams.ics"',
            "Cache-Control": "private, no-store",
        },
    )
