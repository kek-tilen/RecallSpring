"""Request context: authentication, CSRF and idempotency for every API route."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .errors import ApiError, request_id_var
from .models import AuthSession, IdempotencyRecord, User
from .security import CSRF_HEADER, SESSION_COOKIE, constant_time_equal, find_active_session, sha256_hex


@dataclass
class Ctx:
    user: User
    session: AuthSession
    request_id: str


@dataclass
class WriteCtx(Ctx):
    idempotency_key: uuid.UUID
    method: str
    path: str


def current_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    token = request.cookies.get(SESSION_COOKIE)
    session = find_active_session(db, token) if token else None
    if session is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    user = db.get(User, session.user_id)
    if user is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    return Ctx(user=user, session=session, request_id=request_id_var.get())


def csrf_ctx(
    ctx: Ctx = Depends(current_ctx),
    csrf_token: str | None = Header(default=None, alias=CSRF_HEADER),
) -> Ctx:
    if not csrf_token or not constant_time_equal(sha256_hex(csrf_token), ctx.session.csrf_hash):
        raise ApiError(403, "csrf_failed", "The request could not be verified. Reload the page and retry.")
    return ctx


def write_ctx(
    request: Request,
    ctx: Ctx = Depends(csrf_ctx),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> WriteCtx:
    if not idempotency_key:
        raise ApiError(400, "idempotency_key_required", "Write requests need an Idempotency-Key header (UUID).")
    try:
        key = uuid.UUID(idempotency_key)
    except ValueError as exc:
        raise ApiError(400, "idempotency_key_invalid", "Idempotency-Key must be a UUID.") from exc
    return WriteCtx(
        user=ctx.user,
        session=ctx.session,
        request_id=ctx.request_id,
        idempotency_key=key,
        method=request.method,
        path=request.url.path,
    )


def request_hash(payload: BaseModel | dict[str, Any] | None) -> str:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else (payload or {})
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stored(db: Session, ctx: WriteCtx) -> IdempotencyRecord | None:
    return db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == ctx.user.id, IdempotencyRecord.key == ctx.idempotency_key
        )
    )


def _replay_response(record: IdempotencyRecord, ctx: WriteCtx, req_hash: str) -> JSONResponse:
    if record.method != ctx.method or record.path != ctx.path or record.request_hash != req_hash:
        raise ApiError(422, "idempotency_key_reused", "This Idempotency-Key was already used for a different request.")
    return JSONResponse(record.response_body, status_code=record.response_status, headers={"Idempotent-Replay": "true"})


def replay_if_seen(db: Session, ctx: WriteCtx, payload: BaseModel | dict[str, Any] | None) -> JSONResponse | None:
    record = _stored(db, ctx)
    return _replay_response(record, ctx, request_hash(payload)) if record else None


def commit_with_response(
    db: Session, ctx: WriteCtx, payload: BaseModel | dict[str, Any] | None, status: int, body: Any
) -> JSONResponse:
    """Store the response under the idempotency key and commit it together with the write."""
    req_hash = request_hash(payload)
    db.add(
        IdempotencyRecord(
            user_id=ctx.user.id,
            key=ctx.idempotency_key,
            method=ctx.method,
            path=ctx.path,
            request_hash=req_hash,
            response_status=status,
            response_body=body,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request with the same key won the race: return its stored outcome.
        db.rollback()
        record = _stored(db, ctx)
        if record is None:
            raise
        return _replay_response(record, ctx, req_hash)
    return JSONResponse(body, status_code=status)
