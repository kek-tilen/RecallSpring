from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..models import Course, StudySession
from ..schemas import StudySessionIn, StudySessionOut
from ..services.ownership import owned

router = APIRouter(tags=["study"])


@router.post("/study-sessions", status_code=201, response_model=StudySessionOut)
def start_session(
    payload: StudySessionIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if payload.course_id is not None:
        owned(db, Course, payload.course_id, ctx.user.id)
    row = StudySession(user_id=ctx.user.id, course_id=payload.course_id, mode=payload.mode, started_at=clock.now())
    db.add(row)
    db.flush()
    return commit_with_response(db, ctx, payload, 201, StudySessionOut.model_validate(row).model_dump(mode="json"))


@router.get("/study-sessions/{session_id}", response_model=StudySessionOut)
def get_session(session_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> StudySession:
    return owned(db, StudySession, session_id, ctx.user.id)
