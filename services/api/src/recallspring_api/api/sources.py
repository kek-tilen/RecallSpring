from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..ingest import jobs
from ..ingest.storage import StorageError, blob_path, check_text_encoding, sanitize_filename, sniff, spool, spool_bytes
from ..models import Course, Source, SourceSection
from ..schemas import SearchHitOut, SearchOut, SectionOut, SectionPageOut, SourceOut, SourceTextIn
from ..services import sources as svc
from ..services.events import learning_event
from ..services.ownership import owned

router = APIRouter(tags=["sources"])

MULTIPART_OVERHEAD = 64 * 1024


@router.post("/sources", status_code=201, response_model=SourceOut)
def upload_source(
    request: Request,
    course_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    ctx: WriteCtx = Depends(write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Multipart upload of a PDF, Markdown or text file. Extraction runs in the worker; poll GET /sources/{id}.

    In production the reverse proxy must also cap the request body (client_max_body_size)."""
    return handle_upload(request, course_id, file, ctx, db)


def handle_upload(request: Request, course_id: uuid.UUID, file: UploadFile, ctx: WriteCtx, db: Session) -> JSONResponse:
    """Shared by the web app and the connector (local file import)."""
    settings = get_settings()
    declared = int(request.headers.get("content-length") or 0)
    if declared > settings.max_upload_bytes + MULTIPART_OVERHEAD:
        raise svc.upload_error("file_too_large")
    owned(db, Course, course_id, ctx.user.id)
    filename = sanitize_filename(file.filename)
    try:
        tmp, sha256, size = spool(file.file, settings.max_upload_bytes)
    except StorageError as exc:
        raise svc.upload_error(exc.code) from exc
    try:
        with tmp.open("rb") as fh:
            kind, mime = sniff(fh.read(8), filename)
        if kind != "pdf":
            check_text_encoding(tmp)
    except StorageError as exc:
        tmp.unlink(missing_ok=True)
        raise svc.upload_error(exc.code) from exc
    fingerprint = {"course_id": str(course_id), "filename": filename, "sha256": sha256}
    if replay := replay_if_seen(db, ctx, fingerprint):
        tmp.unlink(missing_ok=True)
        return replay
    source = svc.create_source(
        db,
        user=ctx.user,
        course_id=course_id,
        tmp=tmp,
        sha256=sha256,
        size=size,
        filename=filename,
        kind=kind,
        mime=mime,
        origin="upload",
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, fingerprint, 201, svc.source_view(db, source))


@router.post("/sources/text", status_code=201, response_model=SourceOut)
def paste_source(
    payload: SourceTextIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    return handle_paste(payload, ctx, db)


def handle_paste(payload: SourceTextIn, ctx: WriteCtx, db: Session) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, payload.course_id, ctx.user.id)
    ext, kind, mime = (
        (".md", "markdown", "text/markdown") if payload.format == "markdown" else (".txt", "text", "text/plain")
    )
    filename = sanitize_filename(payload.title)
    if not filename.lower().endswith(ext):
        filename = f"{filename[: 255 - len(ext)]}{ext}"
    tmp, sha256, size = spool_bytes(payload.text.encode("utf-8"))
    source = svc.create_source(
        db,
        user=ctx.user,
        course_id=payload.course_id,
        tmp=tmp,
        sha256=sha256,
        size=size,
        filename=filename,
        kind=kind,
        mime=mime,
        origin="paste",
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 201, svc.source_view(db, source))


@router.get("/sources", response_model=list[SourceOut])
def list_sources(
    course_id: uuid.UUID | None = None, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    stmt = select(Source).where(Source.user_id == ctx.user.id, Source.deleted_at.is_(None))
    if course_id is not None:
        stmt = stmt.where(Source.course_id == course_id)
    return [svc.source_view(db, s) for s in db.scalars(stmt.order_by(Source.uploaded_at))]


@router.get("/sources/search", response_model=SearchOut)
def search(
    q: str = Query(min_length=1, max_length=200),
    course_id: uuid.UUID | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    ctx: Ctx = Depends(current_ctx),
    db: Session = Depends(get_db),
) -> SearchOut:
    rows = svc.search_sections(db, ctx.user.id, q, course_id, limit)
    return SearchOut(hits=[SearchHitOut(**dict(r)) for r in rows])


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.source_view(db, owned(db, Source, source_id, ctx.user.id))


@router.get("/sources/{source_id}/sections", response_model=SectionPageOut)
def list_sections(
    source_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
    db: Session = Depends(get_db),
) -> SectionPageOut:
    source = owned(db, Source, source_id, ctx.user.id)
    rows, total = svc.current_sections(db, source, offset, limit)
    return SectionPageOut(
        sections=[SectionOut.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/sources/{source_id}/file")
def download_original(
    source_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> FileResponse:
    """The unchanged original, always as an attachment and never sniffed or rendered inline."""
    source = owned(db, Source, source_id, ctx.user.id)
    path = blob_path(source.storage_key)
    if not path.is_file():
        raise ApiError(410, "original_missing", "The original file is no longer available.")
    return FileResponse(
        path,
        media_type=source.mime_type,
        filename=source.filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post("/sources/{source_id}/reprocess", status_code=202, response_model=SourceOut)
def reprocess(source_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Extract again (new parser version, transient failure). Earlier sections are kept for existing citations."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    source = owned(db, Source, source_id, ctx.user.id, for_update=True)
    if source.parse_state not in ("failed", "needs_attention", "ready"):
        raise ApiError(409, "extraction_in_progress", "Text extraction for this source is still running.")
    source.version += 1
    source.parse_state = "pending"
    source.parse_error = None
    source.parse_notes = []
    jobs.enqueue(
        db,
        user_id=ctx.user.id,
        type=jobs.EXTRACT_SOURCE,
        payload={"source_id": str(source.id), "version": source.version},
    )
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="source",
        entity_id=source.id,
        event_type="source.reprocess",
        payload={"version": source.version},
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, None, 202, svc.source_view(db, source))


@router.get("/sections/{section_id}", response_model=SectionOut)
def get_section(
    section_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    section = owned(db, SourceSection, section_id, ctx.user.id)
    source = db.get(Source, section.source_id)
    if source is None or source.deleted_at is not None:
        raise ApiError(404, "not_found", "Section not found.")
    return svc.section_view(section)
