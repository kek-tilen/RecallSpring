"""Deterministic review scheduler, policy ``rs-interval-v1`` (docs/05-LEARNING-ENGINE.md, ADR-003).

Pure functions only: no database, no clock, no model calls. The review state of a concept is always the
result of replaying its evidence (effective assessments of attempts) and explicit deferrals in order, so
corrections and re-evaluations recompute the schedule exactly.

Rules
-----
* Due dates are the *start of a local calendar day* in the learner's timezone, stored in UTC.
* First evidence for a concept: step 0, due the next local day.
* Evidence is *certain* when status is ``final``, a grade exists and confidence is not ``low``.
  Uncertain evidence never promotes or lengthens: step unchanged, short follow-up the next local day.
* Certain grade >= 3 at or after the due time: step + 1 (max 6), due after ``INTERVALS[step]`` days.
  Before the due time ("early"): the interval is kept (no promotion from massed practice).
* Certain grade 2: step - 1 (min 0), due after ``min(3, INTERVALS[step])`` days (never later than an
  existing earlier due date when early).
* Certain grade <= 1: step 0, due the next local day; a lapse is counted after a success streak.
* Deferral: due becomes ``max(due, until)``; the step is unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

POLICY_VERSION = "rs-interval-v1"
INTERVALS: tuple[int, ...] = (1, 3, 7, 14, 30, 60, 120)
MAX_STEP = len(INTERVALS) - 1

Status = Literal["final", "provisional", "ungraded"]
Confidence = Literal["low", "medium", "high"]

GRADE_LABELS = {0: "No evidence", 1: "Fragile", 2: "Partial", 3: "Solid", 4: "Transfer"}


@dataclass(frozen=True)
class Evidence:
    occurred_at: datetime
    attempt_id: uuid.UUID
    grade: int | None
    status: Status
    confidence: Confidence

    @property
    def certain(self) -> bool:
        return self.status == "final" and self.grade is not None and self.confidence != "low"


@dataclass(frozen=True)
class Deferral:
    occurred_at: datetime
    until: datetime


@dataclass(frozen=True)
class DueReason:
    code: str
    message: str
    interval_days: int | None = None
    grade: int | None = None
    attempt_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "interval_days": self.interval_days,
            "grade": self.grade,
            "attempt_id": str(self.attempt_id) if self.attempt_id else None,
            "policy_version": POLICY_VERSION,
        }


@dataclass(frozen=True)
class ReviewSchedule:
    step: int
    due_at: datetime
    last_review_at: datetime
    consecutive_successes: int
    lapse_count: int
    evidence_count: int
    reason: DueReason
    policy_version: str = POLICY_VERSION


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduler requires timezone-aware datetimes")
    return value.astimezone(UTC)


def local_day_start(now: datetime, tz: ZoneInfo, days_ahead: int) -> datetime:
    """UTC instant of local midnight ``days_ahead`` calendar days after ``now``'s local date."""
    local_date: date = _require_aware(now).astimezone(tz).date() + timedelta(days=days_ahead)
    return datetime.combine(local_date, time(0, 0), tzinfo=tz).astimezone(UTC)


def _grade_text(grade: int | None) -> str:
    return f"{GRADE_LABELS[grade]} ({grade}/4)" if grade is not None else "ungraded"


def apply_evidence(state: ReviewSchedule | None, ev: Evidence, tz: ZoneInfo) -> ReviewSchedule:
    at = _require_aware(ev.occurred_at)
    if state is None:
        reason = (
            DueReason(
                "first_evidence", "First practice recorded; first review is the next day.", 1, ev.grade, ev.attempt_id
            )
            if ev.certain
            else DueReason(
                "uncertain_followup",
                "First answer could not be graded with confidence; short follow-up the next day.",
                1,
                ev.grade,
                ev.attempt_id,
            )
        )
        return ReviewSchedule(
            step=0,
            due_at=local_day_start(at, tz, 1),
            last_review_at=at,
            consecutive_successes=1 if ev.certain and (ev.grade or 0) >= 3 else 0,
            lapse_count=0,
            evidence_count=1,
            reason=reason,
        )

    early = at < state.due_at
    base = replace(state, last_review_at=at, evidence_count=state.evidence_count + 1)

    if not ev.certain:
        follow_up = local_day_start(at, tz, 1)
        due = min(state.due_at, follow_up) if early else follow_up
        return replace(
            base,
            due_at=due,
            reason=DueReason(
                "uncertain_followup",
                f"Last answer was {ev.status} with {ev.confidence} confidence; the interval is not lengthened "
                "and a short follow-up is scheduled.",
                1,
                ev.grade,
                ev.attempt_id,
            ),
        )

    grade = ev.grade
    assert grade is not None  # guaranteed by Evidence.certain

    if grade >= 3:
        if early:
            return replace(
                base,
                reason=DueReason(
                    "early_no_promotion",
                    f"Answered {_grade_text(grade)} before the review was due; the current interval is kept.",
                    None,
                    grade,
                    ev.attempt_id,
                ),
            )
        step = min(state.step + 1, MAX_STEP)
        days = INTERVALS[step]
        return replace(
            base,
            step=step,
            due_at=local_day_start(at, tz, days),
            consecutive_successes=state.consecutive_successes + 1,
            reason=DueReason(
                "promoted",
                f"Last review was {_grade_text(grade)}; next review in {days} days.",
                days,
                grade,
                ev.attempt_id,
            ),
        )

    if grade == 2:
        step = max(state.step - 1, 0)
        days = min(3, INTERVALS[step])
        candidate = local_day_start(at, tz, days)
        return replace(
            base,
            step=step,
            due_at=min(state.due_at, candidate) if early else candidate,
            consecutive_successes=0,
            reason=DueReason(
                "partial",
                f"Last review was {_grade_text(grade)}; reviewing again in {days} days.",
                days,
                grade,
                ev.attempt_id,
            ),
        )

    lapsed = state.consecutive_successes > 0
    return replace(
        base,
        step=0,
        due_at=local_day_start(at, tz, 1),
        consecutive_successes=0,
        lapse_count=state.lapse_count + (1 if lapsed else 0),
        reason=DueReason(
            "lapse", f"Last review was {_grade_text(grade)}; reviewing again the next day.", 1, grade, ev.attempt_id
        ),
    )


def apply_deferral(state: ReviewSchedule | None, d: Deferral) -> ReviewSchedule | None:
    if state is None:
        return None
    until = _require_aware(d.until)
    if until <= state.due_at:
        return state
    return replace(
        state,
        due_at=until,
        reason=DueReason("deferred", "Review deferred by you.", None, state.reason.grade, state.reason.attempt_id),
    )


def replay(events: Iterable[Evidence | Deferral], tz: ZoneInfo) -> ReviewSchedule | None:
    """Replay evidence and deferrals in chronological order (ties: evidence before deferral, then id)."""

    def sort_key(e: Evidence | Deferral) -> tuple[datetime, int, str]:
        if isinstance(e, Evidence):
            return (_require_aware(e.occurred_at), 0, str(e.attempt_id))
        return (_require_aware(e.occurred_at), 1, _require_aware(e.until).isoformat())

    state: ReviewSchedule | None = None
    for event in sorted(events, key=sort_key):
        state = apply_evidence(state, event, tz) if isinstance(event, Evidence) else apply_deferral(state, event)
    return state
