"""Pomodoro focus time: what the learner timed in the web app, summed by learner-local day and by course.

Focus time is self-timed effort, never evidence of learning; nothing here touches mastery or review scheduling.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError, not_found
from ..models import Course, FocusSession, User
from .events import audit

DAYS = 7
RESTORE_DAYS = 30


def _minutes(seconds: int) -> int:
    return round(seconds / 60)


def _day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def session_view(s: FocusSession, course_title: str | None) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "client_session_id": str(s.client_session_id),
        "course_id": str(s.course_id) if s.course_id else None,
        "course_title": course_title,
        "started_at": s.started_at.isoformat(),
        "ended_at": s.ended_at.isoformat(),
        "planned_minutes": s.planned_minutes,
        "minutes": _minutes(s.focused_seconds),
        "completed": s.completed,
        "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None,
    }


def _rows(
    db: Session, user: User, since: datetime, course_id: uuid.UUID | None
) -> list[tuple[FocusSession, str | None]]:
    stmt = (
        select(FocusSession, Course.title)
        .outerjoin(Course, Course.id == FocusSession.course_id)
        .where(FocusSession.user_id == user.id, FocusSession.ended_at >= since, FocusSession.deleted_at.is_(None))
        .order_by(FocusSession.ended_at.desc())
    )
    if course_id is not None:
        stmt = stmt.where(FocusSession.course_id == course_id)
    return [(s, title) for s, title in db.execute(stmt).all()]


def summary(db: Session, user: User, now: datetime) -> dict[str, Any]:
    """Today, the last seven days by day and by course, and the latest sessions (learner's time zone)."""
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    first = today - timedelta(days=DAYS - 1)
    by_day = {first + timedelta(days=i): [0, 0] for i in range(DAYS)}
    by_course: dict[str | None, dict[str, Any]] = {}
    for s, title in _rows(db, user, _day_start(first, tz), None):
        day = s.ended_at.astimezone(tz).date()
        if day in by_day:
            by_day[day][0] += s.focused_seconds
            by_day[day][1] += 1
        key = str(s.course_id) if s.course_id else None
        entry = by_course.setdefault(key, {"course_id": key, "course_title": title, "seconds": 0, "sessions": 0})
        entry["seconds"] += s.focused_seconds
        entry["sessions"] += 1
    recent = db.execute(
        select(FocusSession, Course.title)
        .outerjoin(Course, Course.id == FocusSession.course_id)
        .where(FocusSession.user_id == user.id, FocusSession.deleted_at.is_(None))
        .order_by(FocusSession.ended_at.desc())
        .limit(8)
    ).all()
    removed = db.execute(
        select(FocusSession, Course.title)
        .outerjoin(Course, Course.id == FocusSession.course_id)
        .where(FocusSession.user_id == user.id, FocusSession.deleted_at >= now - timedelta(days=RESTORE_DAYS))
        .order_by(FocusSession.deleted_at.desc())
        .limit(20)
    ).all()
    seconds_today, sessions_today = by_day[today]
    courses = [
        {
            "course_id": e["course_id"],
            "course_title": e["course_title"],
            "minutes": _minutes(e["seconds"]),
            "sessions": e["sessions"],
        }
        for e in by_course.values()
    ]
    return {
        "today": {"date": today.isoformat(), "minutes": _minutes(seconds_today), "sessions": sessions_today},
        "days": [{"date": d.isoformat(), "minutes": _minutes(sec), "sessions": n} for d, (sec, n) in by_day.items()],
        "week_minutes": _minutes(sum(sec for sec, _ in by_day.values())),
        "by_course": sorted(courses, key=lambda e: -e["minutes"]),
        "recent": [session_view(s, title) for s, title in recent],
        "removed": [session_view(s, title) for s, title in removed],
        "restore_days": RESTORE_DAYS,
    }


def set_removed(db: Session, user: User, session_id: uuid.UUID, removed: bool, request_id: str | None) -> None:
    """Remove a wrongly timed block (after the learner confirmed it) or restore it within RESTORE_DAYS. Audited;
    the learning event that recorded the block stays, as all learning events do."""
    s = db.scalar(
        select(FocusSession).where(FocusSession.id == session_id, FocusSession.user_id == user.id).with_for_update()
    )
    if s is None:
        raise not_found("Focus block")
    if (s.deleted_at is not None) == removed:
        return
    now = clock.now()
    if not removed and s.deleted_at is not None and s.deleted_at < now - timedelta(days=RESTORE_DAYS):
        raise ApiError(409, "restore_period_over", f"Removed focus blocks can be restored for {RESTORE_DAYS} days.")
    s.deleted_at = now if removed else None
    audit(
        db,
        actor_id=user.id,
        action="focus.deleted" if removed else "focus.restored",
        target_type="focus_session",
        target_id=s.id,
        details={"minutes": _minutes(s.focused_seconds), "course_id": str(s.course_id) if s.course_id else None},
        request_id=request_id,
    )


def course_focus(db: Session, user: User, course_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """For Claude at the start of a session: recent focus time in one course, framed as effort only."""
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    rows = _rows(db, user, _day_start(today - timedelta(days=DAYS - 1), tz), course_id)
    today_seconds = sum(s.focused_seconds for s, _ in rows if s.ended_at.astimezone(tz).date() == today)
    return {
        "today_minutes": _minutes(today_seconds),
        "last_7_days_minutes": _minutes(sum(s.focused_seconds for s, _ in rows)),
        "sessions_last_7_days": len(rows),
        "how_to_use": "Pomodoro focus time the learner timed for this course in RecallSpring. It shows effort and "
        "pacing only, never what they learned; do not treat it as evidence of mastery.",
    }
