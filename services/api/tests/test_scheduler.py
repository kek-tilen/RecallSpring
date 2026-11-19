"""Deterministic scheduler policy rs-interval-v1 (pure unit tests, no database)."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from recallspring_api.learning.scheduler import (
    INTERVALS,
    Deferral,
    Evidence,
    ReviewSchedule,
    apply_deferral,
    apply_evidence,
    local_day_start,
    replay,
)

TZ = ZoneInfo("Europe/Ljubljana")
T0 = datetime(2026, 11, 19, 16, 0, tzinfo=UTC)  # 17:00 local (CET)


def ev(at: datetime, grade: int | None, status: str = "final", confidence: str = "high") -> Evidence:
    return Evidence(at, uuid.uuid4(), grade, status, confidence)  # type: ignore[arg-type]


def on_time(state: ReviewSchedule) -> datetime:
    """09:00 local on the day the review is due."""
    return state.due_at + timedelta(hours=9)


def test_first_evidence_is_due_at_next_local_midnight() -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    assert s.step == 0
    assert s.due_at == datetime(2026, 11, 19, 23, 0, tzinfo=UTC)  # 2026-11-20 00:00 CET
    assert s.reason.code == "first_evidence"
    assert s.consecutive_successes == 1


def test_promotion_ladder_when_reviewed_on_time_caps_at_120_days() -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    seen = []
    for _ in range(len(INTERVALS) + 1):
        at = on_time(s)
        s = apply_evidence(s, ev(at, 3), TZ)
        seen.append(s.reason.interval_days)
        assert s.due_at == local_day_start(at, TZ, s.reason.interval_days)
    assert seen == [3, 7, 14, 30, 60, 120, 120, 120]
    assert s.step == len(INTERVALS) - 1


def test_early_success_does_not_promote() -> None:
    first = apply_evidence(None, ev(T0, 3), TZ)
    s = apply_evidence(first, ev(T0 + timedelta(hours=2), 4), TZ)
    assert s.step == 0 and s.due_at == first.due_at
    assert s.reason.code == "early_no_promotion"


def test_partial_steps_down_and_caps_at_three_days() -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    for _ in range(3):
        s = apply_evidence(s, ev(on_time(s), 3), TZ)
    assert s.step == 3
    at = on_time(s)
    s = apply_evidence(s, ev(at, 2), TZ)
    assert s.step == 2
    assert s.reason.interval_days == 3
    assert s.due_at == local_day_start(at, TZ, 3)
    assert s.consecutive_successes == 0


def test_t06_failure_after_success_shortens_interval_and_counts_lapse() -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    s = apply_evidence(s, ev(on_time(s), 3), TZ)
    s = apply_evidence(s, ev(on_time(s), 4), TZ)
    before_days = s.reason.interval_days
    at = on_time(s)
    s = apply_evidence(s, ev(at, 1), TZ)
    assert s.step == 0 and s.lapse_count == 1
    assert s.due_at == local_day_start(at, TZ, 1)
    assert before_days is not None and before_days > 1
    assert s.reason.code == "lapse"


def test_t07_transfer_grade_lengthens_interval_with_explanation() -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    s = apply_evidence(s, ev(on_time(s), 4), TZ)
    assert s.step == 1 and s.reason.interval_days == 3
    assert "Transfer (4/4)" in s.reason.message and "3 days" in s.reason.message


@pytest.mark.parametrize(
    ("grade", "status", "confidence"),
    [(4, "provisional", "high"), (None, "ungraded", "medium"), (4, "final", "low")],
)
def test_t08_uncertain_evidence_never_promotes_or_lengthens(grade: int | None, status: str, confidence: str) -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    s = apply_evidence(s, ev(on_time(s), 3), TZ)  # step 1, due in 3 days
    at = on_time(s)
    after = apply_evidence(s, ev(at, grade, status, confidence), TZ)
    assert after.step == s.step
    assert after.due_at == local_day_start(at, TZ, 1)
    assert after.reason.code == "uncertain_followup"


def test_uncertain_early_evidence_keeps_the_earlier_due_date() -> None:
    first = apply_evidence(None, ev(T0, 3), TZ)
    s = apply_evidence(first, ev(T0 + timedelta(hours=1), 2, "provisional", "low"), TZ)
    assert s.due_at == first.due_at


def test_first_uncertain_evidence_schedules_short_followup() -> None:
    s = apply_evidence(None, ev(T0, 2, "provisional", "low"), TZ)
    assert s.step == 0 and s.reason.code == "uncertain_followup"
    assert s.consecutive_successes == 0


def test_deferral_only_moves_due_later() -> None:
    s = apply_evidence(None, ev(T0, 3), TZ)
    assert apply_deferral(s, Deferral(T0, s.due_at - timedelta(hours=1))) == s
    later = local_day_start(T0, TZ, 3)
    d = apply_deferral(s, Deferral(T0, later))
    assert d is not None and d.due_at == later and d.step == s.step and d.reason.code == "deferred"
    assert apply_deferral(None, Deferral(T0, later)) is None


def test_replay_is_independent_of_input_order() -> None:
    events: list[Evidence | Deferral] = []
    at = T0
    for grade in (3, 3, 2, 4, 1, 3):
        events.append(ev(at, grade))
        at += timedelta(days=4)
    events.append(Deferral(T0 + timedelta(days=9), T0 + timedelta(days=12)))
    expected = replay(events, TZ)
    for seed in range(5):
        shuffled = events[:]
        random.Random(seed).shuffle(shuffled)
        assert replay(shuffled, TZ) == expected


def test_due_dates_follow_local_midnight_across_dst_end() -> None:
    at = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)  # CEST (UTC+2); DST ends 2026-10-25
    s = apply_evidence(None, ev(at, 3), TZ)
    assert s.due_at == datetime(2026, 10, 24, 22, 0, tzinfo=UTC)  # 2026-10-25 00:00 CEST
    assert local_day_start(at, TZ, 3) == datetime(2026, 10, 26, 23, 0, tzinfo=UTC)  # 2026-10-27 00:00 CET


def test_never_schedules_in_the_past() -> None:
    for hour in range(24):
        at = T0.replace(hour=hour)
        assert apply_evidence(None, ev(at, 0), TZ).due_at > at


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        apply_evidence(None, ev(datetime(2026, 11, 19, 16, 0), 3), TZ)
