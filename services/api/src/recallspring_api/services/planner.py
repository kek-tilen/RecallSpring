"""Deterministic daily plan, policy ``plan-v1`` (docs/05 → Daily planner, ADR-005). Never calls a model.

Per course, the nearest upcoming study target (kolokvij / izpit) defines the *active scope*. Material of passed
targets is in *maintenance*: only its due reviews are planned, within the owner's maintenance share of the day.
Everything else is ranked by an explainable score::

    score = urgency(days left) × need(category) × exam-profile weight × difficulty factor

and filled into today's available minutes (weekday default or a per-day override). Each item says why it was
chosen, and each active target gets a capacity check (work left vs. time left).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AvailabilityOverride,
    Concept,
    ConceptSource,
    Course,
    ReviewState,
    Source,
    SourceSection,
    StudyTarget,
    User,
)
from . import learning, mastery
from .targets import active_target, latest_profile, live_targets, scope_concepts

PLAN_POLICY = "plan-v1"
MAX_ITEMS = 6
BASE_MINUTES = {"Review due": 4, "Maintain": 4, "Strengthen": 6, "Learn next": 12, "Practice": 6}
# Minutes still needed per concept: learning (12) + first practice (6) when not studied, otherwise by band.
REMAINING_WORK = {"not_studied": 18, "not_started": 6, "emerging": 10, "developing": 6, "reliable": 0}
WEAK_REASONS = {"partial", "lapse", "uncertain_followup"}
EMPTY_MESSAGE = "You're caught up. Continue a topic or browse your library."
NOTE = "Estimated from practice, not a guarantee of recall."


def minutes_available(db: Session, user: User, day: date) -> int:
    override = db.get(AvailabilityOverride, (user.id, day))
    return override.minutes if override is not None else int(user.weekly_minutes[day.weekday()])


def _urgency(days_left: int | None) -> float:
    if days_left is None:
        return 1.0
    if days_left <= 3:
        return 3.0
    if days_left <= 7:
        return 2.0
    if days_left <= 14:
        return 1.5
    return 1.0


def _when(due_at: datetime, today: date, tz: ZoneInfo) -> str:
    days = (today - due_at.astimezone(tz).date()).days
    return "today" if days <= 0 else f"{days} day{'s' if days != 1 else ''} ago"


class _CourseScope:
    def __init__(self, db: Session, course: Course, today: date) -> None:
        targets = live_targets(db, course.id)
        self.active: StudyTarget | None = active_target(targets, today)
        self.active_scope: set[uuid.UUID] | None = scope_concepts(db, self.active) if self.active else None
        passed = [t for t in targets if t.status == "passed"]
        self.passed_names = [t.name for t in passed]
        self.passed_scope: set[uuid.UUID] = set()
        for t in passed:
            self.passed_scope |= scope_concepts(db, t)
        if self.active_scope is not None:
            self.passed_scope -= self.active_scope
        self.weights: dict[str, float] = {}
        profile = latest_profile(db, self.active.id) if self.active else None
        for w in profile.topic_weights if profile else []:
            if isinstance(w, dict) and w.get("concept_id"):
                self.weights[str(w["concept_id"])] = max(0.5, min(2.0, float(w.get("weight", 1.0))))
        self.days_left = (self.active.due_date - today).days if self.active else None


def today_plan(
    db: Session, user: User, now: datetime, minutes: int | None = None, course_id: uuid.UUID | None = None
) -> dict[str, Any]:
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    available = minutes if minutes is not None else minutes_available(db, user, today)
    # Archived courses (e.g. a finished semester) only keep their due reviews, as maintenance, when the course is
    # meant for long-term retention.
    course_stmt = select(Course).where(
        Course.user_id == user.id,
        Course.deleted_at.is_(None),
        (Course.status == "active") | ((Course.status == "archived") & Course.long_term_retention.is_(True)),
    )
    if course_id is not None:
        course_stmt = course_stmt.where(Course.id == course_id)
    courses = {c.id: c for c in db.scalars(course_stmt.order_by(Course.created_at))}
    scopes = {cid: _CourseScope(db, c, today) for cid, c in courses.items()}
    states = {s.concept_id: s for s in db.scalars(select(ReviewState).where(ReviewState.user_id == user.id))}
    concepts = (
        list(
            db.scalars(
                select(Concept)
                .where(Concept.course_id.in_(courses), Concept.deleted_at.is_(None))
                .order_by(Concept.created_at, Concept.term)
            )
        )
        if courses
        else []
    )

    sections_map, order_keys = _material(db, [c.id for c in concepts])
    status_map = {c.id: learning.effective_status(c, c.id in states) for c in concepts}
    main: list[dict[str, Any]] = []
    maintenance: list[tuple[datetime, dict[str, Any]]] = []
    for concept in concepts:
        sc = scopes[concept.course_id]
        state = states.get(concept.id)
        due = state is not None and state.due_at <= now
        band = mastery.band(state)
        diff = mastery.difficulty(concept, state)
        target_name = sc.active.name if sc.active else None
        in_active = sc.active_scope is None or concept.id in sc.active_scope

        if courses[concept.course_id].status == "archived":
            if due and state is not None:
                why = f"Archived course, kept in memory: due {_when(state.due_at, today, tz)}."
                maintenance.append((state.due_at, _item("Maintain", concept, courses, why, band, diff, None)))
            continue
        if concept.id in sc.passed_scope:
            if due and state is not None:
                why = (
                    f"Maintenance of {', '.join(sc.passed_names)} material: due {_when(state.due_at, today, tz)}. "
                    + (f"Kept short so {target_name} gets priority." if target_name else "Keeps it in memory.")
                )
                maintenance.append((state.due_at, _item("Maintain", concept, courses, why, band, diff, None)))
            continue
        if not in_active:
            if due and state is not None:  # outside the current target: only keep due reviews, low priority
                why = f"Due {_when(state.due_at, today, tz)}; not part of {target_name}, so lower priority."
                main.append(_scored(0.5, 1.0, "Review due", concept, courses, why, band, diff, None))
            continue

        context = f" Counts for {target_name} in {sc.days_left} days." if target_name else ""
        weight = sc.weights.get(str(concept.id), 1.0)
        if weight > 1.0:
            context += " Frequent topic on past papers."
        urgency = _urgency(sc.days_left)
        if due and state is not None:
            overdue = (today - state.due_at.astimezone(tz).date()).days
            why = f"Due {_when(state.due_at, today, tz)}. {state.due_reason.get('message', '')}".strip() + context
            main.append(
                _scored(
                    urgency * weight,
                    1.0 + min(0.1 * overdue, 0.5),
                    "Review due",
                    concept,
                    courses,
                    why,
                    band,
                    diff,
                    target_name,
                )
            )
        elif state is None and status_map[concept.id] == "not_studied":
            pages = ", ".join(sec["citation_label"] for sec in sections_map.get(concept.id, [])[:3])
            why = (
                "New material, not studied yet: "
                + (f"study {pages} " if pages else "study it ")
                + "with Claude's explanation, then summarise it in your own words."
                + context
            )
            item = _item("Learn next", concept, courses, why, band, diff, target_name)
            item["_score"] = urgency * 0.95  # in material order, not by difficulty
            item["_order"] = order_keys.get(concept.id, ())
            if weight > 1.0:
                item["estimated_minutes"] += 4  # frequent on past papers: study it in more depth
            main.append(item)
        elif state is None:
            label = "Studied" if status_map[concept.id] == "studied" else "Already known"
            why = f"{label}, not practised yet: a few Bloom 3-5 questions check it." + context
            main.append(_scored(urgency * weight, 0.9, "Practice", concept, courses, why, band, diff, target_name))
        elif band == "emerging" or mastery.evidence_code(state) in WEAK_REASONS:
            why = (
                f"{mastery.BAND_LABELS[band]}: your last answers showed gaps; a short exercise now strengthens it "
                f"before the review on {state.due_at.astimezone(tz).date().isoformat()}." + context
            )
            need = 0.8 + (0.2 if state.lapse_count else 0.0)
            main.append(_scored(urgency * weight, need, "Strengthen", concept, courses, why, band, diff, target_name))

    items: list[dict[str, Any]] = []
    used = 0
    maintenance_budget = round(available * user.maintenance_percent / 100)
    maint_used = 0
    for _, item in sorted(maintenance, key=lambda m: m[0]):
        if maint_used and maint_used + item["estimated_minutes"] > maintenance_budget:
            break
        items.append(item)
        maint_used += item["estimated_minutes"]
    used += maint_used
    main_added = 0
    for item in sorted(main, key=lambda i: (-round(i["_score"], 6), i.get("_order", ()), i["term"])):
        if len(items) >= MAX_ITEMS or (main_added and used + item["estimated_minutes"] > available):
            break
        items.append(item)
        used += item["estimated_minutes"]
        main_added += 1
    ordered = [i for i in items if i["category"] != "Maintain"] + [i for i in items if i["category"] == "Maintain"]
    for i in ordered:
        i.pop("_score", None)
        i.pop("_order", None)
        i["study_status"] = status_map[i["concept_id"]]
        i["sections"] = sections_map.get(i["concept_id"], [])[:3]
    return {
        "policy_version": PLAN_POLICY,
        "generated_at": now,
        "available_minutes": available,
        "planned_minutes": used,
        "maintenance_percent": user.maintenance_percent,
        "items": ordered,
        "targets": [
            _capacity(db, user, courses[cid], sc, states, status_map, now, today, len(scopes))
            for cid, sc in scopes.items()
            if sc.active is not None
        ],
        "message": None if ordered else EMPTY_MESSAGE,
        "note": NOTE,
    }


def _item(
    category: str,
    concept: Concept,
    courses: dict[Any, Course],
    why: str,
    band: str,
    diff: mastery.Difficulty,
    target: str | None,
) -> dict[str, Any]:
    return {
        "category": category,
        "concept_id": concept.id,
        "term": concept.term,
        "course_id": concept.course_id,
        "course_title": courses[concept.course_id].title,
        "why_selected": why,
        "estimated_minutes": BASE_MINUTES[category] + max(0, diff.value - 3),
        "target": target,
        "band": band,
        "difficulty": diff.value,
        "difficulty_source": diff.source,
    }


def _scored(
    urgency: float,
    need: float,
    category: str,
    concept: Concept,
    courses: dict[Any, Course],
    why: str,
    band: str,
    diff: mastery.Difficulty,
    target: str | None,
) -> dict[str, Any]:
    item = _item(category, concept, courses, why, band, diff, target)
    item["_score"] = urgency * need * (1 + (diff.value - 3) * 0.1)
    return item


def _capacity(
    db: Session,
    user: User,
    course: Course,
    sc: _CourseScope,
    states: dict[uuid.UUID, ReviewState],
    status_map: dict[uuid.UUID, str],
    now: datetime,
    today: date,
    course_count: int,
) -> dict[str, Any]:
    assert sc.active is not None and sc.active_scope is not None and sc.days_left is not None
    bands = {b: 0 for b in mastery.BANDS}
    studied = {"not_studied": 0, "studied": 0, "known": 0}
    remaining = 0
    for concept_id in sc.active_scope:
        state = states.get(concept_id)
        b = mastery.band(state)
        bands[b] += 1
        studied[status_map.get(concept_id, "not_studied")] += 1
        work_key = "not_studied" if b == "not_started" and status_map.get(concept_id) == "not_studied" else b
        remaining += REMAINING_WORK[work_key] + (
            BASE_MINUTES["Review due"] if state is not None and state.due_at <= now else 0
        )
    days = max(0, sc.days_left)
    total = sum(minutes_available(db, user, today + timedelta(days=d)) for d in range(days))
    usable = round(total * (100 - user.maintenance_percent) / 100 / max(1, course_count))
    status = "ok" if remaining <= 0.8 * usable else ("tight" if remaining <= usable else "at_risk")
    message = (
        f"About {remaining} min of work left for {sc.active.name}; about {usable} min of study time available "
        f"for this course until {sc.active.due_date.isoformat()} ({sc.days_left} days)."
    )
    if not sc.active_scope:
        message = f"No concepts are in the scope of {sc.active.name} yet: import the material and create concepts."
    elif status == "at_risk":
        message += f" Not enough time: about {round((remaining - usable) / max(1, days))} more min/day would be needed."
    return {
        "course_id": course.id,
        "course_title": course.title,
        "target_id": sc.active.id,
        "target": sc.active.name,
        "due_date": sc.active.due_date.isoformat(),
        "days_left": sc.days_left,
        "concepts_in_scope": len(sc.active_scope),
        "bands": bands,
        "study_status": studied,
        "remaining_minutes": remaining,
        "available_minutes": usable,
        "status": status,
        "message": message,
    }


def _material(
    db: Session, concept_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[dict[str, Any]]], dict[uuid.UUID, tuple]]:
    """Linked sections per concept (for "study pages X") and each concept's position in the material
    (source upload order, then page/position), so new material is learned in the order it is taught."""
    if not concept_ids:
        return {}, {}
    rows = db.execute(
        select(ConceptSource.concept_id, SourceSection, Source)
        .join(SourceSection, SourceSection.id == ConceptSource.section_id)
        .join(Source, Source.id == SourceSection.source_id)
        .where(ConceptSource.concept_id.in_(concept_ids), Source.deleted_at.is_(None))
        .order_by(Source.uploaded_at, Source.id, SourceSection.page, SourceSection.position)
    ).all()
    sections: dict[uuid.UUID, list[dict[str, Any]]] = {}
    order: dict[uuid.UUID, tuple] = {}
    for concept_id, section, source in rows:
        sections.setdefault(concept_id, []).append(
            {"section_id": section.id, "citation_label": section.citation_label, "filename": source.filename}
        )
        order.setdefault(concept_id, (source.uploaded_at, str(source.id), section.page or 0, section.position))
    return sections, order
