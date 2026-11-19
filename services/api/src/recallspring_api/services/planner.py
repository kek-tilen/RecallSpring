"""Deterministic daily plan, policy ``plan-v0`` (docs/05 → Daily planner). Never calls a model.

Order: due reviews (oldest first), then concepts with recent gaps ("Strengthen"), then concepts not practised
yet ("Explore next"), filled up to the learner's available minutes (at least one item, at most five).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Concept, Course, ReviewState, User
from .reviews import review_queue

PLAN_POLICY = "plan-v0"
MAX_ITEMS = 5
ESTIMATED_MINUTES = {"Review due": 4, "Strengthen": 6, "Explore next": 8}
WEAK_REASONS = {"partial", "lapse", "uncertain_followup"}
EMPTY_MESSAGE = "You're caught up. Continue a topic or browse your library."


def _local_date(value: datetime, tz: ZoneInfo) -> str:
    return value.astimezone(tz).date().isoformat()


def today_plan(db: Session, user: User, now: datetime, minutes: int = 20) -> dict[str, Any]:
    tz = ZoneInfo(user.timezone)
    courses = {
        c.id: c.title
        for c in db.scalars(
            select(Course).where(Course.user_id == user.id, Course.deleted_at.is_(None), Course.status == "active")
        )
    }
    candidates: list[dict[str, Any]] = []

    for state, concept in review_queue(db, user, now, 0):
        if concept.course_id not in courses:
            continue
        overdue_days = (now.astimezone(tz).date() - state.due_at.astimezone(tz).date()).days
        when = "today" if overdue_days <= 0 else f"{overdue_days} day{'s' if overdue_days != 1 else ''} ago"
        candidates.append(
            _item("Review due", concept, courses, f"Due {when}. {state.due_reason.get('message', '')}".strip())
        )

    weak = db.execute(
        select(ReviewState, Concept)
        .join(Concept, Concept.id == ReviewState.concept_id)
        .where(ReviewState.user_id == user.id, ReviewState.due_at > now, Concept.deleted_at.is_(None))
        .order_by(ReviewState.last_review_at)
    ).all()
    for state, concept in weak:
        if concept.course_id in courses and (state.due_reason.get("code") in WEAK_REASONS or state.lapse_count > 0):
            candidates.append(
                _item(
                    "Strengthen",
                    concept,
                    courses,
                    f"Last practised {_local_date(state.last_review_at, tz)} with gaps; a short exercise now "
                    f"strengthens it before the review on {_local_date(state.due_at, tz)}.",
                )
            )

    scheduled = select(ReviewState.concept_id).where(ReviewState.user_id == user.id)
    fresh = db.scalars(
        select(Concept)
        .where(Concept.user_id == user.id, Concept.deleted_at.is_(None), Concept.id.not_in(scheduled))
        .order_by(Concept.created_at, Concept.term)
    )
    for concept in fresh:
        if concept.course_id in courses:
            candidates.append(
                _item(
                    "Explore next",
                    concept,
                    courses,
                    "Not practised yet. Read the linked source, write a note, then try a first question.",
                )
            )

    items: list[dict[str, Any]] = []
    used = 0
    for item in candidates:
        if len(items) >= MAX_ITEMS or (items and used + item["estimated_minutes"] > minutes):
            break
        items.append(item)
        used += item["estimated_minutes"]
    return {
        "policy_version": PLAN_POLICY,
        "generated_at": now,
        "available_minutes": minutes,
        "planned_minutes": used,
        "items": items,
        "message": None if items else EMPTY_MESSAGE,
        "note": "Estimated from practice, not a guarantee of recall.",
    }


def _item(category: str, concept: Concept, courses: dict[Any, str], why: str) -> dict[str, Any]:
    return {
        "category": category,
        "concept_id": concept.id,
        "term": concept.term,
        "course_id": concept.course_id,
        "course_title": courses[concept.course_id],
        "why_selected": why,
        "estimated_minutes": ESTIMATED_MINUTES[category],
    }
