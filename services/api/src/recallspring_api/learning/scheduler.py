"""Deterministic review scheduler, policy ``rs-interval-v3`` (docs/05-LEARNING-ENGINE.md, ADR-003, ADR-014).

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
* v2 (2026-11-22): a concept shown in Check first (``KnownFromCheck``) without any practice yet starts at step
  ``CHECK_KNOWN_STEP`` with its first review after ``CHECK_KNOWN_DAYS`` days (rare reviews for what is already
  known). With earlier practice evidence it changes nothing. v1 schedules are otherwise unchanged.
* v3 (2026-11-26, ADR-014): an exam layer, applied by ``apply_exam_layer`` to the *final* replayed state only, so
  history is never rewritten and the ladder keeps its own date (``policy_due_at``). An answer on a date the layer
  brought forward is early for the ladder, so the layer can add reviews but never lengthens an interval.
  - Exam cap: for the nearest upcoming exam after the last review whose scope holds the concept, when the ladder's
    date is after the day before the exam (E-1) and more than ``exam_fraction(T) * INTERVALS[step]`` days lie between
    the last review and E, the review moves to E-1. T is the target for the exam morning: the learner's choice per
    target ("Before this exam", ``BEFORE_EXAM``), else the goal's default (0.95 exam only, 0.90 long term); the
    ladder's interval stands in for FSRS stability on the FSRS-6 forgetting curve. For a long-term target the cap
    applies at most once per concept and exam: when the last answer followed a cap for that exam, it is not capped
    again (it matters once a long-term target has a higher T, rollout step 2).
  - Relearning: a concept whose last certain grade is 2 or lower, answered at most 7 days before an exam, is due
    again the next day (never on the exam day itself, never later than the ladder's date).
  - A deferral after the last answer wins over both: it is the learner's explicit choice.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

POLICY_VERSION = "rs-interval-v3"
INTERVALS: tuple[int, ...] = (1, 3, 7, 14, 30, 60, 120)
MAX_STEP = len(INTERVALS) - 1
CHECK_KNOWN_STEP = 3  # the next success moves on to 30 days
CHECK_KNOWN_DAYS = 21
# ADR-014: the target for recall on the exam morning by goal, and the learner's choice per target (§4).
EXAM_TARGETS = {"exam_only": 0.95, "long_term": 0.90}
BEFORE_EXAM = {"regular": 0.90, "extra_review": 0.95, "intense": 0.97}
RELEARN_DAYS = 7  # weak concepts answered this close to an exam come back the next day
EARLY_TAIL_DAYS = 3  # a review brought forward to E-1 may be offered from E-3 when E-1 is full (planner)
FSRS6_W20 = 0.1542  # FSRS-6 default decay; R(t, S) = (1 + F * t / S) ** -w20, R(S, S) = 0.90
OVERLAY_CODES = ("exam_cap", "relearn")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

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
class KnownFromCheck:
    """The learner showed the concept in Check first (a diagnostic quiz)."""

    occurred_at: datetime
    quiz_id: uuid.UUID


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
    # The reason code of the last graded evidence; a deferral moves the date but must not hide it.
    evidence_code: str | None = None
    # v3 exam layer: the ladder's own date and the exam that moved it.
    policy_due_at: datetime | None = None
    exam: str | None = None
    exam_date: date | None = None
    exam_target: float | None = None

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "code": self.code,
            "evidence_code": self.evidence_code or self.code,
            "message": self.message,
            "interval_days": self.interval_days,
            "grade": self.grade,
            "attempt_id": str(self.attempt_id) if self.attempt_id else None,
            "policy_version": POLICY_VERSION,
        }
        if self.policy_due_at is not None and self.exam_date is not None:
            out |= {
                "policy_due_at": self.policy_due_at.isoformat(),
                "exam": self.exam,
                "exam_date": self.exam_date.isoformat(),
                "exam_target": self.exam_target,
            }
        return out


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
    # The grade of the last certain evidence (None when there is none, e.g. only Check first); not stored.
    last_certain_grade: int | None = None


@dataclass(frozen=True)
class ExamDate:
    """An upcoming exam (study target) whose scope holds the concept."""

    name: str
    day: date  # the exam's local date
    goal: str  # exam_only | long_term
    target: float  # recall target for the exam morning, T


def exam_target(goal: str, retention: float | None) -> float:
    """T for the exam morning: the learner's choice for the target, else the goal's default."""
    return float(retention) if retention is not None else EXAM_TARGETS.get(goal, 0.90)


def before_exam_choice(target: float) -> str:
    """The "Before this exam" choice closest to a stored target (phase B may store values between them)."""
    return min(BEFORE_EXAM, key=lambda k: (abs(BEFORE_EXAM[k] - target), BEFORE_EXAM[k]))


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduler requires timezone-aware datetimes")
    return value.astimezone(UTC)


def local_day_start(now: datetime, tz: ZoneInfo, days_ahead: int) -> datetime:
    """UTC instant of local midnight ``days_ahead`` calendar days after ``now``'s local date."""
    local_date: date = _require_aware(now).astimezone(tz).date() + timedelta(days=days_ahead)
    return datetime.combine(local_date, time(0, 0), tzinfo=tz).astimezone(UTC)


def grade_text(grade: int | None) -> str:
    """A grade as shown everywhere: its meaning, then the number, e.g. "Solid (3/4)"."""
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
            last_certain_grade=ev.grade if ev.certain else None,
        )

    early = at < state.due_at
    base = replace(
        state,
        last_review_at=at,
        evidence_count=state.evidence_count + 1,
        last_certain_grade=ev.grade if ev.certain else state.last_certain_grade,
    )

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
                    f"Answered {grade_text(grade)} before the review was due; the current interval is kept.",
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
                f"Last review was {grade_text(grade)}; next review in {days} days.",
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
                f"Last review was {grade_text(grade)}; reviewing again in {days} days.",
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
            "lapse", f"Last review was {grade_text(grade)}; reviewing again the next day.", 1, grade, ev.attempt_id
        ),
    )


def apply_known_from_check(state: ReviewSchedule | None, ev: KnownFromCheck, tz: ZoneInfo) -> ReviewSchedule:
    if state is not None:
        return state
    at = _require_aware(ev.occurred_at)
    return ReviewSchedule(
        step=CHECK_KNOWN_STEP,
        due_at=local_day_start(at, tz, CHECK_KNOWN_DAYS),
        last_review_at=at,
        consecutive_successes=1,
        lapse_count=0,
        evidence_count=1,
        reason=DueReason(
            "known_from_check",
            f"You showed this in Check first; a light check-up in {CHECK_KNOWN_DAYS} days.",
            CHECK_KNOWN_DAYS,
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
        reason=DueReason(
            "deferred",
            "Review deferred by you.",
            None,
            state.reason.grade,
            state.reason.attempt_id,
            state.reason.evidence_code or state.reason.code,
        ),
    )


def exam_fraction(target: float) -> float:
    """The share of FSRS-6 stability after which predicted recall falls to ``target`` (0.40 for 0.95, 1.0 for 0.90)."""
    decay = -1 / FSRS6_W20
    return (target**decay - 1) / (0.9**decay - 1)


def day_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(UTC)


def _moved(state: ReviewSchedule, day: date, code: str, message: str, exam: ExamDate, tz: ZoneInfo) -> ReviewSchedule:
    last_day = state.last_review_at.astimezone(tz).date()
    return replace(
        state,
        due_at=_local_midnight(day, tz),
        reason=DueReason(
            code,
            message,
            (day - last_day).days,
            state.reason.grade,
            state.reason.attempt_id,
            state.reason.evidence_code or state.reason.code,
            policy_due_at=state.due_at,
            exam=exam.name,
            exam_date=exam.day,
            exam_target=exam.target,
        ),
    )


def _capped_for(
    answered: ReviewSchedule | None, last_day: date, exam: ExamDate, exams: tuple[ExamDate, ...], tz: ZoneInfo
) -> bool:
    """Whether the last answer was the review brought forward for this exam: the state it was given in had the cap
    for this exam, and it came at most ``EARLY_TAIL_DAYS`` before the exam (a practice answer weeks earlier is not
    that review)."""
    if (exam.day - last_day).days > EARLY_TAIL_DAYS:
        return False
    before = apply_exam_layer(answered, exams, tz)
    return (
        before is not None
        and before.reason.code == "exam_cap"
        and before.reason.exam == exam.name
        and before.reason.exam_date == exam.day
    )


def apply_exam_layer(
    state: ReviewSchedule | None,
    exams: Iterable[ExamDate],
    tz: ZoneInfo,
    answered: ReviewSchedule | None = None,
) -> ReviewSchedule | None:
    """v3 exam layer (ADR-014) on the final replayed state. ``exams`` are the upcoming exams whose scope holds the
    concept; only those after the day of the last review count. ``answered`` is the state before the last answer:
    for a long-term target the cap applies at most once per concept and exam."""
    if state is None or state.reason.code == "deferred":
        return state
    exams = tuple(exams)
    last_day = state.last_review_at.astimezone(tz).date()
    ahead = sorted((e for e in exams if e.day > last_day), key=lambda e: (e.day, e.name))
    if not ahead:
        return state
    policy_day = state.due_at.astimezone(tz).date()
    nearest = ahead[0]
    days_left = (nearest.day - last_day).days
    weak = state.last_certain_grade is not None and state.last_certain_grade <= 2
    if weak and 2 <= days_left <= RELEARN_DAYS:
        next_day = last_day + timedelta(days=1)
        if next_day < policy_day:
            return _moved(
                state,
                next_day,
                "relearn",
                f"Not solid yet, {days_left} days before {nearest.name} on {day_label(nearest.day)}: another try "
                "with feedback the next day.",
                nearest,
                tz,
            )
        return state
    interval = INTERVALS[state.step]
    for exam in ahead:
        cap_day = exam.day - timedelta(days=1)
        elapsed = (exam.day - last_day).days
        if exam.goal == "long_term" and _capped_for(answered, last_day, exam, exams, tz):
            continue  # long term: one review brought forward per exam, not a contracting run
        if policy_day > cap_day > last_day and elapsed > exam_fraction(exam.target) * interval:
            return _moved(
                state,
                cap_day,
                "exam_cap",
                f"Last review before {exam.name} on {day_label(exam.day)}; brought forward from "
                f"{day_label(policy_day)}.",
                exam,
                tz,
            )
    return state


def schedule(
    events: Iterable[Evidence | KnownFromCheck | Deferral], tz: ZoneInfo, exams: Iterable[ExamDate] = ()
) -> ReviewSchedule | None:
    """The ladder's replay with the v3 exam layer on top."""
    state, answered = _replay(events, tz)
    return apply_exam_layer(state, exams, tz, answered)


def replay(events: Iterable[Evidence | KnownFromCheck | Deferral], tz: ZoneInfo) -> ReviewSchedule | None:
    """Replay evidence and deferrals in chronological order (ties: evidence before deferral, then id)."""
    return _replay(events, tz)[0]


def _replay(
    events: Iterable[Evidence | KnownFromCheck | Deferral], tz: ZoneInfo
) -> tuple[ReviewSchedule | None, ReviewSchedule | None]:
    """The final state and the state the last evidence was answered in."""

    def sort_key(e: Evidence | KnownFromCheck | Deferral) -> tuple[datetime, int, str]:
        if isinstance(e, Evidence):
            return (_require_aware(e.occurred_at), 0, str(e.attempt_id))
        if isinstance(e, KnownFromCheck):
            return (_require_aware(e.occurred_at), 0, str(e.quiz_id))
        return (_require_aware(e.occurred_at), 1, _require_aware(e.until).isoformat())

    state: ReviewSchedule | None = None
    answered: ReviewSchedule | None = None
    for event in sorted(events, key=sort_key):
        if isinstance(event, Evidence):
            answered = state
            state = apply_evidence(state, event, tz)
        elif isinstance(event, KnownFromCheck):
            state = apply_known_from_check(state, event, tz)
        else:
            state = apply_deferral(state, event)
    return state, answered
