from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, csrf_ctx, current_ctx
from ..errors import ApiError
from ..models import User
from ..schemas import LoginIn, SessionOut, UserOut
from ..security import CSRF_COOKIE, SESSION_COOKIE, LoginRateLimiter, create_session, verify_password
from ..services.events import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    settings = get_settings()
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
    token, csrf, session = create_session(db, user, settings.session_ttl_hours)
    audit(db, actor_id=user.id, action="auth.login")
    db.commit()

    body = SessionOut(user=UserOut.model_validate(user), expires_at=session.expires_at).model_dump(mode="json")
    response = JSONResponse(body)
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
