"""Owner-only settings and planner (session cookie + CSRF). Connector tokens cannot reach these routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import backup, clock
from ..config import get_settings
from ..connector_auth import daily_limit, new_token, used_today
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..models import ConnectorToken, User
from ..schemas import (
    ConnectorSettingsIn,
    ConnectorSettingsOut,
    ConnectorTokenCreatedOut,
    ConnectorTokenIn,
    ConnectorTokenOut,
    FocusIn,
    PlanOut,
    PreferencesIn,
    ProfileIn,
    StudySettingsIn,
    UserOut,
)
from ..security import sha256_hex
from ..services import assistants, chatgpt_import, interests, timezones
from ..services.events import audit
from ..services.planner import today_plan

router = APIRouter(tags=["settings"])


def _settings_view(db: Session, user: User) -> dict[str, Any]:
    tokens = db.scalars(
        select(ConnectorToken).where(ConnectorToken.user_id == user.id).order_by(ConnectorToken.created_at)
    )
    return ConnectorSettingsOut(
        limit_percent=user.connector_limit_percent,
        daily_default=get_settings().connector_daily_requests_default,
        daily_limit=daily_limit(user),
        used_today=used_today(db, user),
        tokens=[ConnectorTokenOut.model_validate(t, from_attributes=True) for t in tokens],
    ).model_dump(mode="json")


@router.get("/planner/today", response_model=PlanOut)
def planner_today(
    minutes: int | None = Query(default=None, ge=0, le=720),
    course_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(current_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return today_plan(db, ctx.user, clock.now(), minutes, course_id)


def _study_view(db: Session, u: User) -> dict[str, Any]:
    return {
        "weekly_minutes": u.weekly_minutes,
        "maintenance_percent": u.maintenance_percent,
        "style_percent": u.style_percent,
        "interest_percent": u.interest_percent,
        "focus": interests.focus_view(db, u),
    }


@router.get("/settings/backup")
def backup_status(ctx: Ctx = Depends(current_ctx)) -> dict[str, Any]:
    """When the last backup ran, whether it was checked, where backups are kept (no secrets)."""
    return backup.status_view()


@router.post("/settings/backup")
def backup_now(ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Back up the database and the uploaded files now (usually seconds). Audited as ``backup.created`` or
    ``backup.failed`` by the backup itself, so a failure is on record although the request fails."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    db.rollback()  # no transaction stays open while pg_dump runs
    try:
        view = backup.run("manual", actor_id=ctx.user.id, request_id=ctx.request_id)
    except backup.BackupError as exc:
        if exc.code == "busy":
            raise ApiError(409, "backup_busy", exc.message) from exc
        raise ApiError(503, "backup_failed", exc.message, {"reason": exc.code}) from exc
    return commit_with_response(db, ctx, None, 200, view)


@router.get("/settings/study")
def study_settings(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _study_view(db, ctx.user)


@router.put("/settings/focus")
def update_focus(payload: FocusIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Put one course or interest first until a day (inclusive), or end the focus with ``course_id`` null."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    interests.set_focus(db, user, payload.course_id, payload.until, ctx.request_id, origin="web")
    return commit_with_response(db, ctx, payload, 200, _study_view(db, user))


@router.get("/settings/preferences")
def study_preferences(ctx: Ctx = Depends(current_ctx)) -> dict[str, Any]:
    """The learner's own words on how they like to study; Claude reads them at the start of a session."""
    return chatgpt_import.preferences_view(ctx.user)


@router.put("/settings/preferences")
def update_study_preferences(
    payload: PreferencesIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    view = chatgpt_import.set_preferences(db, user, payload.text, ctx.request_id)
    db.flush()
    return commit_with_response(db, ctx, payload, 200, view)


@router.put("/settings/profile")
def update_profile(
    payload: ProfileIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Time zone (dates, "today", plans) and the assistant the learner studies with (wording only)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    changes: dict[str, Any] = {}
    if payload.timezone is not None and payload.timezone != user.timezone:
        changes["timezone"] = {"from": user.timezone, "to": timezones.check(payload.timezone)}
        user.timezone = payload.timezone
    if "assistant" in payload.model_fields_set and payload.assistant != user.assistant:
        changes["assistant"] = {"from": user.assistant, "to": payload.assistant}
        user.assistant = payload.assistant
    if changes:
        audit(db, actor_id=user.id, action="profile.changed", details=changes, request_id=ctx.request_id)
    db.flush()
    return commit_with_response(db, ctx, payload, 200, UserOut.model_validate(user).model_dump(mode="json"))


@router.put("/settings/study")
def update_study_settings(
    payload: StudySettingsIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    changes = apply_study_settings(user, payload.model_dump(exclude_none=True))
    audit(db, actor_id=user.id, action="study.settings_changed", details=changes, request_id=ctx.request_id)
    db.flush()
    return commit_with_response(db, ctx, payload, 200, _study_view(db, user))


def apply_study_settings(user: User, values: dict[str, Any]) -> dict[str, Any]:
    if any(m < 0 or m > 720 for m in values.get("weekly_minutes", [])):
        raise ApiError(422, "invalid_minutes", "Minutes per day must be between 0 and 720.")
    changes = {}
    for key, value in values.items():
        changes[key] = {"from": getattr(user, key), "to": value}
        setattr(user, key, value)
    return changes


@router.get("/settings/connector", response_model=ConnectorSettingsOut)
def connector_settings(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _settings_view(db, ctx.user)


@router.put("/settings/connector", response_model=ConnectorSettingsOut)
def update_connector_settings(
    payload: ConnectorSettingsIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    old = user.connector_limit_percent
    user.connector_limit_percent = payload.limit_percent
    audit(
        db,
        actor_id=user.id,
        action="connector.limit_changed",
        details={"from": old, "to": payload.limit_percent},
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 200, _settings_view(db, user))


def issue_token(
    db: Session, user_id: uuid.UUID, label: str | None, client: str = "claude"
) -> tuple[ConnectorToken, str]:
    token = new_token()
    row = ConnectorToken(
        user_id=user_id,
        label=label or assistants.DEFAULT_LABEL[client],
        client=client,
        token_hash=sha256_hex(token),
        created_at=clock.now(),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        actor_id=user_id,
        action="connector.token_created",
        target_type="connector_token",
        target_id=row.id,
        details={"client": client},
    )
    return row, token


@router.post("/settings/connector/tokens", status_code=201, response_model=ConnectorTokenCreatedOut)
def create_token(
    payload: ConnectorTokenIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The token is shown once and stored only as a hash; a replay of this request returns ``token: null``."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    row, token = issue_token(db, ctx.user.id, payload.label, payload.client)
    base = ConnectorTokenOut.model_validate(row, from_attributes=True).model_dump(mode="json")
    return commit_with_response(db, ctx, payload, 201, {**base, "token": token}, stored_body={**base, "token": None})


@router.post("/settings/connector/tokens/{token_id}/revoke", response_model=ConnectorTokenOut)
def revoke_token(
    token_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, None):
        return replay
    row = db.get(ConnectorToken, token_id, with_for_update=True)
    if row is None or row.user_id != ctx.user.id:
        raise ApiError(404, "not_found", "Connector token not found.")
    if row.revoked_at is None:
        row.revoked_at = clock.now()
        audit(
            db,
            actor_id=ctx.user.id,
            action="connector.token_revoked",
            target_type="connector_token",
            target_id=row.id,
            request_id=ctx.request_id,
        )
    db.flush()
    return commit_with_response(
        db, ctx, None, 200, ConnectorTokenOut.model_validate(row, from_attributes=True).model_dump(mode="json")
    )
