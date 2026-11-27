from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import exists, select, text, update
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, csrf_ctx, current_ctx
from ..errors import ApiError
from ..models import AuthSession, User
from ..schemas import FirstRunIn, LoginIn, SessionOut, UserOut
from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    LoginRateLimiter,
    create_session,
    hash_password,
    verify_password,
)
from ..services import passkeys, timezones
from ..services.events import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    limiter: LoginRateLimiter = request.app.state.login_limiter
    client = request.client.host if request.client else "unknown"
    limit_key = f"{client}|{payload.username.casefold()}"
    if limiter.blocked(limit_key):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.")

    user = db.scalar(select(User).where(User.username == payload.username))
    if not verify_password(user.password_hash if user else None, payload.password):
        limiter.record_failure(limit_key)
        audit(db, actor_id=user.id if user else None, action="auth.login_failed")
        db.commit()
        raise ApiError(401, "invalid_credentials", "Username or password is incorrect.")
    assert user is not None

    limiter.reset(limit_key)
    return _signed_in(db, user)


def _signed_in(db: Session, user: User, status_code: int = 200, method: str = "password") -> JSONResponse:
    """Start a session for ``user`` (audited) and set its cookies."""
    settings = get_settings()
    token, csrf, session = create_session(db, user, settings.session_ttl_hours)
    audit(db, actor_id=user.id, action="auth.login", details={"method": method} if method != "password" else None)
    db.commit()

    body = SessionOut(user=UserOut.model_validate(user), expires_at=session.expires_at).model_dump(mode="json")
    response = JSONResponse(body, status_code=status_code)
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=settings.cookie_secure, samesite="strict", path="/"
    )
    return response


@router.post("/logout", status_code=204)
def logout(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> Response:
    session = db.merge(ctx.session)
    session.revoked_at = clock.now()
    audit(db, actor_id=ctx.user.id, action="auth.logout", request_id=ctx.request_id)
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@router.get("/session", response_model=SessionOut)
def session_info(ctx: Ctx = Depends(current_ctx)) -> SessionOut:
    return SessionOut(user=UserOut.model_validate(ctx.user), expires_at=ctx.session.expires_at)


# ---------------------------------------------------------------- passkeys and password (docs/08 -> Passkeys)


class PasskeyFinishIn(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=64)
    credential: dict[str, Any]


class ConfirmIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=256)


class PasskeyRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limiter(request: Request) -> LoginRateLimiter:
    return request.app.state.login_limiter


def _session(db: Session, ctx: Ctx) -> AuthSession:
    assert ctx.session is not None
    return db.merge(ctx.session)


def _sign_in_view(db: Session, ctx: Ctx) -> dict[str, Any]:
    return passkeys.view(db, ctx.user, ctx.session)


@router.post("/passkey/login/options")
def passkey_login_options(request: Request, origin: str | None = Header(default=None)) -> JSONResponse:
    if _limiter(request).blocked(f"{_client(request)}|passkey"):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.")
    return JSONResponse(passkeys.authentication_options(origin, "login"), headers={"Cache-Control": "no-store"})


@router.post("/passkey/login", response_model=SessionOut)
def passkey_login(
    payload: PasskeyFinishIn, request: Request, origin: str | None = Header(default=None), db: Session = Depends(get_db)
) -> JSONResponse:
    limiter, key = _limiter(request), f"{_client(request)}|passkey"
    if limiter.blocked(key):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.")
    try:
        row = passkeys.authenticate(db, origin, "login", payload.challenge_id, payload.credential)
    except ApiError as exc:
        if exc.status == 401:
            limiter.record_failure(key)
            audit(db, actor_id=None, action="auth.login_failed", details={"method": "passkey"})
            db.commit()
        raise
    user = db.get(User, row.user_id)
    assert user is not None
    limiter.reset(key)
    return _signed_in(db, user, method="passkey")


@router.post("/confirm")
def confirm_password(
    payload: ConfirmIn, request: Request, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """ "Confirm it is you" with the password: adding and removing passkeys are allowed for 5 minutes."""
    limiter, key = _limiter(request), f"{_client(request)}|{ctx.user.username.casefold()}"
    if limiter.blocked(key):
        raise ApiError(429, "too_many_attempts", "Too many failed attempts. Try again later.")
    if not verify_password(ctx.user.password_hash, payload.password):
        limiter.record_failure(key)
        raise ApiError(401, "invalid_credentials", "That password is not right.")
    limiter.reset(key)
    session = _session(db, ctx)
    session.confirmed_at = clock.now()
    db.commit()
    return _sign_in_view(db, Ctx(user=ctx.user, session=session, request_id=ctx.request_id))


@router.post("/confirm/passkey/options")
def confirm_passkey_options(
    ctx: Ctx = Depends(csrf_ctx), origin: str | None = Header(default=None), db: Session = Depends(get_db)
) -> JSONResponse:
    body = passkeys.authentication_options(origin, "confirm", db, ctx.user, ctx.session)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/confirm/passkey")
def confirm_passkey(
    payload: PasskeyFinishIn,
    request: Request,
    ctx: Ctx = Depends(csrf_ctx),
    origin: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limiter, key = _limiter(request), f"{_client(request)}|{ctx.user.username.casefold()}"
    if limiter.blocked(key):
        raise ApiError(429, "too_many_attempts", "Too many failed attempts. Try again later.")
    try:
        passkeys.authenticate(db, origin, "confirm", payload.challenge_id, payload.credential, ctx.session)
    except ApiError as exc:
        if exc.status == 401:
            limiter.record_failure(key)
        raise
    limiter.reset(key)
    session = _session(db, ctx)
    session.confirmed_at = clock.now()
    db.commit()
    return _sign_in_view(db, Ctx(user=ctx.user, session=session, request_id=ctx.request_id))


@router.get("/passkeys")
def list_passkeys(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _sign_in_view(db, ctx)


@router.post("/passkeys/options")
def add_passkey_options(
    ctx: Ctx = Depends(csrf_ctx), origin: str | None = Header(default=None), db: Session = Depends(get_db)
) -> JSONResponse:
    passkeys.require_confirmed(ctx.session)
    assert ctx.session is not None
    body = passkeys.registration_options(db, ctx.user, ctx.session, origin)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/passkeys", status_code=201)
def add_passkey(
    payload: PasskeyFinishIn,
    ctx: Ctx = Depends(csrf_ctx),
    origin: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    passkeys.require_confirmed(ctx.session)
    assert ctx.session is not None
    row = passkeys.register(db, ctx.user, ctx.session, origin, payload.challenge_id, payload.credential)
    audit(
        db,
        actor_id=ctx.user.id,
        action="auth.passkey_added",
        target_type="passkey",
        target_id=row.id,
        details={"name": row.name, "address": row.rp_id, "synced": row.backed_up},
        request_id=ctx.request_id,
    )
    db.commit()
    return {"passkey": passkeys.item(row), "sign_in": _sign_in_view(db, ctx)}


@router.patch("/passkeys/{passkey_id}")
def rename_passkey(
    passkey_id: uuid.UUID, payload: PasskeyRenameIn, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    row = passkeys.find(db, ctx.user, passkey_id)
    name = " ".join(payload.name.split())
    if not name:
        raise ApiError(422, "validation_error", "Give the passkey a name.")
    if name != row.name:
        audit(
            db,
            actor_id=ctx.user.id,
            action="auth.passkey_renamed",
            target_type="passkey",
            target_id=row.id,
            details={"from": row.name, "to": name},
            request_id=ctx.request_id,
        )
        row.name = name
        db.commit()
    return _sign_in_view(db, ctx)


@router.delete("/passkeys/{passkey_id}")
def remove_passkey(
    passkey_id: uuid.UUID, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Removed for good (a removed passkey must stop working at once); recorded in History."""
    passkeys.require_confirmed(ctx.session)
    row = passkeys.find(db, ctx.user, passkey_id)
    audit(
        db,
        actor_id=ctx.user.id,
        action="auth.passkey_removed",
        target_type="passkey",
        target_id=row.id,
        details={"name": row.name, "address": row.rp_id},
        request_id=ctx.request_id,
    )
    db.delete(row)
    db.commit()
    return _sign_in_view(db, ctx)


def set_password(db: Session, user: User, new_password: str, keep_session: uuid.UUID | None) -> int:
    """New password; every other session is signed out (all of them when ``keep_session`` is None)."""
    now = clock.now()
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    query = update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
    if keep_session is not None:
        query = query.where(AuthSession.id != keep_session)
    return db.execute(query.values(revoked_at=now)).rowcount or 0


@router.post("/password")
def change_password(
    payload: PasswordIn, request: Request, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    limiter, key = _limiter(request), f"{_client(request)}|{ctx.user.username.casefold()}"
    if limiter.blocked(key):
        raise ApiError(429, "too_many_attempts", "Too many failed attempts. Try again later.")
    user = db.merge(ctx.user)
    if not verify_password(user.password_hash, payload.current_password):
        limiter.record_failure(key)
        raise ApiError(401, "invalid_credentials", "The current password is not right.")
    limiter.reset(key)
    assert ctx.session is not None
    signed_out = set_password(db, user, payload.new_password, ctx.session.id)
    audit(
        db,
        actor_id=user.id,
        action="auth.password_changed",
        target_type="user",
        target_id=user.id,
        details={"signed_out": signed_out},
        request_id=ctx.request_id,
    )
    db.commit()
    return _sign_in_view(db, Ctx(user=user, session=ctx.session, request_id=ctx.request_id))


# ---------------------------------------------------------------- first run (plan-without-claude.md, Phase 3)

LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
_FIRST_RUN_LOCK = 4318_0001  # pg advisory lock: two first-run requests at once make only one account


def _first_run_refusal(request: Request) -> str | None:
    settings = get_settings()
    if settings.environment == "production" or not settings.first_run_enabled:
        return "disabled"
    if (request.client.host if request.client else "") not in LOOPBACK:
        return "not_local"
    return None


def _cross_site(request: Request) -> bool:
    """A page on another site must never create the account (no session or CSRF cookie exists yet)."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = request.headers.get("origin")
    return bool(origin) and (urlsplit(origin).hostname or "") not in LOOPBACK


def _has_users(db: Session) -> bool:
    return bool(db.scalar(select(exists().where(User.id.isnot(None)))))


@router.get("/setup")
def setup_status(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    """Whether this install still needs its first account, and whether this browser may create it."""
    needs = not _has_users(db)
    return {"needs_setup": needs, "refusal": _first_run_refusal(request) if needs else None}


@router.post("/setup", status_code=201, response_model=SessionOut)
def first_run(payload: FirstRunIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """Create the first account and sign it in. Refused once any account exists, from another computer, from
    another site, and in production (use ``recallspring create-owner`` there)."""
    refusal = _first_run_refusal(request)
    if refusal == "disabled":
        raise ApiError(403, "first_run_disabled", "Create the account with the command line on this server.")
    if refusal == "not_local" or _cross_site(request):
        raise ApiError(
            403, "first_run_not_local", "Open RecallSpring on this computer (http://127.0.0.1:4318) to set it up."
        )
    timezones.check(payload.timezone)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _FIRST_RUN_LOCK})
    if _has_users(db):
        raise ApiError(409, "already_set_up", "RecallSpring already has an account. Sign in instead.")
    user = User(username=payload.username, password_hash=hash_password(payload.password), timezone=payload.timezone)
    db.add(user)
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="user.created",
        target_type="user",
        target_id=user.id,
        details={"via": "first_run", "timezone": payload.timezone},
    )
    return _signed_in(db, user, 201)
