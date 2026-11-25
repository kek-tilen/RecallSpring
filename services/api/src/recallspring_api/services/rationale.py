"""Why this plan (``rationale-v1``, ADR-013 §2): for one kolokvij or exam, what the old papers show, how much of it is
covered, why today's work is in this order, whether it fits, and what the basis cannot say.

Deterministic, no model calls: everything comes from the exam profile, readiness (``readiness-v1``) and today's plan
(``plan-v2``). An assistant may explain it in its own words but must not add claims it does not contain.

Coverage is weighted by each topic's share of the points on the papers (or its given share; topics without one count
as an average topic). A topic counts as *studied* for the part of its concepts that is studied, *ready* for the part
that is developing or solid, and *solid* for the part that is solid. Estimates from practice, never a grade.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Attempt,
    Concept,
    ConceptSource,
    Course,
    Question,
    QuestionConcept,
    Quiz,
    ReviewState,
    Source,
    SourceSection,
    StudyTarget,
    TargetProfile,
    User,
)
from . import check_first, readiness
from .learning import effective_status
from .planner import PRIORITY_RULES, today_plan
from .targets import latest_profile, profile_view

POLICY = "rationale-v1"
MAX_LISTED = 20


def _states(db: Session, user: User, ids: set[uuid.UUID], now: datetime) -> dict[str, dict[str, Any]]:
    """State of concepts outside the exam's scope that a topic names (readiness covers the ones inside)."""
    if not ids:
        return {}
    concepts = list(
        db.scalars(select(Concept).where(Concept.id.in_(ids), Concept.user_id == user.id, Concept.deleted_at.is_(None)))
    )
    states = {
        s.concept_id: s
        for s in db.scalars(
            select(ReviewState).where(
                ReviewState.user_id == user.id, ReviewState.concept_id.in_([c.id for c in concepts])
            )
        )
    }
    out = {}
    for c in concepts:
        st = states.get(c.id)
        out[str(c.id)] = {
            "id": str(c.id),
            "term": c.term,
            "state": readiness.concept_state(effective_status(c, st is not None), st),
            "due": st is not None and st.due_at <= now,
        }
    return out


def _profile_topics(profile: TargetProfile | None) -> list[dict[str, Any]]:
    """The profile's topics in one shape. A v1 topic weight without a concept is kept as ``unmapped`` (it had no
    effect on the plan)."""
    if profile is None:
        return []
    if profile.version >= 2:
        return [
            {**t, "unmapped": False, "concept_ids": [str(c) for c in t.get("concept_ids") or []]}
            for t in profile.topics
            if isinstance(t, dict)
        ]
    out = []
    for w in profile.topic_weights:
        if not isinstance(w, dict):
            continue
        cid = w.get("concept_id")
        out.append(
            {
                "label": str(w.get("label") or ""),
                "concept_ids": [str(cid)] if cid else [],
                "not_in_material": False,
                "unmapped": not cid,
                "points": None,
                "share": None,
                "where": None,
                "papers": [],
                "style_only": False,
                "weight": w.get("weight", 1.0),
            }
        )
    return out


def _web_only(db: Session, concept_ids: set[str]) -> set[str]:
    """Concepts whose linked material is all from the web (ADR-013 §5)."""
    if not concept_ids:
        return set()
    rows = db.execute(
        select(ConceptSource.concept_id, Source.origin)
        .join(SourceSection, SourceSection.id == ConceptSource.section_id)
        .join(Source, Source.id == SourceSection.source_id)
        .where(ConceptSource.concept_id.in_([uuid.UUID(c) for c in concept_ids]), Source.deleted_at.is_(None))
    ).all()
    origins: dict[str, set[str]] = {}
    for cid, origin in rows:
        origins.setdefault(str(cid), set()).add(origin)
    return {cid for cid, found in origins.items() if found == {"web"}}


def _status(t: dict[str, Any], concepts: list[dict[str, Any]]) -> str:
    if t["not_in_material"]:
        return "not_in_material"
    if t["unmapped"] or not concepts:
        return "unmapped"
    states = [c["state"] for c in concepts]
    if all(s == "solid" for s in states):
        return "solid"
    if all(s == "not_studied" for s in states):
        return "not_studied"
    if any(s == "weak" for s in states):
        return "weak"
    return "in_progress"


def _fraction(concepts: list[dict[str, Any]], states: tuple[str, ...]) -> float:
    return sum(1 for c in concepts if c["state"] in states) / len(concepts) if concepts else 0.0


def _coverage(topics: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not topics:
        return None
    known = [t["share"] for t in topics if isinstance(t.get("share"), int | float)]
    fallback = sum(known) / len(known) if known else 1.0
    raw = [t["share"] if isinstance(t.get("share"), int | float) else fallback for t in topics]
    total = sum(raw) or 1.0
    weights = [r / total for r in raw]
    basis = "points" if any(t.get("points") for t in topics) else "share" if known else "topics"

    def pct(key: str) -> int:
        return round(100 * sum(w * t["_" + key] for w, t in zip(weights, topics, strict=True)))

    outside = sum(w for w, t in zip(weights, topics, strict=True) if t["status"] in ("not_in_material", "unmapped"))
    return {
        "basis": basis,
        "studied_percent": pct("studied"),
        "ready_percent": pct("ready"),
        "solid_percent": pct("solid"),
        "not_in_material_percent": round(100 * outside),
    }


def _practised_bloom(db: Session, user: User, concept_ids: list[str]) -> dict[str, float]:
    """Share of the questions answered on this exam's concepts at each Bloom level (Check first excluded)."""
    if not concept_ids:
        return {}
    rows = db.execute(
        select(Question.bloom_level, func.count(func.distinct(Attempt.question_id)))
        .join(Attempt, Attempt.question_id == Question.id)
        .join(QuestionConcept, QuestionConcept.question_id == Question.id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(
            QuestionConcept.concept_id.in_([uuid.UUID(c) for c in concept_ids]),
            Attempt.user_id == user.id,
            Attempt.kind == "answer",
            or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"),
        )
        .group_by(Question.bloom_level)
    ).all()
    total = sum(n for _, n in rows)
    return {str(level): round(n / total, 2) for level, n in sorted(rows)} if total else {}


def _listed(names: list[str]) -> str:
    shown = ", ".join(names[:MAX_LISTED])
    return shown + (f" and {len(names) - MAX_LISTED} more" if len(names) > MAX_LISTED else "")


def rationale(db: Session, user: User, target_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    view = readiness.readiness(db, user, target_id, now)  # 404 for someone else's or a deleted exam
    target = db.get(StudyTarget, target_id)
    course = db.get(Course, target.course_id) if target else None
    assert target is not None and course is not None
    profile = latest_profile(db, target.id)
    in_scope = {c["id"]: c for g in view["groups"] for c in g["concepts"]}
    raw_topics = _profile_topics(profile)
    named = {cid for t in raw_topics for cid in t["concept_ids"]}
    outside = _states(db, user, {uuid.UUID(c) for c in named - set(in_scope)}, now)
    web_only = _web_only(db, named)

    topics = []
    for t in raw_topics:
        concepts = []
        for cid in t["concept_ids"]:
            row = in_scope.get(cid) or outside.get(cid)
            if row is not None:
                concepts.append(
                    {
                        "id": cid,
                        "term": row["term"],
                        "state": row["state"],
                        "due": row["due"],
                        "in_scope": cid in in_scope,
                    }
                )
        counts = {s: 0 for s in readiness.STATES}
        for c in concepts:
            counts[c["state"]] += 1
        status = _status(t, concepts)
        topics.append(
            {
                "label": t["label"],
                "points": t.get("points"),
                "share": t.get("share"),
                "where": t.get("where"),
                "papers": t.get("papers") or [],
                "weight": t.get("weight", 1.0),
                "not_in_material": t["not_in_material"],
                "unmapped": t["unmapped"],
                # added from the web at the learner's request: every concept of the topic is backed by web sources
                "from_web": bool(concepts) and all(c["id"] in web_only for c in concepts),
                # only on papers used for their style (e.g. another kolokvij): listed, but it does not weigh
                "style_only": bool(t.get("style_only")),
                "status": status,
                "concepts": concepts,
                "counts": counts,
                "_studied": _fraction(concepts, ("weak", "not_practised", "developing", "solid")),
                "_ready": _fraction(concepts, ("developing", "solid")),
                "_solid": _fraction(concepts, ("solid",)),
            }
        )
    topics.sort(key=lambda t: (t["style_only"], -(t["share"] if isinstance(t["share"], int | float) else -1.0)))
    counted = [t for t in topics if not t["style_only"]]  # topics of papers used only for their style do not count
    coverage = _coverage(counted)
    for t in topics:
        for key in ("_studied", "_ready", "_solid"):
            t.pop(key)

    # today's plan as the learner sees it on Home, this course's part, each item tied to its topics on the paper
    plan = today_plan(db, user, now)
    by_concept: dict[str, list[dict[str, Any]]] = {}
    for t in counted:
        for c in t["concepts"]:
            by_concept.setdefault(c["id"], []).append(t)
    today = []
    for item in plan["items"]:
        if item["course_id"] != course.id:
            continue
        on_paper = by_concept.get(str(item["concept_id"]), [])
        today.append(
            {
                "concept_id": str(item["concept_id"]),
                "term": item["term"],
                "category": item["category"],
                "minutes": item["estimated_minutes"],
                "topics": [{"label": t["label"], "points": t["points"], "share": t["share"]} for t in on_paper],
                "why": item["why_selected"],
            }
        )
    others = len(plan["items"]) - len(today)

    mix = profile.bloom_mix if profile else {}
    limit = check_first.ceiling(course)
    above = check_first._share_above(mix, limit)
    bloom = {
        "paper": mix,
        "practised": _practised_bloom(db, user, list(in_scope)),
        "practice_limit": limit,
        "paper_above_limit": above,
    }

    on_paper = {c["id"] for t in counted for c in t["concepts"]}
    not_on_paper = [c["term"] for c in in_scope.values() if c["id"] not in on_paper] if counted else []
    limits = _limits(profile, topics, not_on_paper, above, limit, len(in_scope))

    return {
        "policy_version": POLICY,
        "generated_at": now.isoformat(),
        "target": view["target"],
        "profile": profile_view(db, profile),
        "topics": topics,
        "coverage": coverage,
        "bloom": bloom,
        "today": {
            "items": today,
            "minutes": sum(i["minutes"] for i in today),
            "other_courses_items": others,
            "note": None
            if today
            else "Today's plan has no work for this course yet."
            if not others
            else ("Today's plan has work for other courses only: they need the time more today."),
        },
        "order_rules": list(PRIORITY_RULES),
        "fit": {"days_left": view["target"]["days_left"], "summary": view["summary"], "capacity": view["capacity"]},
        "not_on_paper": {"count": len(not_on_paper), "terms": not_on_paper[:MAX_LISTED]},
        "limits": limits,
        "note": readiness.NOTE,
    }


def _paper_name(paper: dict[str, Any]) -> str:
    name = str(paper.get("label") or "a paper")
    return f"{name} ({paper['exam']})" if paper.get("exam") else name


def _limits(
    profile: TargetProfile | None,
    topics: list[dict[str, Any]],
    not_on_paper: list[str],
    above: float,
    limit: int,
    concepts: int,
) -> list[dict[str, str]]:
    """What the basis of the plan cannot say, in the order a learner should hear it."""
    out: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        out.append({"code": code, "message": message})

    if concepts == 0:
        add("no_concepts", "No concepts are in this exam's scope yet, so there is nothing to plan or cover.")
    if profile is None:
        add(
            "no_profile",
            "No old paper has been analysed: the plan follows the order of the material and your answers only, not "
            "the style or weight of the exam's questions.",
        )
        return out
    if profile.version < 2:
        unmapped = [t["label"] for t in topics if t["unmapped"]]
        add(
            "before_confirmation",
            "The analysis was made before analyses were checked and confirmed. Ask your assistant to analyse the paper "
            "again."
            + (
                f" These topics were not linked to the material and had no effect: {_listed(unmapped)}."
                if unmapped
                else ""
            ),
        )
    elif profile.confirmed_at is None:
        add("unconfirmed", "You have not confirmed the analysis yet: check it against the paper.")
    if profile.version >= 2:
        papers = [p for p in profile.papers if isinstance(p, dict)]
        if not papers:
            add("no_paper_listed", "The analysis names no old paper, so it cannot be checked against one.")
        elif len(papers) == 1:
            add("one_paper", "Based on one old paper: the next one may weigh topics differently.")
        missing = [p.get("label") or "a paper" for p in papers if not p.get("source_id")]
        if missing:
            add(
                "no_copy",
                f"RecallSpring has no copy of {_listed([str(m) for m in missing])}: add it to the course's material to "
                "check the analysis against it.",
            )
        if profile.unreadable:
            add("unreadable", f"Your assistant could not read: {_listed([str(u) for u in profile.unreadable])}.")
        style = [_paper_name(p) for p in papers if p.get("use") == "style"]
        if style:
            add(
                "style_only",
                f"Used only for the kind of questions, not for its topics: {_listed(style)}. Its topics are listed "
                "but do not change the order of your plan.",
            )
    topics = [t for t in topics if not t.get("style_only")]
    web = [t["label"] for t in topics if t.get("from_web")]
    if web:
        add(
            "from_web",
            f"Added from the web at your request, not from your course material: {_listed(web)}. Your professor may "
            "expect it differently.",
        )
    not_in = [t for t in topics if t["not_in_material"]]
    if not_in:
        names = [t["label"] + (f" ({t['points']:g} points)" if t["points"] else "") for t in not_in]
        add(
            "not_in_material",
            f"On the paper but not in your material: {_listed(names)}. The plan cannot cover them from your material.",
        )
    outside = [t["label"] for t in topics if t["concepts"] and not any(c["in_scope"] for c in t["concepts"])]
    if outside:
        add("outside_scope", f"On the paper but outside this exam's scope as you described it: {_listed(outside)}.")
    if topics and not any(t["points"] or t["share"] for t in topics):
        add("no_points", "The paper shows no points per topic, so every topic counts the same.")
    if not_on_paper:
        add(
            "not_on_paper",
            f"{len(not_on_paper)} concepts in this exam's scope were not on the old papers. They stay in the plan with "
            "an average weight; topics that weigh more on the papers can come before them.",
        )
    if above > 0:
        add(
            "above_limit",
            f"About {round(above * 100)} % of the paper's questions are above your practice limit (level {limit}); "
            "you do not practise those levels.",
        )
    return out
