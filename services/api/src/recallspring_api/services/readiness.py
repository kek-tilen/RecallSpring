"""Exam readiness (``readiness-v1``, docs/05 -> Exam readiness): what is left before one kolokvij or exam.

Deterministic, no model calls. Every concept in the exam's scope gets one state:

* ``not_studied``   - not learned yet (learning first, ADR-006)
* ``weak``          - the last graded answer was 0-2 (No evidence / Fragile / Partial) or a lapse
* ``not_practised`` - studied or "known", but never answered, so there is no evidence yet
* ``developing``    - answered well (3-4), not yet spaced often enough to be reliable
* ``solid``         - the review band is "reliable" (three spaced successes)

Concepts are grouped by the material they come from (syllabus topic if set, else the first linked file, with its
page range), in the order the material is taught. The weakest concepts carry the gaps named in their last
feedback. Estimates from practice, not a validated score.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import ApiError, not_found
from ..models import (
    Assessment,
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
    SyllabusItem,
    User,
)
from . import mastery
from .learning import effective_status
from .reviews import effective_assessment
from .targets import concept_weights, latest_profile, scope_concepts

POLICY = "readiness-v1"
STATES = ("not_studied", "weak", "not_practised", "developing", "solid")
STATE_LABELS = {
    "not_studied": "Not studied yet",
    "weak": "Weak",
    "not_practised": "Studied, not practised",
    "developing": "Getting there",
    "solid": "Solid",
}
GRADE_LABELS = ("No evidence", "Fragile", "Partial", "Solid", "Transfer")
WEAK_GRADE = 2
MAX_WEAKEST = 5
NO_MATERIAL = "Not linked to material"
NOTE = "Estimated from your answers so far, not a prediction of your grade."
# Minutes still needed per state: learn (12) + first practice (6); practice; strengthen; one more review.
REMAINING = {"not_studied": 18, "weak": 10, "not_practised": 6, "developing": 6, "solid": 0}


def concept_state(status: str, state: ReviewState | None) -> str:
    if state is None:
        return "not_studied" if status == "not_studied" else "not_practised"
    grade = state.due_reason.get("grade")
    if (
        mastery.band(state) == "emerging"
        or mastery.evidence_code(state) == "lapse"
        or (isinstance(grade, int) and grade <= WEAK_GRADE)
    ):
        return "weak"
    return "solid" if mastery.band(state) == "reliable" else "developing"


def state_counts(db: Session, user: User, target: StudyTarget, now: datetime) -> dict[str, int]:
    """Concepts in the exam's scope per state (for the weekly review and lists); ``concepts`` is the total."""
    ids = list(scope_concepts(db, target))
    concepts = list(db.scalars(select(Concept).where(Concept.id.in_(ids), Concept.deleted_at.is_(None)))) if ids else []
    states = (
        {
            s.concept_id: s
            for s in db.scalars(
                select(ReviewState).where(
                    ReviewState.user_id == user.id, ReviewState.concept_id.in_([c.id for c in concepts])
                )
            )
        }
        if concepts
        else {}
    )
    counts = {s: 0 for s in STATES}
    for c in concepts:
        st = states.get(c.id)
        counts[concept_state(effective_status(c, st is not None), st)] += 1
    return {"concepts": len(concepts), **counts}


def _owned_target(db: Session, user: User, target_id: uuid.UUID) -> tuple[StudyTarget, Course]:
    target = db.get(StudyTarget, target_id)
    if target is None or target.user_id != user.id or target.deleted_at is not None:
        raise not_found("Exam")
    course = db.get(Course, target.course_id)
    if course is None or course.deleted_at is not None:
        raise not_found("Exam")
    return target, course


def _last_feedback(db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """The effective assessment of each concept's latest graded answer (diagnostic pre-tests excluded, as in the
    review schedule)."""
    if not concept_ids:
        return {}
    rows = db.execute(
        select(QuestionConcept.concept_id, Attempt, Assessment, Question.prompt)
        .join(Attempt, Attempt.question_id == QuestionConcept.question_id)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .join(Question, Question.id == Attempt.question_id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(QuestionConcept.concept_id.in_(concept_ids), Attempt.user_id == user_id)
        .where(or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"))
    ).all()
    per_attempt: dict[uuid.UUID, list[Assessment]] = defaultdict(list)
    meta: dict[uuid.UUID, tuple[Attempt, str, set[uuid.UUID]]] = {}
    for concept_id, attempt, assessment, prompt in rows:
        if assessment not in per_attempt[attempt.id]:
            per_attempt[attempt.id].append(assessment)
        meta.setdefault(attempt.id, (attempt, prompt, set()))[2].add(concept_id)
    latest: dict[uuid.UUID, tuple[datetime, dict[str, Any]]] = {}
    for attempt_id, assessments in per_attempt.items():
        eff = effective_assessment(assessments)
        if eff is None:
            continue
        attempt, prompt, concepts = meta[attempt_id]
        view = {
            "attempt_id": str(attempt.id),
            "answered_at": attempt.submitted_at.isoformat(),
            "grade": eff.grade,
            "status": eff.status,
            "question": prompt if len(prompt) <= 160 else prompt[:157] + "…",
            "gaps": [str(g) for g in eff.gaps[:3]],
            "remediation": eff.remediation,
        }
        for concept_id in concepts:
            if concept_id not in latest or latest[concept_id][0] < attempt.submitted_at:
                latest[concept_id] = (attempt.submitted_at, view)
    return {cid: v for cid, (_, v) in latest.items()}


def _material(db: Session, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Each concept's first linked section, in the order the material was added and taught."""
    if not concept_ids:
        return {}
    rows = db.execute(
        select(ConceptSource.concept_id, SourceSection, Source)
        .join(SourceSection, SourceSection.id == ConceptSource.section_id)
        .join(Source, Source.id == SourceSection.source_id)
        .where(ConceptSource.concept_id.in_(concept_ids), Source.deleted_at.is_(None))
        .order_by(Source.uploaded_at, Source.id, SourceSection.page, SourceSection.position)
    ).all()
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for concept_id, section, source in rows:
        entry = out.setdefault(
            concept_id,
            {
                "source_id": source.id,
                "filename": source.filename,
                "order": (0, source.uploaded_at.isoformat(), str(source.id), section.page or 0, section.position),
                "page": section.page,
                "citations": [],
            },
        )
        if len(entry["citations"]) < 2:
            entry["citations"].append(section.citation_label)
    return out


def _weights(db: Session, target: StudyTarget) -> dict[str, float]:
    return concept_weights(latest_profile(db, target.id))


def _pages(pages: list[int]) -> str | None:
    if not pages:
        return None
    lo, hi = min(pages), max(pages)
    return f"p. {lo}" if lo == hi else f"p. {lo}–{hi}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def readiness(db: Session, user: User, target_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    target, course = _owned_target(db, user, target_id)
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    days_left = (target.due_date - today).days
    ids = sorted(scope_concepts(db, target), key=str)
    concepts = list(db.scalars(select(Concept).where(Concept.id.in_(ids), Concept.deleted_at.is_(None)))) if ids else []
    ids = [c.id for c in concepts]
    states = (
        {
            s.concept_id: s
            for s in db.scalars(
                select(ReviewState).where(ReviewState.user_id == user.id, ReviewState.concept_id.in_(ids))
            )
        }
        if ids
        else {}
    )
    feedback = _last_feedback(db, user.id, ids)
    material = _material(db, ids)
    weights = _weights(db, target)
    topics = {
        t.id: t
        for t in db.scalars(
            select(SyllabusItem).where(
                SyllabusItem.id.in_({c.syllabus_item_id for c in concepts if c.syllabus_item_id}),
                SyllabusItem.deleted_at.is_(None),
            )
        )
    }

    counts = {s: 0 for s in STATES}
    due_count = 0
    remaining = 0
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for c in concepts:
        st = states.get(c.id)
        state = concept_state(effective_status(c, st is not None), st)
        counts[state] += 1
        due = st is not None and st.due_at <= now
        due_count += int(due)
        remaining += REMAINING[state] + (4 if due and state != "weak" else 0)
        diff = mastery.difficulty(c, st)
        mat = material.get(c.id)
        fb = feedback.get(c.id)
        row = {
            "id": str(c.id),
            "term": c.term,
            "state": state,
            "band": mastery.band(st),
            "last_grade": st.due_reason.get("grade") if st else None,
            "lapses": st.lapse_count if st else 0,
            "due": due,
            "next_review": st.due_at.isoformat() if st else None,
            "difficulty": diff.value,
            "exam_weight": weights.get(str(c.id)),
            "citations": [f"{mat['filename']}, {label}" for label in mat["citations"]] if mat else [],
            "feedback": fb,
            "_order": mat["order"] if mat else (1, "", "", 0, 0),
        }
        rows.append(row)
        topic = topics.get(c.syllabus_item_id) if c.syllabus_item_id else None
        if topic is not None:
            key: tuple[Any, ...] = (0, topic.position, str(topic.id))
            group = groups.setdefault(key, {"kind": "topic", "id": str(topic.id), "title": topic.title, "_pages": []})
        elif mat is not None:
            key = (1, mat["order"][1], mat["order"][2])
            group = groups.setdefault(
                key, {"kind": "source", "id": str(mat["source_id"]), "title": mat["filename"], "_pages": []}
            )
        else:
            key = (2,)
            group = groups.setdefault(key, {"kind": "none", "id": None, "title": NO_MATERIAL, "_pages": []})
        if mat is not None and mat["page"] is not None and group["kind"] == "source":
            group["_pages"].append(mat["page"])
        group.setdefault("concepts", []).append(row)

    group_views = []
    for key in sorted(groups):  # topics first, then files in the order they were added
        g = groups[key]
        members = sorted(g.pop("concepts"), key=lambda r: (r["_order"], r["term"]))
        g_counts = {s: 0 for s in STATES}
        for r in members:
            g_counts[r["state"]] += 1
        group_views.append(
            {
                **{k: v for k, v in g.items() if not k.startswith("_")},
                "pages": _pages(g["_pages"]),
                "counts": g_counts,
                "concepts": [{k: v for k, v in r.items() if not k.startswith("_")} for r in members],
            }
        )
    order = {r["id"]: i for i, r in enumerate(r for g in group_views for r in g["concepts"])}
    group_of = {r["id"]: g["title"] for g in group_views for r in g["concepts"]}

    weak = [r for r in rows if r["state"] == "weak"]
    weak.sort(
        key=lambda r: (
            r["last_grade"] if isinstance(r["last_grade"], int) else WEAK_GRADE,
            -r["lapses"],
            -(r["exam_weight"] or 1.0),
            -r["difficulty"],
            order[r["id"]],
        )
    )
    weakest = [
        {
            "id": r["id"],
            "term": r["term"],
            "group": group_of[r["id"]],
            "last_grade": r["last_grade"],
            "reason": _reason(r),
            "gaps": r["feedback"]["gaps"] if r["feedback"] else [],
            "remediation": r["feedback"]["remediation"] if r["feedback"] else None,
            "citations": r["citations"],
        }
        for r in weak[:MAX_WEAKEST]
    ]

    quizzes = list(
        db.scalars(
            select(Quiz).where(Quiz.target_id == target.id, Quiz.user_id == user.id).order_by(Quiz.created_at.desc())
        )
    )
    from .overview import quiz_summary  # overview imports many services; keep this module light to import

    simulations = [quiz_summary(db, q) for q in quizzes[:5]]
    recent_simulation = any(
        q.status == "submitted"
        and q.mode != "diagnostic"
        and q.submitted_at
        and now - q.submitted_at < timedelta(days=7)
        for q in quizzes
    )
    capacity = _capacity(db, user, target, now)
    total = len(rows)
    first_unstudied = next(
        (g["title"] for g in group_views if g["counts"]["not_studied"] and g["kind"] != "none"),
        None,
    )
    return {
        "policy_version": POLICY,
        "generated_at": now.isoformat(),
        "target": {
            "id": str(target.id),
            "name": target.name,
            "kind": target.kind,
            "status": target.status,
            "due_date": target.due_date.isoformat(),
            "days_left": days_left,
            "scope_description": target.scope_description,
            "course": {"id": str(course.id), "title": course.title, "color": course.color},
        },
        "summary": {
            "concepts": total,
            **counts,
            "due": due_count,
            "ready_percent": round(100 * (counts["solid"] + counts["developing"]) / total) if total else 0,
            "remaining_minutes": capacity["remaining_minutes"] if capacity else remaining,
        },
        "capacity": capacity,
        "groups": group_views,
        "weakest": weakest,
        "simulations": simulations,
        "next_steps": _next_steps(counts, due_count, weakest, days_left, total, first_unstudied, recent_simulation),
        "labels": STATE_LABELS,
        "note": NOTE,
    }


def compact(view: dict[str, Any]) -> dict[str, Any]:
    """The connector's version: per concept only what Claude needs to choose work; the weakest keep their gaps."""
    keep = ("id", "term", "state", "last_grade", "due", "exam_weight")
    return {
        **view,
        "groups": [{**g, "concepts": [{k: c[k] for k in keep} for c in g["concepts"]]} for g in view["groups"]],
    }


def for_course(db: Session, user: User, course_id: uuid.UUID, now: datetime) -> uuid.UUID:
    """The next exam of a course (the one the plan works toward)."""
    from .targets import active_target, live_targets

    course = db.get(Course, course_id)
    if course is None or course.user_id != user.id or course.deleted_at is not None:
        raise not_found("Course")
    target = active_target(live_targets(db, course.id), now.astimezone(ZoneInfo(user.timezone)).date())
    if target is None:
        raise ApiError(
            409, "no_upcoming_exam", "This course has no upcoming exam. Record one first (set_study_target)."
        )
    return target.id


def _reason(row: dict[str, Any]) -> str:
    grade = row["last_grade"]
    fb = row["feedback"]
    if isinstance(grade, int):
        text = f"Last answer {GRADE_LABELS[grade]} ({grade}/4)"
        if fb and fb["status"] == "provisional":
            text += ", provisional"
    else:
        text = "Last answers showed gaps"
    if row["lapses"] >= 2:
        text += f"; forgotten {row['lapses']} times"
    if (row["exam_weight"] or 1.0) >= 1.5:
        text += "; weighs more on your old papers"
    return text + "."


def _capacity(db: Session, user: User, target: StudyTarget, now: datetime) -> dict[str, Any] | None:
    """The plan's time check for this exam: only the next exam of each course has one."""
    from .planner import today_plan

    for cap in today_plan(db, user, now)["targets"]:
        if cap["target_id"] == target.id:
            return {
                "status": cap["status"],
                "remaining_minutes": cap["remaining_minutes"],
                "available_minutes": cap["available_minutes"],
                "message": cap["message"],
            }
    return None


def _next_steps(
    counts: dict[str, int],
    due: int,
    weakest: list[dict[str, Any]],
    days_left: int,
    total: int,
    first_unstudied: str | None,
    recent_simulation: bool,
) -> list[str]:
    if total == 0:
        return [
            "No concepts are in this exam's scope yet: import the material and ask your assistant to "
            "create concepts from it."
        ]
    steps = []
    days = max(1, days_left)
    if counts["not_studied"]:
        n = counts["not_studied"]
        start = f", starting with {first_unstudied}" if first_unstudied else ""
        steps.append(
            f"Learn the {_plural(n, 'concept')} not studied yet{start}: about {math.ceil(n / days)} a day. "
            "Start a study session for this course with your assistant."
        )
    if counts["weak"]:
        names = ", ".join(w["term"] for w in weakest[:3])
        more = " and more" if counts["weak"] > 3 else ""
        steps.append(
            f"Strengthen {_plural(counts['weak'], 'weak concept')}: {names}{more}. "
            "Ask your assistant to practise your weak points."
        )
    if counts["not_practised"]:
        steps.append(
            f"Answer one question each on {_plural(counts['not_practised'], 'studied concept')}, "
            "so RecallSpring can see how well you know them."
        )
    if due:
        steps.append(f"{_plural(due, 'review is', 'reviews are')} due: open Review.")
    studied_share = 1 - counts["not_studied"] / total
    if 0 <= days_left <= 10 and studied_share >= 0.5 and not recent_simulation:
        steps.append("Do a timed simulation in the style of your old paper, then let your assistant grade it.")
    if not steps:
        steps.append("Everything in scope looks solid. Keep up the reviews until the exam.")
    return steps
