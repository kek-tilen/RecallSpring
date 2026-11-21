"""Moving material in (owner session + CSRF): a ChatGPT data export, and ZIPs of course material.

See services/chatgpt_import.py and services/bulk.py. Connector tokens cannot reach these routes: bringing a whole
export in is the learner's own step in the web app."""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..ingest.storage import StorageError, spool
from ..models import Course
from ..schemas import ChatImportSaveIn, MaterialCategory
from ..services import bulk
from ..services import chatgpt_import as svc
from ..services.ownership import owned

router = APIRouter(tags=["imports"])

MULTIPART_OVERHEAD = 64 * 1024


def _check_upload(request: Request, staging_factor: int) -> int:
    """Refuse an upload that is too large, or that would leave the disk too full once staged."""
    settings = get_settings()
    declared = int(request.headers.get("content-length") or 0)
    if declared > settings.max_import_bytes + MULTIPART_OVERHEAD:
        raise ApiError(
            413,
            "file_too_large",
            f"The upload is larger than {settings.max_import_bytes // 1024**2} MB (RS_MAX_IMPORT_BYTES).",
        )
    try:
        free = shutil.disk_usage(settings.storage_dir).free
    except OSError:  # pragma: no cover - storage_dir is created at start-up
        return declared
    if free - declared * staging_factor < settings.min_free_disk_bytes:
        raise ApiError(
            507,
            "storage_low",
            "The disk RecallSpring stores files on is too full to unpack this upload. Free some space, then try again.",
        )
    return declared


@router.post("/imports/chatgpt", status_code=201)
def stage_chatgpt_export(
    request: Request,
    file: UploadFile = File(...),
    ctx: WriteCtx = Depends(write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Upload a ChatGPT data export (ZIP). It is kept privately for a few days while the learner picks what to
    keep; nothing is added to the library yet."""
    declared = _check_upload(request, staging_factor=3)
    fingerprint = {"filename": file.filename, "declared": declared}
    if replay := replay_if_seen(db, ctx, fingerprint):
        return replay
    view = svc.stage(db, ctx.user, file.file, file.filename or "chatgpt-export.zip", ctx.request_id)
    return commit_with_response(db, ctx, fingerprint, 201, view)


@router.get("/imports/chatgpt")
def list_chatgpt_imports(ctx: Ctx = Depends(current_ctx)) -> list[dict[str, Any]]:
    return svc.list_imports(ctx.user)


@router.get("/imports/chatgpt/{import_id}")
def get_chatgpt_import(import_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> dict[str, Any]:
    return svc.get_view(ctx.user, import_id)


@router.get("/imports/chatgpt/{import_id}/chats/{key}")
def preview_chat(import_id: uuid.UUID, key: str, ctx: Ctx = Depends(current_ctx)) -> dict[str, Any]:
    """The conversation as it will be saved (plain text; the web app never renders it as HTML)."""
    return svc.preview(ctx.user, import_id, key)


@router.post("/imports/chatgpt/{import_id}/save")
def save_chats(
    import_id: uuid.UUID,
    payload: ChatImportSaveIn,
    ctx: WriteCtx = Depends(write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Save the chosen conversations word for word into one course (and folder), with their attached files."""
    if replay := replay_if_seen(db, ctx, {"import_id": str(import_id), **payload.model_dump(mode="json")}):
        return replay
    result, saved = svc.save(
        db,
        ctx.user,
        import_id,
        keys=payload.keys,
        course_id=payload.course_id,
        folder_id=payload.folder_id,
        folder=payload.folder,
        include_files=payload.include_files,
        request_id=ctx.request_id,
    )
    db.flush()
    body = {**bulk.result_view(db, ctx.user, result), "conversations": len(saved)}
    response = commit_with_response(
        db, ctx, {"import_id": str(import_id), **payload.model_dump(mode="json")}, 200, body
    )
    svc.mark_saved(ctx.user, import_id, saved)
    return response


@router.delete("/imports/chatgpt/{import_id}")
def discard_chatgpt_import(
    import_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Remove the uploaded export from RecallSpring. Conversations already saved stay in the library."""
    fingerprint = {"discard": str(import_id)}
    if replay := replay_if_seen(db, ctx, fingerprint):
        return replay
    svc.discard(db, ctx.user, import_id, ctx.request_id)
    return commit_with_response(db, ctx, fingerprint, 200, {"discarded": True})


@router.post("/sources/zip", status_code=201)
def import_zip(
    request: Request,
    course_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    category: MaterialCategory = Form("material"),
    folder_id: uuid.UUID | None = Form(None),
    ctx: WriteCtx = Depends(write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Every supported file in a ZIP, with its folders, into a course (below ``folder_id`` when given). Files
    that do not fit are listed as skipped; the rest is imported."""
    _check_upload(request, staging_factor=2)
    owned(db, Course, course_id, ctx.user.id)
    try:
        tmp, sha256, _size = spool(file.file, get_settings().max_import_bytes)
    except StorageError as exc:
        raise ApiError(413, "file_too_large", "The ZIP is too large (RS_MAX_IMPORT_BYTES).") from exc
    try:
        fingerprint = {
            "course_id": str(course_id),
            "sha256": sha256,
            "category": category,
            "folder_id": str(folder_id) if folder_id else None,
        }
        if replay := replay_if_seen(db, ctx, fingerprint):
            return replay
        result = bulk.import_zip(
            db, ctx.user, tmp, course_id=course_id, folder_id=folder_id, category=category, request_id=ctx.request_id
        )
        db.flush()
        return commit_with_response(db, ctx, fingerprint, 201, bulk.result_view(db, ctx.user, result))
    finally:
        tmp.unlink(missing_ok=True)
