"""Check first and the practice limit (owner decisions 2026-11-22), worked out without any model call.

Check first is a short diagnostic quiz (``quizzes.mode = 'diagnostic'``) for a chapter, or "a bit of everything" for
the active midterm or exam (the whole course without one). The learner chooses it; assistants offer it gently.
Each concept gets a result from its latest submitted check:

* an open answer graded final 3-4 (not low confidence) is one full green; each correct closed answer (multiple
  choice, true/false) is half a green, so two make one and an odd count rounds down; an answer marked
  "I'm guessing" counts nothing, even when correct;
* **green** (at least one full green): already known; it moves to the background and gets rare reviews (the first
  after ``CHECK_KNOWN_DAYS``, see the scheduler);
* **yellow** (half a green, a Partial open answer or an unsure grade): learn only the gaps, own summary optional;
* **red** (nothing correct): learn it first, as usual;
* **pending** while an open answer waits for its grade.

A check asks each concept at its current level: Understand (2) before it is studied, otherwise the next level of
its practice ramp (services/bloom.py), never above the practice limit. Check answers never change the ramp.

The practice limit (``courses.bloom_ceiling``, 2-6) caps practice, simulations and checks. Without one it is 5
Evaluate, or 6 Create while an upcoming exam's profile has Bloom 6 questions (2026-11-26). When an exam
profile of the course has questions above the limit, RecallSpring says so until the learner confirms the limit on
purpose. At 6 it also recommends a more capable model.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import (
    Assessment,
    Attempt,
    Concept,
    ConceptSource,
    Course,
    Question,
    QuestionConcept,
    Quiz,
    QuizItem,
    Source,
    SourceSection,
    SyllabusItem,
)
from . import bloom, targets
from .reviews import effective_assessment

OPEN_UNITS = 2  # an open answer that is Solid or better: one full green
CLOSED_UNITS = 1  # a correct closed answer: half a green
GREEN_UNITS = 2
CHAPTER_MAX = 12  # concepts in one chapter check
EVERYTHING_MAX = 15  # concepts in "a bit of everything"
LEVEL_LABEL = bloom.LABEL
RESULT_LABEL = {"green": "Already know it", "yellow": "Partly", "red": "Not yet", "pending": "Waiting for a grade"}
_CLOSED_TYPE = re.compile(r"multiple|choice|mcq|true|false|yes/no|izbir|obkro|drži|da/ne", re.IGNORECASE)

HOW = (
    "Check first is the learner's choice: offer it once, briefly and gently (a chapter, or a bit of everything for "
    "the target), never insist. Create it with create_quiz mode='diagnostic' for the concept_ids of a chapter (or "
    "of 'everything'): ask each concept at its check.level; 'open' means one open question, 'closed' two closed "
    "ones (multiple choice or true/false), as check.item says. One correct closed answer is only half known and a "
    "guess counts nothing. After grading: green = known (keep it in the background), yellow = explain only the gaps "
    "from the feedback, then open_summary_form (the learner may write or skip), red = learn it first as usual."
)


# ---------------------------------------------------------------- practice limit


def _share_at(profile_mix: dict[str, Any], level: int) -> float:
    total = 0.0
    for key, share in (profile_mix or {}).items():
        try:
            if int(str(key).strip()) == level:
                total += float(share)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def exam_asks_create(db: Session, course: Course, today: date | None = None) -> dict[str, Any] | None:
    """The first upcoming exam whose profile has Bloom 6 Create questions, or None."""
    today = today or clock.now().date()
    for target in targets.live_targets(db, course.id):
        if target.status != "upcoming" or target.due_date < today:
            continue
        profile = targets.latest_profile(db, target.id)
        if profile is not None and _share_at(profile.bloom_mix, bloom.CREATE) > 0:
            return {"target_id": str(target.id), "target": target.name, "share": _share_at(profile.bloom_mix, 6)}
    return None


def ceiling(db: Session, course: Course, today: date | None = None) -> int:
    """The learner's limit, else 5 Evaluate, or 6 Create while an upcoming exam paper asks for it."""
    if course.bloom_ceiling:
        return course.bloom_ceiling
    return bloom.CREATE if exam_asks_create(db, course, today) else bloom.DEFAULT_LEVEL


def _share_above(profile_mix: dict[str, Any], level: int) -> float:
    total = 0.0
    for key, share in (profile_mix or {}).items():
        try:
            if int(str(key).strip()) > level:
                total += float(share)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def practice_limit(db: Session, course: Course, today: date) -> dict[str, Any]:
    """The limit, and whether an upcoming exam's profile asks for more (until the learner confirms the limit)."""
    level = ceiling(db, course, today)
    create = None if course.bloom_ceiling else exam_asks_create(db, course, today)
    above = None
    for target in targets.live_targets(db, course.id):
        if target.status != "upcoming" or target.due_date < today:
            continue
        profile = targets.latest_profile(db, target.id)
        if profile is None:
            continue
        share = _share_above(profile.bloom_mix, level)
        if share > 0:
            confirmed = course.bloom_ceiling_confirmed_at is not None and course.bloom_ceiling_confirmed_at >= (
                profile.created_at
            )
            above = {"target_id": str(target.id), "target": target.name, "share": share, "confirmed": confirmed}
            break
    warning = None
    if above and not above["confirmed"]:
        warning = (
            f"About {round(above['share'] * 100)} % of the questions on the {above['target']} paper are above "
            f"{level} {LEVEL_LABEL[level]}. With this limit you will not practise them."
        )
    return {
        "level": level,
        "label": LEVEL_LABEL[level],
        "set_by_learner": course.bloom_ceiling is not None,
        # automatic: why it is 6 (an exam paper with Create questions), else 5
        "automatic": None
        if course.bloom_ceiling
        else (
            f"6 Create, because the {create['target']} paper has Create questions."
            if create
            else "5 Evaluate; 6 Create only when you choose it or an exam paper asks for it."
        ),
        "exam_profile_above": above,
        "warning": warning,
        "model_tip": bloom.CREATE_TIP if level >= bloom.CREATE else None,
    }


def require_within_limit(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, levels: list[int]) -> None:
    course = db.get(Course, course_id)
    if course is None or course.user_id != user_id:
        return
    limit = ceiling(db, course)
    too_high = sorted({lvl for lvl in levels if lvl > max(limit, 2)})
    if too_high:
        raise ApiError(
            409,
            "above_practice_limit",
            f"The learner practises this course up to Bloom {limit} {LEVEL_LABEL[limit]} (their choice in "
            f"RecallSpring). Ask at level {limit} or lower.",
            {"limit": limit, "levels": too_high},
        )


# ---------------------------------------------------------------- results


def _item_units(question: Question, attempt: Attempt | None, eff: Assessment | None) -> tuple[str, int]:
    """(state, units) for one answered check item; state is 'pending', 'partial' or 'scored'."""
    if attempt is None or attempt.kind != "answer":
        return "scored", 0
    if question.question_type == "mcq":
        right = eff is not None and (eff.grade or 0) >= 3
        return "scored", CLOSED_UNITS if right and not attempt.guessing else 0
    if eff is None:
        return "pending", 0
    certain = eff.status == "final" and eff.grade is not None and eff.confidence != "low"
    if certain and (eff.grade or 0) >= 3:
        return "scored", OPEN_UNITS
    if eff.grade is None or eff.grade >= 2:  # Partial, or unsure / ungraded: shown, but not confirmed
        return "partial", 0
    return "scored", 0


def _verdict(units: int, partial: bool, pending: bool, guesses: int) -> tuple[str, str]:
    greens = units // GREEN_UNITS
    if greens:
        return "green", "Shown in Check first."
    if pending:
        return "pending", "An open answer is waiting for its grade."
    if units or partial:
        why = "One correct closed answer counts as half." if units else "Partly shown; some points were missing."
        return "yellow", why
    return "red", "Marked as a guess, so it does not count." if guesses else "Not shown in Check first."


def results(
    db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID], quiz_id: uuid.UUID | None = None
) -> dict[uuid.UUID, dict[str, Any]]:
    """Each concept's result from its latest submitted check, or from one check (``quiz_id``); concepts never
    checked are left out."""
    if not concept_ids:
        return {}
    db.flush()  # the session does not autoflush; a just-submitted check must count
    rows = db.execute(
        select(QuestionConcept.concept_id, Question, Quiz)
        .join(Question, Question.id == QuestionConcept.question_id)
        .join(QuizItem, QuizItem.question_id == Question.id)
        .join(Quiz, Quiz.id == QuizItem.quiz_id)
        .where(
            QuestionConcept.concept_id.in_(concept_ids),
            Quiz.user_id == user_id,
            Quiz.mode == "diagnostic",
            Quiz.status == "submitted",
            *([Quiz.id == quiz_id] if quiz_id is not None else []),
        )
    ).all()
    if not rows:
        return {}
    latest: dict[uuid.UUID, Quiz] = {}
    for concept_id, _, quiz in rows:
        if concept_id not in latest or (quiz.submitted_at, str(quiz.id)) > (
            latest[concept_id].submitted_at,
            str(latest[concept_id].id),
        ):
            latest[concept_id] = quiz
    quiz_ids = {q.id for q in latest.values()}
    attempts = {(a.quiz_id, a.question_id): a for a in db.scalars(select(Attempt).where(Attempt.quiz_id.in_(quiz_ids)))}
    grades: dict[uuid.UUID, list[Assessment]] = defaultdict(list)
    if attempts:
        ids = [a.id for a in attempts.values()]
        for assessment in db.scalars(select(Assessment).where(Assessment.attempt_id.in_(ids))):
            grades[assessment.attempt_id].append(assessment)
    tally: dict[uuid.UUID, dict[str, Any]] = {}
    for concept_id, question, quiz in rows:
        if latest[concept_id].id != quiz.id:
            continue
        attempt = attempts.get((quiz.id, question.id))
        eff = effective_assessment(grades[attempt.id]) if attempt else None
        state, units = _item_units(question, attempt, eff)
        t = tally.setdefault(concept_id, {"units": 0, "partial": False, "pending": False, "guesses": 0})
        t["units"] += units
        t["partial"] |= state == "partial"
        t["pending"] |= state == "pending"
        # only a closed guess counts nothing; an open answer marked unsure is graded normally (2026-11-26)
        t["guesses"] += 1 if attempt is not None and attempt.guessing and question.question_type == "mcq" else 0
    out = {}
    for concept_id, t in tally.items():
        result, why = _verdict(t["units"], t["partial"], t["pending"], t["guesses"])
        quiz = latest[concept_id]
        out[concept_id] = {
            "result": result,
            "label": RESULT_LABEL[result],
            "why": why,
            "greens": t["units"] // GREEN_UNITS,
            "checked_at": quiz.submitted_at.isoformat() if quiz.submitted_at else None,
            "quiz_id": str(quiz.id),
        }
    return out


# ---------------------------------------------------------------- what to check


def _closed_share(db: Session, course: Course, today: date) -> float:
    """Share of closed questions on the upcoming exam paper, if a profile says so; otherwise open questions."""
    for target in targets.live_targets(db, course.id):
        if target.status != "upcoming" or target.due_date < today:
            continue
        profile = targets.latest_profile(db, target.id)
        if profile and profile.item_types:
            return min(1.0, sum(float(t.get("share", 0)) for t in profile.item_types if _CLOSED_TYPE.search(t["type"])))
    return 0.0


def chapters(db: Session, course: Course, concepts: list[Concept]) -> list[dict[str, Any]]:
    """Concepts grouped by chapter: the course's topics in order, then (for concepts without one) the first
    material file they come from, in upload order."""
    topic_rows = list(
        db.scalars(
            select(SyllabusItem)
            .where(SyllabusItem.course_id == course.id, SyllabusItem.deleted_at.is_(None))
            .order_by(SyllabusItem.position, SyllabusItem.title)
        )
    )
    first_source: dict[uuid.UUID, Source] = {}
    ids = [c.id for c in concepts if c.syllabus_item_id is None]
    if ids:
        for concept_id, source in db.execute(
            select(ConceptSource.concept_id, Source)
            .join(SourceSection, SourceSection.id == ConceptSource.section_id)
            .join(Source, Source.id == SourceSection.source_id)
            .where(ConceptSource.concept_id.in_(ids), Source.deleted_at.is_(None))
            .order_by(Source.uploaded_at, Source.id, SourceSection.page, SourceSection.position)
        ):
            first_source.setdefault(concept_id, source)
    groups: dict[str, dict[str, Any]] = {}
    for t in topic_rows:
        groups[f"topic:{t.id}"] = {"key": f"topic:{t.id}", "title": t.title, "concept_ids": []}
    sources_in_order: list[Source] = []
    for c in concepts:
        if c.syllabus_item_id and f"topic:{c.syllabus_item_id}" in groups:
            key = f"topic:{c.syllabus_item_id}"
        elif c.id in first_source:
            source = first_source[c.id]
            key = f"source:{source.id}"
            if key not in groups:
                sources_in_order.append(source)
                groups[key] = {"key": key, "title": source.filename, "concept_ids": []}
        else:
            key = "other"
            groups.setdefault(key, {"key": key, "title": "Other concepts", "concept_ids": []})
        groups[key]["concept_ids"].append(c.id)
    sources_in_order.sort(key=lambda s: (s.uploaded_at, str(s.id)))
    ordered = [groups[f"topic:{t.id}"] for t in topic_rows]
    ordered += [groups[f"source:{s.id}"] for s in sources_in_order]
    ordered += [groups["other"]] if "other" in groups else []
    return [g for g in ordered if g["concept_ids"]]


def _pick(ids: list[uuid.UUID], checks: dict[uuid.UUID, dict[str, Any]], n: int) -> list[uuid.UUID]:
    """Concepts not checked yet first, then the ones whose last check was not green, then the oldest checks."""

    def key(cid: uuid.UUID) -> tuple[int, str]:
        r = checks.get(cid)
        if r is None:
            return (0, "")
        return (1 if r["result"] != "green" else 2, r["checked_at"] or "")

    return sorted(ids, key=key)[:n]


def plan(
    db: Session,
    course: Course,
    concepts: list[Concept],
    status: dict[uuid.UUID, str],
    practice: dict[uuid.UUID, dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    """Per concept: its last check, the level and kind of question to check it with; per chapter and for
    "a bit of everything": which concepts to check (adapted to the number of concepts and the exam style)."""
    limit = ceiling(db, course, today)
    checks = results(db, course.user_id, [c.id for c in concepts])
    level = {c.id: min(2 if status[c.id] == "not_studied" else practice[c.id]["next_level"], limit) for c in concepts}
    share = _closed_share(db, course, today)
    by_level = sorted(concepts, key=lambda c: (level[c.id], c.term))
    closed = {c.id for c in by_level[: round(share * len(concepts))]}
    per_concept = {
        c.id: {
            "last": checks.get(c.id),
            "level": level[c.id],
            "item": "closed" if c.id in closed else "open",
        }
        for c in concepts
    }
    groups = chapters(db, course, concepts)
    chapter_views = []
    for g in groups:
        counts = {"green": 0, "yellow": 0, "red": 0, "pending": 0, "unchecked": 0}
        for cid in g["concept_ids"]:
            counts[checks[cid]["result"] if cid in checks else "unchecked"] += 1
        pick = _pick(g["concept_ids"], checks, CHAPTER_MAX)
        chapter_views.append(
            {
                "key": g["key"],
                "title": g["title"],
                "concept_ids": [str(c) for c in g["concept_ids"]],
                "check_concept_ids": [str(c) for c in pick],
                "counts": counts,
            }
        )
    active = targets.active_target(targets.live_targets(db, course.id), today)
    in_scope = targets.scope_concepts(db, active) if active else None
    pool = [g for g in groups if in_scope is None or any(c in in_scope for c in g["concept_ids"])]
    pool_ids = [[c for c in g["concept_ids"] if in_scope is None or c in in_scope] for g in pool]
    total = sum(len(ids) for ids in pool_ids)
    budget = min(EVERYTHING_MAX, total)
    everything: list[uuid.UUID] = []
    if total:
        # Every chapter gets at least one concept, the rest in proportion to its size.
        quotas = [max(1, round(budget * len(ids) / total)) for ids in pool_ids]
        while sum(quotas) > budget and max(quotas) > 1:
            quotas[quotas.index(max(quotas))] -= 1
        for ids, quota in zip(pool_ids, quotas, strict=True):
            everything += _pick(ids, checks, quota)
    return {
        "how": HOW,
        "concepts": per_concept,
        "chapters": chapter_views,
        "everything": {
            "scope": active.name if active else "the whole course",
            "target_id": str(active.id) if active else None,
            "concept_ids": [str(c) for c in everything],
            "of": total,
        },
        "closed_share": share,
    }
