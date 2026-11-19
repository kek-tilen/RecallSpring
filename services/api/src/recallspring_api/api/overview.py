"""Read-only overview for the web app: everything RecallSpring stores, owner session only.

Connector tokens never reach these routes (they only authenticate ``/api/v1/connector/*``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, current_ctx
from ..errors import not_found
from ..models import Concept, Course, Quiz
from ..services import overview
from ..services.ownership import owned
from ..services.planner import today_plan
from ..services.quizzes import form_view, results_view

router = APIRouter(tags=["overview"])


def _quiz(db: Session, quiz_id: uuid.UUID, user_id: uuid.UUID) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == user_id))
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
