"""Concept-to-Clarity in the web app (ADR-010): read a concept's explanation, save a new version, delete (after
confirmation) or restore one. Feedback comes only from assistants (connector and Chat)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, csrf_ctx, current_ctx, replay_if_seen, write_ctx
from ..schemas import ExplanationVersionIn
from ..services import explanations as svc

router = APIRouter(tags=["explanations"])


@router.get("/concepts/{concept_id}/explanation")
def explanation(
    concept_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return svc.view(db, ctx.user, concept_id)


@router.post("/concepts/{concept_id}/explanation/versions", status_code=201)
def add_version(
    concept_id: uuid.UUID,
    payload: ExplanationVersionIn,
    ctx: WriteCtx = Depends(write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Save the learner's explanation exactly as a new version (or the exact text of an exam answer)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    body = svc.add_version(
        db,
        ctx.user,
        concept_id,
        text=payload.text,
        source=payload.source,
        client_request_id=payload.client_request_id,
        from_attempt_id=payload.from_attempt_id,
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 201, body)


@router.delete("/explanation-versions/{version_id}")
def delete_version(
    version_id: uuid.UUID, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Soft delete after the learner confirmed it; restorable for 30 days."""
    body = svc.set_deleted(db, ctx.user, version_id, True, ctx.request_id)
    db.commit()
    return body


@router.post("/explanation-versions/{version_id}/restore")
def restore_version(
    version_id: uuid.UUID, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    body = svc.set_deleted(db, ctx.user, version_id, False, ctx.request_id)
    db.commit()
    return body
