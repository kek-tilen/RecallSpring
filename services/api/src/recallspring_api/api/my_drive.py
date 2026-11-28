"""Your cloud folder (BYOS step 2, 2026-11-27; Dropbox 2026-11-28): each learner's own readable copy of their
material in Google Drive or Dropbox (services/my_drive.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..cloud import CloudError
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, csrf_ctx, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..services import my_drive

router = APIRouter(tags=["drive"])

STATUS = {
    "not_configured": 409,
    "unreachable": 503,
    "refused": 502,
    "revoked": 409,
    "no_room": 507,
    "busy": 409,
    "bad_code": 422,
    "expired": 409,
}


def _error(exc: CloudError) -> ApiError:
    return ApiError(STATUS.get(exc.code, 503), f"drive_{exc.code}", exc.message)


class DriveOptionsIn(BaseModel):
    mirror: bool | None = None
    exports: bool | None = None


class DriveDisconnectIn(BaseModel):
    delete_files: bool = False


class DropboxCodeIn(BaseModel):
    code: str = Field(min_length=8, max_length=200)


@router.get("/drive")
def drive_view(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(my_drive.view(db, ctx.user), headers={"Cache-Control": "no-store"})


def _start(db: Session, ctx: Ctx, provider: str) -> JSONResponse:
    conn = my_drive.connection(db, ctx.user.id)
    if conn is not None and conn.state != "revoked":
        raise ApiError(409, "drive_connected", "Your cloud folder is connected already. Disconnect it first.")
    try:
        body = my_drive.start(ctx.user, provider)
    except CloudError as exc:
        raise _error(exc) from exc
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/drive/start")
def drive_start(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Google Drive: a code to type at google.com/device. The device code stays on the server; nothing is kept for
    replays."""
    return _start(db, ctx, "google")


@router.post("/drive/dropbox/start")
def drive_dropbox_start(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Dropbox: the page to open; Dropbox shows a code to paste back. The PKCE verifier stays on the server."""
    return _start(db, ctx, "dropbox")


@router.post("/drive/dropbox/finish")
def drive_dropbox_finish(
    payload: DropboxCodeIn, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The code Dropbox showed. Never stored or logged; on success the first copy starts in the background."""
    try:
        my_drive.finish_dropbox(db, ctx.user, payload.code, ctx.request_id)
    except CloudError as exc:
        raise _error(exc) from exc
    db.commit()
    my_drive.sync_in_background(ctx.user.id)
    return {"state": "connected", "drive": my_drive.view(db, ctx.user)}


@router.post("/drive/poll")
def drive_poll(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Whether the learner finished signing in at Google: pending, connected, denied or expired."""
    try:
        state = my_drive.poll(db, ctx.user, ctx.request_id)
    except CloudError as exc:
        raise _error(exc) from exc
    db.commit()
    if state == "connected":
        my_drive.sync_in_background(ctx.user.id)
    return {"state": state, "drive": my_drive.view(db, ctx.user)}


@router.post("/drive/cancel")
def drive_cancel(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    my_drive.cancel(ctx.user.id)
    return my_drive.view(db, ctx.user)


@router.post("/drive/settings")
def drive_settings(
    payload: DriveOptionsIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    conn = my_drive.set_options(db, ctx.user, mirror=payload.mirror, exports=payload.exports)
    db.flush()
    response = commit_with_response(db, ctx, payload, 200, my_drive.view(db, ctx.user))
    if conn.mirror:
        my_drive.sync_in_background(ctx.user.id)
    return response


@router.post("/drive/copy-existing")
def drive_copy_existing(ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Copy the material from before the connection too (the page shows the size first)."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    my_drive.copy_existing(db, ctx.user, ctx.request_id)
    db.flush()
    response = commit_with_response(db, ctx, None, 202, my_drive.view(db, ctx.user))
    my_drive.sync_in_background(ctx.user.id)
    return response


@router.post("/drive/disconnect")
def drive_disconnect(
    payload: DriveDisconnectIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Forget the sign-in and ask Google or Dropbox to withdraw it; the files there stay unless delete_files (the
    page asks once more). Audited as drive.disconnected."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    my_drive.disconnect(db, ctx.user, payload.delete_files, ctx.request_id)
    db.flush()
    return commit_with_response(db, ctx, payload, 200, my_drive.view(db, ctx.user))
