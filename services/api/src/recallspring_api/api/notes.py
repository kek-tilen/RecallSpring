"""Learner notes with autosave revisions and conflict preservation (FR-03, T-10, T-19)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError, not_found
from ..models import Course, Note, NoteRevision, SyllabusItem
from ..schemas import NoteIn, NoteOut, NotePatch, NoteRevisionOut
from ..services.events import learning_event
from ..services.ownership import owned

router = APIRouter(tags=["notes"])


def note_view(note: Note) -> dict[str, Any]:
    return NoteOut(
        id=note.id,
        course_id=note.course_id,
        topic_id=note.syllabus_item_id,
        client_note_id=note.client_note_id,
        title=note.title,
        body=note.body,
        revision=note.revision,
        saved_at=note.saved_at,
        created_at=note.created_at,
    ).model_dump(mode="json")


def _snapshot(db: Session, note: Note) -> None:
    """Keep history without one row per keystroke: an editing burst updates its latest autosave snapshot."""
    window = timedelta(seconds=get_settings().note_snapshot_window_seconds)
    latest = db.scalar(
        select(NoteRevision)
        .where(NoteRevision.note_id == note.id, NoteRevision.kind == "autosave")
        .order_by(NoteRevision.saved_at.desc())
        .limit(1)
    )
    if latest is not None and latest.saved_at > note.saved_at - window and latest.revision > 1:
        latest.revision, latest.title, latest.body, latest.saved_at = (
            note.revision,
            note.title,
            note.body,
            note.saved_at,
        )
        return
    db.add(
        NoteRevision(
            user_id=note.user_id,
            note_id=note.id,
            kind="autosave",
            revision=note.revision,
            title=note.title,
            body=note.body,
            saved_at=note.saved_at,
        )
    )


def _existing(db: Session, ctx: WriteCtx, payload: NoteIn) -> JSONResponse:
    note = db.scalar(select(Note).where(Note.user_id == ctx.user.id, Note.client_note_id == payload.client_note_id))
    assert note is not None
    if note.course_id != payload.course_id:
        raise ApiError(409, "client_note_id_conflict", "This client_note_id belongs to another note.")
    return JSONResponse(note_view(note), status_code=200, headers={"Idempotent-Replay": "true"})


@router.post("/notes", status_code=201, response_model=NoteOut)
def create_note(payload: NoteIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if len(payload.body) > get_settings().max_note_chars:
        raise ApiError(422, "note_too_long", "The note is too long to save.")
    if db.scalar(select(Note.id).where(Note.user_id == ctx.user.id, Note.client_note_id == payload.client_note_id)):
        return _existing(db, ctx, payload)
    owned(db, Course, payload.course_id, ctx.user.id)
    if payload.topic_id is not None:
        topic = db.get(SyllabusItem, payload.topic_id)
        if topic is None or topic.user_id != ctx.user.id or topic.course_id != payload.course_id:
            raise not_found("Topic")
    now = clock.now()
    note = Note(
        user_id=ctx.user.id,
        course_id=payload.course_id,
        syllabus_item_id=payload.topic_id,
        client_note_id=payload.client_note_id,
        title=payload.title,
        body=payload.body,
        revision=1,
        saved_at=now,
        created_at=now,
    )
    db.add(note)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _existing(db, ctx, payload)
    _snapshot(db, note)
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="note",
        entity_id=note.id,
        event_type="note.created",
        payload={"revision": 1},
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 201, note_view(note))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: uuid.UUID, payload: NotePatch, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Autosave. ``base_revision`` must equal the stored revision; otherwise 409 and the rejected draft is kept
    as a ``conflict`` revision so neither version is lost before the learner resolves it."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if payload.title is None and payload.body is None:
        raise ApiError(422, "nothing_to_update", "Send a new title or body.")
    if payload.body is not None and len(payload.body) > get_settings().max_note_chars:
        raise ApiError(422, "note_too_long", "The note is too long to save.")
    note = owned(db, Note, note_id, ctx.user.id, for_update=True)
    now = clock.now()
    if payload.base_revision != note.revision:
        conflict = NoteRevision(
            user_id=ctx.user.id,
            note_id=note.id,
            kind="conflict",
            revision=note.revision,
            base_revision=payload.base_revision,
            title=payload.title or note.title,
            body=payload.body if payload.body is not None else note.body,
            saved_at=now,
        )
        db.add(conflict)
        db.flush()
        learning_event(
            db,
            user_id=ctx.user.id,
            entity_type="note",
            entity_id=note.id,
            event_type="note.conflict",
            payload={"base_revision": payload.base_revision, "current_revision": note.revision},
            request_id=ctx.request_id,
        )
        body = {
            "code": "revision_conflict",
            "message": "This note changed on another device. Both versions are kept; choose or merge them.",
            "request_id": ctx.request_id,
            "details": {"current": note_view(note), "conflict_revision_id": str(conflict.id)},
        }
        return commit_with_response(db, ctx, payload, 409, body)
    if payload.title is not None:
        note.title = payload.title
    if payload.body is not None:
        note.body = payload.body
    note.revision += 1
    note.saved_at = now
    db.flush()
    _snapshot(db, note)
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="note",
        entity_id=note.id,
        event_type="note.saved",
        payload={"revision": note.revision},
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 200, note_view(note))


@router.get("/notes", response_model=list[NoteOut])
def list_notes(
    course_id: uuid.UUID | None = None,
    topic_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(current_ctx),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Note).where(Note.user_id == ctx.user.id, Note.deleted_at.is_(None))
    if course_id is not None:
        stmt = stmt.where(Note.course_id == course_id)
    if topic_id is not None:
        stmt = stmt.where(Note.syllabus_item_id == topic_id)
    return [note_view(n) for n in db.scalars(stmt.order_by(Note.saved_at.desc()))]


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return note_view(owned(db, Note, note_id, ctx.user.id))


@router.get("/notes/{note_id}/revisions", response_model=list[NoteRevisionOut])
def list_revisions(note_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[Any]:
    owned(db, Note, note_id, ctx.user.id)
    rows = db.scalars(select(NoteRevision).where(NoteRevision.note_id == note_id).order_by(NoteRevision.saved_at))
    return [NoteRevisionOut.model_validate(r, from_attributes=True) for r in rows]
