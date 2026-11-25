"""Deterministic daily plan, policy ``plan-v2`` (docs/05 → Daily planner, ADR-005, ADR-007). Never calls a model.

Per course, the nearest upcoming study target (kolokvij / izpit) defines the *active scope*. Material of passed
targets is in *maintenance*: only its due reviews are planned, within the owner's maintenance share of the day.
Everything else is ranked by an explainable score::

    score = urgency(days left) × need(category) × exam-profile weight × difficulty factor

and filled into today's available minutes (weekday default or a per-day override). Each item says why it was
chosen, and each active target gets a capacity check (work left vs. time left).

``plan-v2`` adds personal *interests* (courses of kind ``interest``: learning without a deadline) and a *focus*:

- University first (``interest_percent`` 0, the default): interests get only the time left after today's course
  work, and only while every exam is on track; when one is tight or at risk the whole day goes to the courses.
- A share (``interest_percent`` 1-50): that share of the day is kept for interests first; courses get the rest,
  and their capacity checks count only the rest.
- Focus (``courses.focus_until``): the learner chose one course or interest to come first until a day; other work
  gets the time left, and the capacity checks of the other courses do not count the focus days.

Without interests and without a focus the plan is the same as ``plan-v1``.
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
from . import check_first, learning, mastery
from .targets import active_target, concept_weights, latest_profile, live_targets, scope_concepts

PLAN_POLICY = "plan-v2"
MAX_ITEMS = 6
MAX_INTEREST_ITEMS = 3
BASE_MINUTES = {"Review due": 4, "Maintain": 4, "Strengthen": 6, "Learn next": 12, "Practice": 6}
# Minutes still needed per concept: learning (12) + first practice (6) when not studied, otherwise by band.
REMAINING_WORK = {"not_studied": 18, "not_started": 6, "emerging": 10, "developing": 6, "reliable": 0}
WEAK_REASONS = {"partial", "lapse", "uncertain_followup"}
EMPTY_MESSAGE = "You're caught up. Continue a topic or browse your library."
NOTE = "Estimated from practice, not a guarantee of recall."
# How the scoring below orders a course's work, in words; "Why this plan" (rationale-v1, ADR-013) shows them.
# Keep them true to the code in today_plan when the scoring changes.
PRIORITY_RULES = (
    "Each piece of work gets a score: how close the exam is (x1 more than 2 weeks away, x1.5 within 2 weeks, x2 "
    "within a week, x3 within 3 days) x what it needs x how much its topic weighs on the old papers (0.5-2) x how "
    "hard the concept is (harder a little sooner).",
    "What it needs: a due review 1.0-1.5 (more when overdue), a studied concept not yet practised 0.9, a weak "
    "concept 0.8-1.0 (more when it was forgotten).",
    "New material counts 0.95 and keeps the order of the material whatever its weight, so earlier parts come before "
    "what builds on them; a topic that weighs more on the old papers gets 4 more minutes to study instead.",
    "With average weights: due reviews, then new material, then practice and weak concepts. A heavier topic can "
    "move ahead of new material; a lighter one falls behind it.",
    "Material outside this exam keeps only its due reviews, at lower priority; passed exams get a small "
    "maintenance share of the day.",
)
STATUS_WORDS = {"tight": "tight", "at_risk": "at risk"}


def minutes_available(db: Session, user: User, day: date) -> int:
    override = db.get(AvailabilityOverride, (user.id, day))
    return override.minutes if override is not None else int(user.weekly_minutes[day.weekday()])


def focus_course(db: Session, user_id: uuid.UUID, today: date) -> Course | None:
    """The course or interest the learner chose to concentrate on, while its focus lasts (a focus on an archived
    or deleted course is ignored)."""
    return db.scalar(
        select(Course)
        .where(
            Course.user_id == user_id,
            Course.deleted_at.is_(None),
            Course.status == "active",
            Course.focus_until >= today,
        )
        .order_by(Course.updated_at.desc())
        .limit(1)
    )


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
        self.weights: dict[str, float] = concept_weights(latest_profile(db, self.active.id) if self.active else None)
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
    # A plan for one course is the learner's explicit choice: no interest rules and no focus apply.
    overview = course_id is None
    focus = focus_course(db, user.id, today) if overview else None
    has_interests = overview and any(c.kind == "interest" and c.status == "active" for c in courses.values())
    interest_share = user.interest_percent if has_interests else 0
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
    checks = check_first.results(db, user.id, [c.id for c in concepts if status_map[c.id] == "not_studied"])
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
        if courses[concept.course_id].kind == "interest":
            context = " Personal interest: no deadline, at your own pace."
        weight = sc.weights.get(str(concept.id), 1.0)
        if weight > 1.0:
            context += " Weighs more on past papers."
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
                + "with your assistant's explanation, then summarise it in your own words."
                + context
            )
            check = checks.get(concept.id)
            partly = check is not None and check["result"] == "yellow"
            if partly:  # Check first showed part of it: only the gaps, after what was not shown at all
                why = (
                    "Check first showed part of it: learn only the gaps from its feedback"
                    + (f" ({pages})" if pages else "")
                    + "; a summary in your own words is optional."
                    + context
                )
            elif check is not None and check["result"] == "red":
                why = "Not shown in Check first. " + why
            item = _item("Learn next", concept, courses, why, band, diff, target_name)
            item["_score"] = urgency * (0.93 if partly else 0.95)  # in material order, not by difficulty
            item["_order"] = order_keys.get(concept.id, ())
            if partly:
                item["estimated_minutes"] = max(6, item["estimated_minutes"] - 6)
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

    course_count = max(1, sum(1 for c in courses.values() if c.kind == "course" or not overview))
    capacities = [
        _capacity(db, user, courses[cid], sc, states, status_map, now, today, course_count, interest_share, focus)
        for cid, sc in scopes.items()
        if sc.active is not None
    ]
    # Exams that are not on track (only university courses count; a focused course is the learner's choice).
    behind = [c for c in capacities if c["status"] != "ok" and courses[c["course_id"]].kind == "course"]

    ranked = sorted(main, key=lambda i: (-round(i["_score"], 6), i.get("_order", ()), i["term"]))
    plan = _Fill(available)
    maintenance_budget = round(available * user.maintenance_percent / 100)
    for _, item in sorted(maintenance, key=lambda m: m[0]):
        if plan.maint_used and plan.maint_used + item["estimated_minutes"] > maintenance_budget:
            break
        plan.add(item)
        plan.maint_used += item["estimated_minutes"]
    maint_count = len(plan.items)

    def kind_of(item: dict[str, Any]) -> str:
        return "course" if not overview else courses[item["course_id"]].kind

    course_items = [i for i in ranked if kind_of(i) == "course" and (focus is None or i["course_id"] != focus.id)]
    interest_items = [i for i in ranked if kind_of(i) == "interest" and (focus is None or i["course_id"] != focus.id)]
    # A focus replaces the reserved share for its duration.
    reserved = round(available * interest_share / 100) if focus is None and interest_items else 0
    if focus is not None:
        focus_items = [i for i in ranked if i["course_id"] == focus.id]
        until = focus.focus_until.isoformat() if focus.focus_until else ""
        for i in focus_items:
            i["focus"] = True
            i["why_selected"] = f"Focus: you chose {focus.title} until {until}. " + i["why_selected"]
        added = plan.fill(focus_items, available, MAX_ITEMS - maint_count, first=True)
        course_slots = MAX_ITEMS - maint_count - (added if focus.kind == "course" else 0)
        plan.fill(course_items, available, course_slots, first=False)
        if not behind:
            plan.fill(interest_items, available, MAX_INTEREST_ITEMS - (added if focus.kind == "interest" else 0))
    else:
        plan.fill(interest_items, plan.used + reserved, MAX_INTEREST_ITEMS, first=reserved > 0)
        plan.fill(course_items, available, MAX_ITEMS - maint_count, first=True)
        if not behind:
            plan.fill(interest_items, available, MAX_INTEREST_ITEMS - plan.count(interest_items))

    items = plan.items
    ordered = (
        [i for i in items if i.get("focus")]
        + [i for i in items if not i.get("focus") and i["category"] != "Maintain" and kind_of(i) == "course"]
        + [i for i in items if not i.get("focus") and i["category"] != "Maintain" and kind_of(i) == "interest"]
        + [i for i in items if i["category"] == "Maintain"]
    )
    for i in ordered:
        i.pop("_score", None)
        i.pop("_order", None)
        i["study_status"] = status_map[i["concept_id"]]
        i["sections"] = sections_map.get(i["concept_id"], [])[:3]
    interest_minutes = sum(i["estimated_minutes"] for i in ordered if kind_of(i) == "interest" and not i.get("focus"))
    return {
        "policy_version": PLAN_POLICY,
        "generated_at": now,
        "available_minutes": available,
        "planned_minutes": plan.used,
        "maintenance_percent": user.maintenance_percent,
        "items": ordered,
        "targets": capacities,
        "message": None if ordered else EMPTY_MESSAGE,
        "note": NOTE,
        "interests": _interest_view(user, reserved, interest_minutes, behind, focus) if has_interests else None,
        "focus": _focus_view(focus, behind) if focus is not None else None,
    }


class _Fill:
    """Adds ranked items while time and slots last. The first item of a group may run over the time (a plan
    should never be empty only because one item is a few minutes too long)."""

    def __init__(self, available: int) -> None:
        self.available = available
        self.items: list[dict[str, Any]] = []
        self.used = 0
        self.maint_used = 0

    def add(self, item: dict[str, Any]) -> None:
        self.items.append(item)
        self.used += item["estimated_minutes"]

    def count(self, group: list[dict[str, Any]]) -> int:
        ids = {id(i) for i in group}
        return sum(1 for i in self.items if id(i) in ids)

    def fill(self, group: list[dict[str, Any]], end: int, slots: int, first: bool = False) -> int:
        added = 0
        taken = {id(i) for i in self.items}
        for item in group:
            if id(item) in taken:
                continue
            if added >= slots or ((added or not first) and self.used + item["estimated_minutes"] > end):
                break
            self.add(item)
            added += 1
        return added


def _names(behind: list[dict[str, Any]]) -> str:
    parts = [f"{c['target']} ({c['course_title']}) is {STATUS_WORDS[c['status']]}" for c in behind]
    return "; ".join(parts)


def _interest_view(
    user: User, reserved: int, planned: int, behind: list[dict[str, Any]], focus: Course | None
) -> dict[str, Any]:
    share = user.interest_percent
    if focus is not None:
        until = focus.focus_until.isoformat() if focus.focus_until else ""
        message = (
            f"Focus on {focus.title} until {until}: it comes first."
            if focus.kind == "interest"
            else f"Focus on {focus.title} until {until}: other interests get only time that is left."
        )
    elif share == 0 and behind:
        message = (
            f"University first: {_names(behind)}, so today's time goes to your courses. Your interests continue "
            "when every exam is on track."
        )
    elif share == 0 and planned:
        message = (
            f"University first: your exams are on track, so {planned} min after today's course work go to your "
            "interests."
        )
    elif share == 0:
        message = "University first: today's time is taken by your courses; interests get what is left on lighter days."
    else:
        message = f"{share} % of today ({reserved} min) is kept for your interests."
        if behind:
            message += f" {_names(behind)}: a smaller interest share in Settings gives your courses more time."
    return {
        "policy": "university_first" if share == 0 else "share",
        "percent": share,
        "reserved_minutes": reserved,
        "planned_minutes": planned,
        "message": message,
    }


def _focus_view(focus: Course, behind: list[dict[str, Any]]) -> dict[str, Any]:
    until = focus.focus_until.isoformat() if focus.focus_until else ""
    message = f"Focus on {focus.title} until {until}: it comes first; other work gets the time left."
    others = [c for c in behind if c["course_id"] != focus.id]
    if others:
        message += f" Meanwhile {_names(others)}."
    return {
        "course_id": focus.id,
        "course_title": focus.title,
        "kind": focus.kind,
        "until": until,
        "message": message,
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
        "course_kind": courses[concept.course_id].kind,
        "focus": False,
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
    interest_share: int = 0,
    focus: Course | None = None,
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
    # Days of the learner's focus on another course or interest are not counted for this one.
    focus_end = focus.focus_until if focus is not None and focus.id != course.id else None
    days_list = [today + timedelta(days=d) for d in range(days)]
    total = sum(minutes_available(db, user, day) for day in days_list if focus_end is None or day > focus_end)
    usable = round(total * (100 - user.maintenance_percent - interest_share) / 100 / max(1, course_count))
    status = "ok" if remaining <= 0.8 * usable else ("tight" if remaining <= usable else "at_risk")
    message = (
        f"About {remaining} min of work left for {sc.active.name}; about {usable} min of study time available "
        f"for this course until {sc.active.due_date.isoformat()} ({sc.days_left} days)."
    )
    if focus_end is not None and focus is not None and days_list and days_list[0] <= focus_end:
        message += f" Days of your focus on {focus.title} (until {focus_end.isoformat()}) are not counted."
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
