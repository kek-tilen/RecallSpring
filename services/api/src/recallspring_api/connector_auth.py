"""Authentication for the Claude connector (Mode A).

Connector tokens are bearer tokens accepted **only** by routes under ``/api/v1/connector`` (read + append).
They never work on owner routes, which require the session cookie and CSRF token, so a connector cannot reach
deletion, export, budget, consent or account actions by construction. Every request counts towards the
owner's daily connector limit (1–100 % of the default).
"""

from __future__ import annotations

import math
import secrets
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import clock
from .config import get_settings
from .db import get_db, new_session
from .deps import Ctx, WriteCtx, to_write_ctx
from .errors import ApiError, request_id_var
from .models import ConnectorToken, ConnectorUsage, User
from .security import sha256_hex

TOKEN_PREFIX = "rsc_"


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def daily_limit(user: User) -> int:
    return max(1, math.ceil(get_settings().connector_daily_requests_default * user.connector_limit_percent / 100))


def local_day(user: User) -> date:
    return clock.now().astimezone(ZoneInfo(user.timezone)).date()


def used_today(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(ConnectorUsage.requests).where(
                ConnectorUsage.user_id == user.id, ConnectorUsage.day == local_day(user)
            )
        )
        or 0
    )


def _count_request(user: User, token_id: object) -> None:
    """Count in its own committed transaction so throttling holds even if the request later fails."""
    with new_session() as db:
        stmt = (
            insert(ConnectorUsage)
            .values(user_id=user.id, day=local_day(user), requests=1)
            .on_conflict_do_update(
                index_elements=[ConnectorUsage.user_id, ConnectorUsage.day],
                set_={"requests": ConnectorUsage.requests + 1},
            )
            .returning(ConnectorUsage.requests)
        )
        count = db.execute(stmt).scalar_one()
        token = db.get(ConnectorToken, token_id)
        if token is not None:
            token.last_used_at = clock.now()
        db.commit()
    limit = daily_limit(user)
    if count > limit:
        raise ApiError(
            429,
            "connector_daily_limit",
            f"RecallSpring's daily connector limit is reached ({limit} requests at {user.connector_limit_percent} %). "
            "Your notes and answers are saved; change the limit in RecallSpring settings or continue tomorrow.",
        )


def connector_ctx(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Ctx:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "connector_token_required", "This endpoint needs a RecallSpring connector token.")
    token = db.scalar(select(ConnectorToken).where(ConnectorToken.token_hash == sha256_hex(authorization[7:].strip())))
    if token is None or token.revoked_at is not None:
        raise ApiError(
            401,
            "connector_token_invalid",
            "This connector token is invalid or was revoked. Create a new one in RecallSpring settings.",
        )
    user = db.get(User, token.user_id)
    if user is None:
        raise ApiError(401, "connector_token_invalid", "This connector token is invalid.")
    _count_request(user, token.id)
    return Ctx(user=user, session=None, request_id=request_id_var.get())


def connector_write_ctx(
    request: Request,
    ctx: Ctx = Depends(connector_ctx),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> WriteCtx:
    return to_write_ctx(request, ctx, idempotency_key)
