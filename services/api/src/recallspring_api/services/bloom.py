"""Which Bloom level to practise next for a concept (owner decision 2026-11-22), worked out from graded answers
without any model call.

Practice ramps 3 Apply → 4 Analyze → 5 Evaluate (→ 6 Create only when the practice limit is 6): a level counts as
reached with a final Solid (3) or Transfer (4)
grade from an assistant or the learner's correction. A 0-1 answer steps back one level (never below 3); provisional
and self-assessed grades never move the ramp up. Once the top level is reached, practice is mixed: RecallSpring
suggests the level that was practised least recently, so earlier levels keep coming back. An exam profile's Bloom
mix, when the course has one, takes precedence (the assistants' instructions say so); this is the default without it.
The practice limit (``courses.bloom_ceiling``, 2-6; services/check_first.py ``ceiling``) caps both: the ramp then
ends, and mixes, at the limit. Without one it is 5, or 6 while an upcoming exam paper asks for Create (owner notes
2026-11-26).
Levels 1-2 (recall and the check questions after a summary) belong to learning, not to the ramp, and Check first
(diagnostic) answers never move it.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..learning.scheduler import grade_text
from ..models import Assessment, Attempt, Concept, Question, QuestionConcept, Quiz
from .reviews import effective_assessment

RAMP = (3, 4, 5, 6)
LABEL = {2: "Understand", 3: "Apply", 4: "Analyze", 5: "Evaluate", 6: "Create"}
MAX_LEVEL = 6
DEFAULT_LEVEL = 5  # the limit when the learner set none and no exam paper asks for 6 Create
CREATE = 6
# Owner notes 2026-11-26: at 6 Create recommend a more capable model.
CREATE_TIP = (
    "Bloom 6 Create asks you to design, plan or produce something of your own, and judging it well is hard: use the "
    "most capable model your assistant offers (a thinking or reasoning model) for these questions and their grading."
)


def _solid(a: Assessment) -> bool:
    """A level is reached with a final Solid or Transfer grade that is not the learner's own self-assessment."""
    return a.grade is not None and a.grade >= 3 and a.status == "final" and a.evaluator_kind != "self"


def _suggest(graded: list[tuple[datetime, int, Assessment]], ceiling: int = DEFAULT_LEVEL) -> dict[str, Any]:
    """graded: (answered_at, bloom_level, effective assessment) of practice answers (level 3+), any order.
    ceiling: the practice limit (2-6); levels above it are never suggested."""
    if ceiling < RAMP[0]:
        return {
            "next_level": ceiling,
            "phase": "limited",
            "highest_solid": None,
            "why": f"Your practice limit is {ceiling} {LABEL[ceiling]}: practise at that level.",
        }
    ramp = tuple(lvl for lvl in RAMP if lvl <= ceiling)
    top = ramp[-1]
    limit = f" (your limit is {top} {LABEL[top]})" if top < DEFAULT_LEVEL else ""
    if not graded:
        return {"next_level": 3, "phase": "ramp", "highest_solid": None, "why": "No practice yet: start with 3 Apply."}
    graded.sort(key=lambda g: g[0])
    solid = [lvl for _, lvl, a in graded if _solid(a)]
    highest = min(max(solid), top) if solid else None
    _, last_level, last = graded[-1]
    if last.grade is not None and last.grade <= 1:
        level = max(3, min(last_level, top) - 1)
        return {
            "next_level": level,
            "phase": "consolidate",
            "highest_solid": highest,
            "why": f"The last answer at {last_level} was weak, {grade_text(last.grade)}: practise {level} "
            f"{LABEL[level]} again.",
        }
    if highest is None or highest < top:
        level = 3 if highest is None else highest + 1
        reached = "Nothing solid yet" if highest is None else f"{highest} {LABEL[highest]} is solid"
        return {
            "next_level": level,
            "phase": "ramp",
            "highest_solid": highest,
            "why": f"{reached}: next {level} {LABEL[level]}{limit}.",
        }
    last_at = {lvl: max((at for at, lv, _ in graded if min(lv, top) == lvl), default=None) for lvl in ramp}
    level = min(ramp, key=lambda lvl: (last_at[lvl] is not None, last_at[lvl] or datetime.min))
    return {
        "next_level": level,
        "phase": "mixed",
        "highest_solid": highest,
        "why": f"All levels up to {top} are solid{limit}: mix them; {level} {LABEL[level]} was practised least "
        "recently.",
    }


def suggestions(
    db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID], ceiling: int = DEFAULT_LEVEL
) -> dict[uuid.UUID, dict[str, Any]]:
    """The next practice level for each concept, from all graded practice answers (level 3+) linked to it."""
    if not concept_ids:
        return {}
    rows = db.execute(
        select(QuestionConcept.concept_id, Attempt, Question.bloom_level, Assessment)
        .join(Attempt, Attempt.question_id == QuestionConcept.question_id)
        .join(Question, Question.id == QuestionConcept.question_id)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(QuestionConcept.concept_id.in_(concept_ids), Attempt.user_id == user_id, Question.bloom_level >= 3)
        # A Check first answer shows the current level; it never moves the ramp (owner decision 2026-11-22).
        .where(or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"))
    ).all()
    per_attempt: dict[tuple[uuid.UUID, uuid.UUID], tuple[Attempt, int, list[Assessment]]] = {}
    for concept_id, attempt, level, assessment in rows:
        key = (concept_id, attempt.id)
        per_attempt.setdefault(key, (attempt, level, []))[2].append(assessment)
    graded: dict[uuid.UUID, list[tuple[datetime, int, Assessment]]] = defaultdict(list)
    for (concept_id, _), (attempt, level, assessments) in per_attempt.items():
        current = effective_assessment(assessments)
        if current is not None and current.grade is not None:
            graded[concept_id].append((attempt.submitted_at, level, current))
    return {cid: _suggest(graded.get(cid, []), ceiling) for cid in concept_ids}


# ---------------------------------------------------------------- harder questions while learning (owner 2026-11-25)

LEARNING_LEVELS = 2  # check questions after a summary and recall are Bloom 1-2
OFFER_STREAK = 2  # two Solid-or-better learning answers in a row


def harder_offer(db: Session, user_id: uuid.UUID, attempt: Attempt, ceiling: int) -> dict[str, Any] | None:
    """When the learner's last two learning answers in a course (Bloom 1-2, not Check first) were both Solid or
    Transfer, offer once to go on with harder questions (3 Apply) for the concepts of those answers. Offered exactly
    when the streak reaches two, so a declined offer does not come back with every further good answer; a weaker
    answer starts a new streak. Never above the learner's practice limit. Deterministic, no model call."""
    question = db.get(Question, attempt.question_id)
    if question is None or question.bloom_level > LEARNING_LEVELS or ceiling < RAMP[0]:
        return None
    rows = db.execute(
        select(Attempt, Question)
        .join(Question, Question.id == Attempt.question_id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(
            Attempt.user_id == user_id,
            Attempt.kind == "answer",
            Question.course_id == question.course_id,
            Question.bloom_level <= LEARNING_LEVELS,
            or_(Quiz.id.is_(None), Quiz.mode != "diagnostic"),
        )
        .order_by(Attempt.submitted_at.desc(), Attempt.id.desc())
        .limit(OFFER_STREAK + 1)
    ).all()
    if not rows or rows[0][0].id != attempt.id:
        return None

    def solid(a: Attempt) -> bool:
        current = effective_assessment(
            list(db.scalars(select(Assessment).where(Assessment.attempt_id == a.id).order_by(Assessment.created_at)))
        )
        return current is not None and _solid(current)

    streak = rows[:OFFER_STREAK]
    if len(streak) < OFFER_STREAK or not all(solid(a) for a, _ in streak):
        return None
    if len(rows) > OFFER_STREAK and solid(rows[OFFER_STREAK][0]):
        return None  # the streak is longer: the offer was made at two
    concept_ids = list(
        dict.fromkeys(
            db.scalars(
                select(QuestionConcept.concept_id)
                .where(QuestionConcept.question_id.in_([q.id for _, q in streak]))
                .order_by(QuestionConcept.concept_id)
            )
        )
    )
    terms = [c.term for c in db.scalars(select(Concept).where(Concept.id.in_(concept_ids), Concept.user_id == user_id))]
    return {
        "level": RAMP[0],
        "level_name": LABEL[RAMP[0]],
        "concept_ids": [str(c) for c in concept_ids],
        "terms": sorted(terms),
        "say": "Two Solid answers in a row while learning. Offer once, in one short sentence, harder questions on "
        'this part (Bloom 3 Apply), e.g. "You are doing well: want a harder question on this?". On yes ask at '
        "level 3 for these concepts; on no go on as planned and do not offer again in this chunk. If the next "
        "chapter may be familiar too, you may mention Check first once.",
    }
