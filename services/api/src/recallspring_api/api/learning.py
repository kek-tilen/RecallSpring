"""The learner's summary at the end of a learning chunk, written in the web app.

Assistants that cannot show RecallSpring's summary form inside the chat (e.g. Codex) send the learner here with a
link; the summary is saved exactly as typed, the same way as from the form (services/learning.save_summary).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import WriteCtx, commit_with_response, replay_if_seen, write_ctx
from ..models import Course
from ..schemas import LearningSummaryIn
from ..services.learning import save_summary
from ..services.ownership import owned

router = APIRouter(tags=["learning"])


@router.post("/learning", status_code=201)
def save_learning_summary(
    payload: LearningSummaryIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Store the learner's own summary as a note and mark the concepts studied (owner session + CSRF)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, payload.course_id, ctx.user.id)
    body = save_summary(
        db,
        ctx.user,
        course_id=payload.course_id,
        concept_ids=payload.concept_ids,
        title=payload.title,
        text=payload.text,
        client_request_id=payload.client_request_id,
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 201, body)
