from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, csrf_ctx, current_ctx
from ..errors import ApiError
from ..models import User
from ..schemas import FirstRunIn, LoginIn, SessionOut, UserOut
from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    LoginRateLimiter,
    create_session,
    hash_password,
    verify_password,
)
from ..services import timezones
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


def _signed_in(db: Session, user: User, status_code: int = 200) -> JSONResponse:
    """Start a session for ``user`` (audited) and set its cookies."""
    settings = get_settings()
    token, csrf, session = create_session(db, user, settings.session_ttl_hours)
    audit(db, actor_id=user.id, action="auth.login")
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
