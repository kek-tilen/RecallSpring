"""Which simulation answers count for the review schedule, the Bloom ramp and the last feedback.

Diagnostic checks (ADR-006) and same-day retakes (2026-11-26, migration 0036) are graded and shown, but
never drive the schedule: a check only shows what is known, and a retake on the same day answers questions whose
keys and feedback the learner saw a few hours earlier. Use with ``outerjoin(Quiz, Quiz.id == Attempt.quiz_id)``.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_

from ..models import Quiz


def counts_for_schedule() -> ColumnElement[bool]:
    return or_(Quiz.id.is_(None), and_(Quiz.mode != "diagnostic", Quiz.same_day_practice.is_(False)))
