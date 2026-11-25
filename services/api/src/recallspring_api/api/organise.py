"""Owner-only organisation from the web app: university → faculty → semester groups, course colour and archive,
and editing exams/kolokviji (date, result, scope). Every change is audited; nothing is deleted."""

from __future__ import annotations

import uuid
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..models import Course, CourseGroup, User
from ..schemas import (
    ArchiveIn,
    CoursePatch,
    GroupIn,
    GroupPatch,
    MergeIn,
    ProfileConfirmIn,
    ProfileSourceIn,
    TargetIn,
    TargetUpdateIn,
)
from ..services import interests, overview, rationale, readiness
from ..services import targets as target_svc
from ..services.events import audit
from ..services.ownership import owned
from ..services.targets import target_view

router = APIRouter(tags=["organise"])

MAX_DEPTH = 6


def _group(db: Session, group_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> CourseGroup:
    group = db.get(CourseGroup, group_id, with_for_update=lock)
    if group is None or group.user_id != user_id or group.deleted_at is not None:
        raise ApiError(404, "not_found", "Group not found.")
    return group


def _check_parent(db: Session, user_id: uuid.UUID, group_id: uuid.UUID | None, parent_id: uuid.UUID | None) -> None:
    """The parent must be the learner's own group and must not be the group itself or one of its descendants."""
    depth = 0
    current = parent_id
    while current is not None:
        if current == group_id:
            raise ApiError(422, "invalid_parent", "A group cannot be placed inside itself.")
        depth += 1
        if depth > MAX_DEPTH:
            raise ApiError(422, "invalid_parent", "Groups can be nested at most six levels deep.")
        current = _group(db, current, user_id).parent_id


def _descendants(db: Session, user_id: uuid.UUID, root: uuid.UUID) -> list[uuid.UUID]:
    ids, frontier = [root], [root]
    while frontier:
        frontier = list(
            db.scalars(
                select(CourseGroup.id).where(
                    CourseGroup.user_id == user_id,
                    CourseGroup.parent_id.in_(frontier),
                    CourseGroup.deleted_at.is_(None),
                )
            )
        )
        ids += frontier
    return ids


def _today(user: User):  # type: ignore[no-untyped-def]
    return clock.now().astimezone(ZoneInfo(user.timezone)).date()


# ---------------------------------------------------------------- groups


@router.get("/groups")
def list_groups(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return overview.groups(db, ctx.user)


@router.post("/groups", status_code=201)
def create_group(payload: GroupIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if payload.starts_on and payload.ends_on and payload.starts_on > payload.ends_on:
        raise ApiError(422, "invalid_dates", "The start date must be before the end date.")
    _check_parent(db, ctx.user.id, None, payload.parent_id)
    group = CourseGroup(user_id=ctx.user.id, **payload.model_dump())
    db.add(group)
    db.flush()
    audit(
        db,
        actor_id=ctx.user.id,
        action="group.created",
        target_type="course_group",
        target_id=group.id,
        details={"kind": group.kind, "name": group.name},
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 201, overview.group_view(group, 0))


@router.patch("/groups/{group_id}")
def update_group(
    group_id: uuid.UUID, payload: GroupPatch, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    group = _group(db, group_id, ctx.user.id, lock=True)
    sent = payload.model_fields_set
    if "parent_id" in sent:
        _check_parent(db, ctx.user.id, group.id, payload.parent_id)
    changes: dict[str, Any] = {}
    for key in ("name", "kind", "parent_id", "starts_on", "ends_on", "position"):
        if key not in sent:
            continue
        value = getattr(payload, key)
        if value is None and key in ("name", "kind", "position"):
            continue
        if value != getattr(group, key):
            changes[key] = {"from": str(getattr(group, key)), "to": str(value)}
            setattr(group, key, value)
    if group.starts_on and group.ends_on and group.starts_on > group.ends_on:
        raise ApiError(422, "invalid_dates", "The start date must be before the end date.")
    group.revision += 1
    db.flush()
    audit(
        db,
        actor_id=ctx.user.id,
        action="group.updated",
        target_type="course_group",
        target_id=group.id,
        details=changes,
        request_id=ctx.request_id,
    )
    count = len(list(db.scalars(select(Course.id).where(Course.group_id == group.id, Course.deleted_at.is_(None)))))
    return commit_with_response(db, ctx, payload, 200, overview.group_view(group, count))


@router.post("/groups/{group_id}/archive")
def archive_group(
    group_id: uuid.UUID, payload: ArchiveIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Archive (or restore) a group with everything inside it: nested groups and their courses. Reversible.
    Archived courses leave the daily plan; with long-term retention their due reviews stay as maintenance."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    root = _group(db, group_id, ctx.user.id, lock=True)
    ids = _descendants(db, ctx.user.id, root.id)
    now = clock.now()
    new_group_status, from_course, to_course = (
        ("archived", "active", "archived") if payload.archived else ("active", "archived", "active")
    )
    for group in db.scalars(select(CourseGroup).where(CourseGroup.id.in_(ids)).with_for_update()):
        group.status = new_group_status
        group.archived_at = now if payload.archived else None
        group.revision += 1
    changed = []
    for course in db.scalars(
        select(Course)
        .where(
            Course.user_id == ctx.user.id,
            Course.group_id.in_(ids),
            Course.deleted_at.is_(None),
            Course.status == from_course,
        )
        .with_for_update()
    ):
        course.status = to_course
        course.revision += 1
        changed.append(str(course.id))
    db.flush()
    audit(
        db,
        actor_id=ctx.user.id,
        action="group.archived" if payload.archived else "group.restored",
        target_type="course_group",
        target_id=root.id,
        details={"groups": len(ids), "courses": changed},
        request_id=ctx.request_id,
    )
    return commit_with_response(
        db, ctx, payload, 200, {"groups": overview.groups(db, ctx.user), "courses_changed": len(changed)}
    )


# ---------------------------------------------------------------- courses


@router.patch("/courses/{course_id}")
def update_course(
    course_id: uuid.UUID, payload: CoursePatch, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    course = owned(db, Course, course_id, ctx.user.id, for_update=True)
    sent = payload.model_fields_set
    changes: dict[str, Any] = {}
    if payload.kind is not None and (kind_change := interests.change_kind(db, course, payload.kind)):
        changes["kind"] = kind_change
    if "group_id" in sent and payload.group_id is not None:
        interests.refuse_interest_filing(course)
        _group(db, payload.group_id, ctx.user.id)
    for key in ("title", "description", "color", "group_id", "long_term_retention"):
        if key not in sent:
            continue
        value = getattr(payload, key)
        if value is None and key in ("title", "long_term_retention"):
            continue
        if value != getattr(course, key):
            changes[key] = {"from": str(getattr(course, key)), "to": str(value)}
            setattr(course, key, value)
    if payload.archived is not None:
        status = "archived" if payload.archived else "active"
        if status != course.status:
            changes["status"] = {"from": course.status, "to": status}
            course.status = status
    course.revision += 1
    db.flush()
    audit(
        db,
        actor_id=ctx.user.id,
        action="course.updated",
        target_type="course",
        target_id=course.id,
        details=changes,
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 200, overview.course_view(course))


# ---------------------------------------------------------------- exams and kolokviji


@router.get("/targets")
def list_targets(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return overview.targets_timeline(db, ctx.user)


@router.get("/targets/{target_id}/rationale")
def target_rationale(
    target_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Why this plan (ADR-013 §2): what the old papers show, coverage by points, today's order, fit and limits."""
    return rationale.rationale(db, ctx.user, target_id, clock.now())


@router.get("/targets/{target_id}/readiness")
def target_readiness(
    target_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """What is left before this exam, by material: not studied, weak, not practised, getting there, solid."""
    return readiness.readiness(db, ctx.user, target_id, clock.now())


@router.post("/targets", status_code=201)
def create_target(payload: TargetIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = target_svc.create_target(db, ctx.user, payload, ctx.request_id, origin="web")
    return commit_with_response(db, ctx, payload, 201, target_view(db, target, _today(ctx.user)))


@router.patch("/targets/{target_id}")
def update_target(
    target_id: uuid.UUID, payload: TargetUpdateIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Move a date (also by dragging on the timeline), rename, record a result or change the scope."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = target_svc.update_target(db, ctx.user, target_id, payload, ctx.request_id, origin="web")
    return commit_with_response(db, ctx, payload, 200, target_view(db, target, _today(ctx.user)))


@router.put("/targets/{target_id}/profile/source")
def link_profile_source(
    target_id: uuid.UUID, payload: ProfileSourceIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The learner says which old paper (now in the course's material) the exam-style analysis came from."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = target_svc.link_profile_source(db, ctx.user, target_id, payload.source_id, ctx.request_id)
    return commit_with_response(db, ctx, payload, 200, target_view(db, target, _today(ctx.user)))


@router.post("/targets/{target_id}/profile/confirm")
def confirm_profile(
    target_id: uuid.UUID, payload: ProfileConfirmIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The learner confirms in the web app that the latest exam-style analysis matches the paper (ADR-013)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = target_svc.confirm_profile(db, ctx.user, target_id, payload.profile_id, "web", clock.now(), ctx.request_id)
    return commit_with_response(db, ctx, payload, 200, target_view(db, target, _today(ctx.user)))


RESTORE_DAYS = 30


@router.get("/targets/deleted")
def deleted_targets(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Exams deleted in the last 30 days, newest first, so they can be restored."""
    return overview.deleted_targets(db, ctx.user, RESTORE_DAYS)


@router.delete("/targets/{target_id}")
def delete_target(
    target_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Soft delete after the learner confirmed it in the app. Simulations, answers and grades are kept."""
    if replay := replay_if_seen(db, ctx, {"delete": str(target_id)}):
        return replay
    target = target_svc.delete_target(db, ctx.user, target_id, ctx.request_id, clock.now())
    body = {"deleted": target_view(db, target, _today(ctx.user)), "restorable_days": RESTORE_DAYS}
    return commit_with_response(db, ctx, {"delete": str(target_id)}, 200, body)


@router.post("/targets/{target_id}/restore")
def restore_target(
    target_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, {"restore": str(target_id)}):
        return replay
    target = target_svc.restore_target(db, ctx.user, target_id, ctx.request_id)
    return commit_with_response(db, ctx, {"restore": str(target_id)}, 200, target_view(db, target, _today(ctx.user)))


@router.post("/targets/{target_id}/merge")
def merge_target(
    target_id: uuid.UUID, payload: MergeIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Merge this duplicate into ``into_id`` (the exam to keep) and soft-delete it."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    kept = target_svc.merge_targets(db, ctx.user, target_id, payload.into_id, ctx.request_id, clock.now())
    return commit_with_response(db, ctx, payload, 200, target_view(db, kept, _today(ctx.user)))
