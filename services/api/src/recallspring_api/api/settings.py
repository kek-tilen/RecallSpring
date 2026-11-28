"""Owner-only settings and planner (session cookie + CSRF). Connector tokens cannot reach these routes."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import backup, clock, cloud
from ..ai import siwc
from ..config import get_settings
from ..connector_auth import daily_limit, new_token, used_today
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, csrf_ctx, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..models import AiConversation, ConnectorToken, User
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
from ..services import assistants, chatgpt_import, explanation_pace, interests, timezones
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
        remote_url=f"{remote}/mcp" if (remote := get_settings().remote_url) else None,
        remote_from_internet=bool(remote) and get_settings().remote_from_internet,
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


class BackupFolderIn(BaseModel):
    path: str | None = Field(default=None, max_length=1000)


class BackupScheduleIn(BaseModel):
    every: Literal["days", "monthly"]
    days: int | None = Field(default=None, ge=1, le=backup.EVERY_MAX_DAYS)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class BackupEncryptionIn(BaseModel):
    recipient: str = Field(min_length=10, max_length=200)
    remove_unencrypted: bool = False


def _backup_owner(db: Session, user: User) -> bool:
    """A backup holds the whole installation, so only its first account may move it (2026-11-27)."""
    first = db.scalar(select(User.id).order_by(User.created_at, User.id).limit(1))
    return first == user.id


def _require_backup_owner(db: Session, user: User) -> None:
    if not get_settings().backup_settings_from_web:
        raise ApiError(403, "backup_folder_locked", "Backups are set in the server settings here.")
    if not _backup_owner(db, user):
        raise ApiError(403, "not_backup_owner", "Only the first account on this RecallSpring can change backups.")


def _backup_view(db: Session, user: User) -> dict[str, Any]:
    """The status view every backup route returns, with whether this account may change backups."""
    view = backup.status_view()
    view["can_change"] = get_settings().backup_settings_from_web and _backup_owner(db, user)
    view["cloud"] = cloud.view()
    return view


@router.get("/settings/backup")
def backup_status(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """When the last backup ran, whether it was checked, where backups are kept (no secrets)."""
    return _backup_view(db, ctx.user)


@router.post("/settings/backup/folder/check")
def backup_folder_check(
    payload: BackupFolderIn, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Try a folder before choosing it (nothing is saved or created)."""
    _require_backup_owner(db, ctx.user)
    return backup.check_folder(payload.path)


@router.put("/settings/backup/folder")
def backup_folder_set(
    payload: BackupFolderIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Choose where backups go (path null: back to the server's folder). Refused while a backup runs. Audited as
    ``backup.folder_changed`` by backup.set_folder."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    _require_backup_owner(db, ctx.user)
    db.rollback()
    try:
        backup.set_folder(payload.path, actor_id=ctx.user.id, request_id=ctx.request_id)
    except backup.BackupError as exc:
        if exc.code == "busy":
            raise ApiError(409, "backup_busy", exc.message) from exc
        raise ApiError(422 if exc.code == "folder_refused" else 409, exc.code, exc.message) from exc
    return commit_with_response(db, ctx, payload, 200, _backup_view(db, ctx.user))


@router.put("/settings/backup/schedule")
def backup_schedule_set(
    payload: BackupScheduleIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """How often backups run and at what time (2026-11-27). Audited as ``backup.schedule_changed``."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    _require_backup_owner(db, ctx.user)
    db.rollback()
    try:
        backup.set_schedule(
            payload.every,
            payload.days,
            payload.at,
            day_of_month=payload.day_of_month,
            actor_id=ctx.user.id,
            request_id=ctx.request_id,
        )
    except backup.BackupError as exc:
        status = {"busy": 409, "invalid_schedule": 422, "folder_locked": 403}.get(exc.code, 409)
        raise ApiError(status, "backup_busy" if exc.code == "busy" else exc.code, exc.message) from exc
    return commit_with_response(db, ctx, payload, 200, _backup_view(db, ctx.user))


@router.post("/settings/backup")
def backup_now(ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Back up the database and the uploaded files now (usually seconds). Audited as ``backup.created`` or
    ``backup.failed`` by the backup itself, so a failure is on record although the request fails."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    db.rollback()  # no transaction stays open while pg_dump runs
    try:
        backup.run("manual", actor_id=ctx.user.id, request_id=ctx.request_id)
    except backup.BackupError as exc:
        if exc.code == "busy":
            raise ApiError(409, "backup_busy", exc.message) from exc
        raise ApiError(503, "backup_failed", exc.message, {"reason": exc.code}) from exc
    if cloud.connection() is not None:
        cloud.copy_in_background(actor_id=ctx.user.id, request_id=ctx.request_id)
    return commit_with_response(db, ctx, None, 200, _backup_view(db, ctx.user))


@router.post("/settings/backup/key")
def backup_new_key(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """A new recovery key, shown once. Nothing is stored and no response is kept for replays: the private half
    exists only in this response (Cache-Control: no-store) until the learner saves it."""
    _require_backup_owner(db, ctx.user)
    return JSONResponse(backup.new_key(), headers={"Cache-Control": "no-store"})


@router.put("/settings/backup/encryption")
def backup_encryption_set(
    payload: BackupEncryptionIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Lock the next backups with the public half of a recovery key (turns encryption on, or replaces the key)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    _require_backup_owner(db, ctx.user)
    db.rollback()
    try:
        backup.set_encryption(
            payload.recipient,
            remove_unencrypted=payload.remove_unencrypted,
            actor_id=ctx.user.id,
            request_id=ctx.request_id,
        )
    except backup.BackupError as exc:
        status = {"busy": 409, "invalid_key": 422, "folder_locked": 403}.get(exc.code, 409)
        raise ApiError(status, "backup_busy" if exc.code == "busy" else exc.code, exc.message) from exc
    return commit_with_response(db, ctx, payload, 200, _backup_view(db, ctx.user))


# ---------------------------------------------------------------- cloud copy (cloud.py, 2026-11-27)

CLOUD_STATUS = {
    "not_configured": 409,
    "needs_encryption": 409,
    "unreachable": 503,
    "refused": 502,
    "revoked": 409,
    "bad_code": 422,
    "expired": 409,
}


def _cloud_error(exc: cloud.CloudError) -> ApiError:
    return ApiError(CLOUD_STATUS.get(exc.code, 503), f"cloud_{exc.code}", exc.message)


class CloudDisconnectIn(BaseModel):
    delete_files: bool = False


class CloudCodeIn(BaseModel):
    code: str = Field(min_length=8, max_length=200)


@router.post("/settings/backup/cloud/google/start")
def cloud_google_start(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """A code to type at google.com/device. The device code stays on the server; nothing is kept for replays."""
    _require_backup_owner(db, ctx.user)
    if cloud.connection() is not None:
        raise ApiError(409, "cloud_connected", "A cloud copy is connected already. Disconnect it first.")
    try:
        body = cloud.start_google()
    except cloud.CloudError as exc:
        raise _cloud_error(exc) from exc
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/settings/backup/cloud/dropbox/start")
def cloud_dropbox_start(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """The Dropbox page to open; Dropbox shows a code to paste back. The PKCE verifier stays on the server."""
    _require_backup_owner(db, ctx.user)
    if cloud.connection() is not None:
        raise ApiError(409, "cloud_connected", "A cloud copy is connected already. Disconnect it first.")
    try:
        body = cloud.start_dropbox()
    except cloud.CloudError as exc:
        raise _cloud_error(exc) from exc
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/settings/backup/cloud/dropbox/finish")
def cloud_dropbox_finish(
    payload: CloudCodeIn, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The code Dropbox showed (never stored or logged). On success the first copy starts in the background."""
    _require_backup_owner(db, ctx.user)
    db.rollback()
    try:
        cloud.finish_dropbox(payload.code, actor_id=ctx.user.id, request_id=ctx.request_id)
    except cloud.CloudError as exc:
        raise _cloud_error(exc) from exc
    cloud.copy_in_background(actor_id=ctx.user.id, request_id=ctx.request_id)
    return {"state": "connected", "backup": _backup_view(db, ctx.user)}


@router.post("/settings/backup/cloud/google/poll")
def cloud_google_poll(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Whether the learner finished signing in at Google: pending, connected, denied or expired. On connected the
    first copy starts in the background."""
    _require_backup_owner(db, ctx.user)
    db.rollback()
    try:
        state = cloud.poll_google(actor_id=ctx.user.id, request_id=ctx.request_id)
    except cloud.CloudError as exc:
        raise _cloud_error(exc) from exc
    if state == "connected":
        cloud.copy_in_background(actor_id=ctx.user.id, request_id=ctx.request_id)
    return {"state": state, "backup": _backup_view(db, ctx.user)}


@router.post("/settings/backup/cloud/cancel")
def cloud_cancel(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_backup_owner(db, ctx.user)
    cloud.cancel()
    return _backup_view(db, ctx.user)


@router.post("/settings/backup/cloud/copy")
def cloud_copy_now(ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    """Copy now, in the background; the page follows the status."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    _require_backup_owner(db, ctx.user)
    if cloud.connection() is None:
        raise ApiError(409, "cloud_off", "No cloud copy is connected.")
    db.rollback()
    cloud.copy_in_background(actor_id=ctx.user.id, request_id=ctx.request_id)
    return commit_with_response(db, ctx, None, 202, _backup_view(db, ctx.user))


@router.post("/settings/backup/cloud/disconnect")
def cloud_disconnect(
    payload: CloudDisconnectIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Forget the sign-in and ask Google or Dropbox to withdraw it; the files there stay unless delete_files (the
    page asks once more). Audited as backup.cloud_disconnected (and backup.cloud_files_deleted)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    _require_backup_owner(db, ctx.user)
    db.rollback()
    try:
        cloud.disconnect(payload.delete_files, actor_id=ctx.user.id, request_id=ctx.request_id)
    except cloud.CloudError as exc:
        raise _cloud_error(exc) from exc
    return commit_with_response(db, ctx, payload, 200, _backup_view(db, ctx.user))


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
    """Time zone (dates, "today", plans), the assistant the learner studies with (wording only) and what Home calls
    them (``greeting_name``; blank = none), and the default explanation pace (``explanation_pace``)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    changes: dict[str, Any] = {}
    if payload.timezone is not None and payload.timezone != user.timezone:
        changes["timezone"] = {"from": user.timezone, "to": timezones.check(payload.timezone)}
        user.timezone = payload.timezone
    if "assistant" in payload.model_fields_set:
        mix: list[str] = []
        if payload.assistant == "mix":
            mix = [k for k in ("claude", "codex", "chatgpt", "antigravity") if k in (payload.assistant_mix or [])]
            if len(mix) < 2:
                raise ApiError(422, "mix_too_small", "A mix needs at least two assistants.")
        if payload.assistant != user.assistant or mix != list(user.assistant_mix or []):
            changes["assistant"] = {"from": user.assistant, "to": payload.assistant}
            if mix or user.assistant_mix:
                changes["assistant_mix"] = {"from": list(user.assistant_mix or []), "to": mix}
            user.assistant = payload.assistant
            user.assistant_mix = mix
    if "greeting_name" in payload.model_fields_set:
        name = " ".join((payload.greeting_name or "").split()) or None
        if name != user.greeting_name:
            changes["greeting_name"] = {"set": name is not None}  # the name itself stays out of the audit log
            user.greeting_name = name
    if payload.explanation_pace is not None:
        explanation_pace.set_default(db, user, payload.explanation_pace, ctx.request_id, origin="web")
    if changes:
        audit(db, actor_id=user.id, action="profile.changed", details=changes, request_id=ctx.request_id)
    db.flush()
    return commit_with_response(db, ctx, payload, 200, UserOut.model_validate(user).model_dump(mode="json"))


@router.get("/settings/assistants")
def assistants_status(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Which assistants are connected now, from RecallSpring's own records: Claude Desktop, Codex and Antigravity by
    an active connector token, ChatGPT in Chat by its sign-in. ``in_use`` is the one the app names in its wording:
    the only connected one; the welcome page's choice while none is connected yet; none ("your assistant") when
    several are."""
    tokens = db.scalars(
        select(ConnectorToken).where(ConnectorToken.user_id == ctx.user.id, ConnectorToken.revoked_at.is_(None))
    ).all()
    items: list[dict[str, Any]] = []
    for client in ("claude", "codex", "antigravity"):
        mine = [t for t in tokens if t.client == client]
        used = max((t.last_used_at for t in mine if t.last_used_at), default=None)
        items.append({"key": client, "connected": bool(mine), "tokens": len(mine), "last_used_at": used})
    last_chat = db.scalar(
        select(func.max(AiConversation.updated_at)).where(
            AiConversation.user_id == ctx.user.id,
            AiConversation.provider == "chatgpt",
            AiConversation.deleted_at.is_(None),
        )
    )
    items.append(
        {"key": "chatgpt", "connected": siwc.status(ctx.user.id)["connected"], "tokens": 0, "last_used_at": last_chat}
    )
    for item in items:
        item["last_used_at"] = item["last_used_at"].isoformat() if item["last_used_at"] else None
    connected = [i["key"] for i in items if i["connected"]]
    chosen = ctx.user.assistant
    mix = list(ctx.user.assistant_mix or []) if chosen == "mix" else []
    for item in items:
        item["in_mix"] = item["key"] in mix
    if mix:  # a mix: show the chosen assistants first
        items.sort(key=lambda i: not i["in_mix"])
    fallback = chosen if chosen != "mix" else None  # a mix is "your assistant" until exactly one is connected
    in_use = connected[0] if len(connected) == 1 else (fallback if not connected else None)
    return {"items": items, "in_use": in_use, "chosen": chosen, "mix": mix}


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


@router.post("/settings/connector/clients/{client}/disconnect")
def disconnect_client(
    client: Literal["claude", "codex", "antigravity"], ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Disconnect one assistant: revoke all its active tokens at once (unticking it in Settings, 2026-11-27).
    Its grades and records stay; a new token connects it again."""
    if replay := replay_if_seen(db, ctx, None):
        return replay
    rows = db.scalars(
        select(ConnectorToken)
        .where(
            ConnectorToken.user_id == ctx.user.id,
            ConnectorToken.client == client,
            ConnectorToken.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    now = clock.now()
    for row in rows:
        row.revoked_at = now
    if rows:
        audit(
            db,
            actor_id=ctx.user.id,
            action="connector.disconnected",
            details={"client": client, "tokens": len(rows)},
            request_id=ctx.request_id,
        )
    db.flush()
    return commit_with_response(db, ctx, None, 200, {"client": client, "revoked": len(rows)})
