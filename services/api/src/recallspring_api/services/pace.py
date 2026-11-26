"""Review estimates from the learner's own pace (ADR-014 §3, answer timing).

RecallSpring's answer forms report how long a question was open and visible, without pauses over 5 minutes
(``attempts.answer_seconds``; chat answers have none). After ``MIN_TIMED`` timed answers of a depth, its estimate is
the median of the last ``WINDOW`` plus ``FEEDBACK_MINUTES`` for the feedback, rounded up; until then the defaults
apply. A quick review is one question at Bloom 1-2 and a standard one a question at Bloom 3 or higher; a relearn
item (feedback and another try until the criterion) keeps the default ratio to a standard review, 2.5. Check first
answers do not count. Like focus sessions this records time spent, never learning or mastery. No model calls.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Attempt, Question, Quiz, User

DEFAULT_MINUTES = {"quick": 3, "standard": 4, "relearn": 10}
MIN_TIMED = 10
WINDOW = 30
FEEDBACK_MINUTES = 2
RELEARN_PER_STANDARD = DEFAULT_MINUTES["relearn"] / DEFAULT_MINUTES["standard"]
MAX_MINUTES = 60


def depth_of(bloom_level: int) -> str:
    return "quick" if bloom_level <= 2 else "standard"


def estimates(db: Session, user: User) -> dict[str, dict[str, Any]]:
    """Minutes per review depth: ``{depth: {minutes, timed_answers, source}}``, source ``default`` or ``your_pace``."""
    rows = db.execute(
        select(Attempt.answer_seconds, Question.bloom_level)
        .join(Question, Question.id == Attempt.question_id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(
            Attempt.user_id == user.id,
            Attempt.answer_seconds.is_not(None),
            Attempt.kind == "answer",
            or_(Attempt.quiz_id.is_(None), Quiz.mode != "diagnostic"),
        )
        .order_by(Attempt.submitted_at.desc(), Attempt.id)
        .limit(WINDOW * 20)
    ).all()
    timed: dict[str, list[int]] = {"quick": [], "standard": []}
    for seconds, level in rows:
        bucket = timed[depth_of(level)]
        if len(bucket) < WINDOW:
            bucket.append(seconds)
    out: dict[str, dict[str, Any]] = {}
    for depth, values in timed.items():
        if len(values) >= MIN_TIMED:
            minutes = min(MAX_MINUTES, math.ceil(statistics.median(values) / 60 + FEEDBACK_MINUTES))
            out[depth] = {"minutes": minutes, "timed_answers": len(values), "source": "your_pace"}
        else:
            out[depth] = {"minutes": DEFAULT_MINUTES[depth], "timed_answers": len(values), "source": "default"}
    standard = out["standard"]
    out["relearn"] = {
        "minutes": (
            min(2 * MAX_MINUTES, math.ceil(RELEARN_PER_STANDARD * standard["minutes"]))
            if standard["source"] == "your_pace"
            else DEFAULT_MINUTES["relearn"]
        ),
        "timed_answers": standard["timed_answers"],
        "source": standard["source"],
    }
    return out
