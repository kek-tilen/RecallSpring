"""The learner's own folders in the library and everything archived in one place (owner session only)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..schemas import ArchiveIn, FolderIn, FolderPatch
from ..services import folders as svc

router = APIRouter(tags=["library"])


def _view(db: Session, user_id: uuid.UUID, folder_id: uuid.UUID) -> dict[str, Any]:
    t = svc.tree(db, user_id)
    files = svc._file_counts(db, user_id).get(folder_id, 0)
    return svc.folder_view(t.by_id[folder_id], t, files)


@router.get("/folders")
def list_folders(
    course_id: uuid.UUID | None = None, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """All folders (or one course's), with their path, file count and archived state."""
    return svc.list_views(db, ctx.user, course_id)


@router.post("/folders", status_code=201)
def create_folder(payload: FolderIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    folder = svc.create(db, ctx.user, payload.course_id, payload.parent_id, payload.name, ctx.request_id)
    return commit_with_response(db, ctx, payload, 201, _view(db, ctx.user.id, folder.id))


@router.patch("/folders/{folder_id}")
def update_folder(
    folder_id: uuid.UUID, payload: FolderPatch, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Rename or move a folder within its course (``parent_id: null`` = top level)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    folder = svc.get(db, ctx.user.id, folder_id, lock=True)
    svc.update(
        db,
        ctx.user,
        folder,
        name=payload.name,
        move="parent_id" in payload.model_fields_set,
        parent_id=payload.parent_id,
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 200, _view(db, ctx.user.id, folder.id))


@router.post("/folders/{folder_id}/archive")
def archive_folder(
    folder_id: uuid.UUID, payload: ArchiveIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Archive (hide with everything in it) or restore a folder. Nothing is deleted. Audited."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    folder = svc.get(db, ctx.user.id, folder_id, lock=True)
    svc.set_archived(db, ctx.user, folder, payload.archived, ctx.request_id)
    return commit_with_response(db, ctx, payload, 200, _view(db, ctx.user.id, folder.id))


@router.delete("/folders/{folder_id}")
def remove_folder(
    folder_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Remove an empty folder (``409 folder_not_empty`` otherwise). Audited."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    folder = svc.get(db, ctx.user.id, folder_id, lock=True)
    svc.remove(db, ctx.user, folder, ctx.request_id)
    return commit_with_response(db, ctx, None, 200, {"removed": str(folder.id)})


@router.get("/library/archived")
def archived(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Archived semesters and other groups, courses, folders and files, newest first, each restorable."""
    return svc.archived_view(db, ctx.user)
