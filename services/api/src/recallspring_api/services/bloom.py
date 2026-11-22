"""Which Bloom level to practise next for a concept (owner decision 2026-11-22), worked out from graded answers
without any model call.

Practice ramps 3 Apply → 4 Analyze → 5 Evaluate: a level counts as reached with a final Solid (3) or Transfer (4)
grade from an assistant or the learner's correction. A 0-1 answer steps back one level (never below 3); provisional
and self-assessed grades never move the ramp up. Once level 5 is reached, practice is mixed: RecallSpring suggests
the level among 3-5 that was practised least recently, so earlier levels keep coming back. An exam profile's Bloom
mix, when the course has one, takes precedence (the assistants' instructions say so); this is the default without it.
Levels 1-2 (recall and the check questions after a summary) belong to learning, not to the ramp.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assessment, Attempt, Question, QuestionConcept
from .reviews import effective_assessment

RAMP = (3, 4, 5)
LABEL = {3: "Apply", 4: "Analyze", 5: "Evaluate"}


def _suggest(graded: list[tuple[datetime, int, Assessment]]) -> dict[str, Any]:
    """graded: (answered_at, bloom_level, effective assessment) of practice answers (level 3+), any order."""
    if not graded:
        return {"next_level": 3, "phase": "ramp", "highest_solid": None, "why": "No practice yet: start with 3 Apply."}
    graded.sort(key=lambda g: g[0])
    solid = [
        lvl
        for _, lvl, a in graded
        if a.grade is not None and a.grade >= 3 and a.status == "final" and a.evaluator_kind != "self"
    ]
    highest = min(max(solid), 5) if solid else None
    _, last_level, last = graded[-1]
    if last.grade is not None and last.grade <= 1:
        level = max(3, min(last_level, 5) - 1)
        return {
            "next_level": level,
            "phase": "consolidate",
            "highest_solid": highest,
            "why": f"The last answer at {last_level} was weak ({last.grade}/4): practise {level} {LABEL[level]} again.",
        }
    if highest is None or highest < 5:
        level = 3 if highest is None else highest + 1
        reached = "Nothing solid yet" if highest is None else f"{highest} {LABEL[highest]} is solid"
        return {
            "next_level": level,
            "phase": "ramp",
            "highest_solid": highest,
            "why": f"{reached}: next {level} {LABEL[level]}.",
        }
    last_at = {lvl: max((at for at, lv, _ in graded if min(lv, 5) == lvl), default=None) for lvl in RAMP}
    level = min(RAMP, key=lambda lvl: (last_at[lvl] is not None, last_at[lvl] or datetime.min))
    return {
        "next_level": level,
        "phase": "mixed",
        "highest_solid": highest,
        "why": f"All levels up to 5 are solid: mix them; {level} {LABEL[level]} was practised least recently.",
    }


def suggestions(db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """The next practice level for each concept, from all graded practice answers (level 3+) linked to it."""
    if not concept_ids:
        return {}
    rows = db.execute(
        select(QuestionConcept.concept_id, Attempt, Question.bloom_level, Assessment)
        .join(Attempt, Attempt.question_id == QuestionConcept.question_id)
        .join(Question, Question.id == QuestionConcept.question_id)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .where(QuestionConcept.concept_id.in_(concept_ids), Attempt.user_id == user_id, Question.bloom_level >= 3)
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
    return {cid: _suggest(graded.get(cid, [])) for cid in concept_ids}
