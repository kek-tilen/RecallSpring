"""Export (BYOS step 1): the learner's own material, notes and answers as plain files (services/exports.py)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..services import exports

router = APIRouter(tags=["export"])


class ExportIn(BaseModel):
    course_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    material: bool = True
    notes: bool = True
    answers: bool = True
    destination: Literal["download"] = "download"


@router.get("/exports")
def export_view(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return exports.view(db, ctx.user)


@router.post("/exports", status_code=202)
def make_export(payload: ExportIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    if replayed := replay_if_seen(db, ctx, payload):
        return replayed
    exports.create(
        db,
        ctx.user,
        course_ids=payload.course_ids,
        material=payload.material,
        notes=payload.notes,
        answers=payload.answers,
        destination=payload.destination,
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 202, exports.view(db, ctx.user))


@router.post("/exports/{export_id}/cancel")
def cancel_export(
    export_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replayed := replay_if_seen(db, ctx, None):
        return replayed
    exports.cancel(db, ctx.user, export_id)
    db.flush()
    return commit_with_response(db, ctx, None, 200, exports.view(db, ctx.user))


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> FileResponse:
    row = exports.owned(db, ctx.user, export_id)
    path = exports.mark_downloaded(db, ctx.user, row, ctx.request_id)
    name = exports.file_name(row)
    db.commit()
    return FileResponse(
        path,
        media_type="application/zip",
        filename=name,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
