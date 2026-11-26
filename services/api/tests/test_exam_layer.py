"""Exam layer of rs-interval-v3 (ADR-014): reviews brought forward before an exam, weak concepts the next day,
never a longer interval, and dates that follow the study target."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from recallspring_api import cli
from recallspring_api.db import new_session
from recallspring_api.learning.scheduler import (
    Deferral,
    Evidence,
    ExamDate,
    apply_exam_layer,
    exam_fraction,
    replay,
    schedule,
)
from recallspring_api.models import AuditEvent, ReviewState

from .conftest import Api, ConnectorApi, FrozenClock

TZ = ZoneInfo("Europe/Ljubljana")
DAY0 = date(2026, 11, 19)


def at(day: int, hour: int = 9) -> datetime:
    return datetime.combine(DAY0 + timedelta(days=day), time(hour), TZ).astimezone(UTC)


def ev(day: int, grade: int | None, status: str = "final", confidence: str = "high") -> Evidence:
    return Evidence(at(day), uuid.uuid4(), grade, status, confidence)  # type: ignore[arg-type]


def exam(day: int, goal: str = "exam_only", target: float | None = None) -> ExamDate:
    return ExamDate("1. kolokvij", DAY0 + timedelta(days=day), goal, target or (0.95 if goal == "exam_only" else 0.9))


def local_day(value: datetime) -> date:
    return value.astimezone(TZ).date()


def test_the_fraction_follows_the_fsrs6_forgetting_curve() -> None:
    assert exam_fraction(0.90) == pytest.approx(1.0)
    assert exam_fraction(0.95) == pytest.approx(0.40, abs=0.005)
    assert exam_fraction(0.97) == pytest.approx(0.22, abs=0.005)


def test_a_review_that_would_fall_after_the_exam_moves_to_the_day_before_it() -> None:
    events = [ev(0, 3), ev(1, 3), ev(4, 3)]  # the ladder's next review is day 11, the exam is on day 10
    ladder = replay(events, TZ)
    assert ladder is not None and local_day(ladder.due_at) == DAY0 + timedelta(days=11)

    capped = schedule(events, TZ, [exam(10)])
    assert capped is not None and local_day(capped.due_at) == DAY0 + timedelta(days=9)
    assert capped.reason.code == "exam_cap" and capped.reason.evidence_code == "promoted"
    assert capped.reason.policy_due_at == ladder.due_at and capped.step == ladder.step
    assert capped.reason.message == "Last review before 1. kolokvij on 29 Nov; brought forward from 30 Nov."
    reason = capped.reason.as_dict()
    assert (reason["code"], reason["exam_date"], reason["exam_target"]) == ("exam_cap", "2026-11-29", 0.95)
    assert reason["policy_version"] == "rs-interval-v3"

    long_term = schedule(events, TZ, [exam(10, "long_term")])
    assert long_term == ladder  # 6 days is less than one interval of 7: recall stays above 0.90


def test_a_review_on_the_brought_forward_day_keeps_the_ladder_and_adds_nothing_more() -> None:
    events = [ev(0, 3), ev(1, 3), ev(4, 3), ev(9, 3)]
    state = schedule(events, TZ, [exam(10)])
    assert state is not None and local_day(state.due_at) == DAY0 + timedelta(days=11)
    assert state.reason.code == "early_no_promotion" and state.step == 2  # early for the ladder: no promotion


def test_exams_on_or_before_the_last_review_do_not_count_and_the_nearest_capping_one_wins() -> None:
    events = [ev(0, 3), ev(1, 3), ev(4, 3)]
    assert schedule(events, TZ, [exam(4)]) == replay(events, TZ)
    both = schedule(events, TZ, [exam(9), exam(10)])
    assert both is not None and local_day(both.due_at) == DAY0 + timedelta(days=8)


def test_a_weak_concept_close_to_the_exam_comes_back_the_next_day() -> None:
    events = [ev(0, 3), ev(1, 3), ev(4, 3), ev(5, 2)]  # Partial on day 5 at step 2: the ladder says day 8
    assert local_day(replay(events, TZ).due_at) == DAY0 + timedelta(days=8)  # type: ignore[union-attr]

    state = schedule(events, TZ, [exam(10)])
    assert state is not None and state.reason.code == "relearn"
    assert local_day(state.due_at) == DAY0 + timedelta(days=6)
    assert state.reason.evidence_code == "partial" and "5 days before 1. kolokvij" in state.reason.message

    far = schedule(events, TZ, [exam(13)])  # 8 days before: not yet
    assert far is not None and far.reason.code != "relearn"
    eve = schedule([*events, ev(9, 2)], TZ, [exam(10)])  # on the day before: never on the exam day itself
    assert eve is not None and eve.reason.code == "partial" and local_day(eve.due_at) < DAY0 + timedelta(days=11)


def test_uncertain_evidence_does_not_make_a_concept_weak() -> None:
    events = [ev(0, 3), ev(1, 3), ev(4, 3), ev(5, 1, "provisional", "low")]
    state = schedule(events, TZ, [exam(10)])
    assert state is not None and state.last_certain_grade == 3 and state.reason.code == "uncertain_followup"


def test_a_deferral_after_the_last_answer_wins() -> None:
    events = [ev(0, 3), ev(1, 3), ev(4, 3), Deferral(at(5), at(14, 0))]
    state = schedule(events, TZ, [exam(10)])
    assert state is not None and state.reason.code == "deferred"
    assert local_day(state.due_at) == DAY0 + timedelta(days=14)


def test_the_layer_never_lengthens_an_interval() -> None:
    rng = random.Random(14)
    for _ in range(300):
        day, events = 0, []
        for _ in range(rng.randint(1, 7)):
            events.append(ev(day, rng.choice([0, 1, 2, 3, 3, 4, None]), rng.choice(["final", "final", "provisional"])))
            day += rng.randint(0, 5)
        goals = ["exam_only", "long_term"]
        exams = [exam(day + rng.randint(-3, 20), rng.choice(goals)) for _ in range(rng.randint(0, 2))]
        ladder = replay(events, TZ)
        layered = apply_exam_layer(ladder, exams, TZ)
        assert ladder is not None and layered is not None
        assert layered.due_at <= ladder.due_at
        assert (layered.step, layered.consecutive_successes, layered.lapse_count) == (
            ladder.step,
            ladder.consecutive_successes,
            ladder.lapse_count,
        )


# ------------------------------------------------------------------------------------------- through the API


def _solid(owner_api: Api, conn: ConnectorApi, question_id: str, grade: int = 3) -> dict:
    attempt = owner_api.answer(question_id).json()
    r = conn.post(
        f"/attempts/{attempt['attempt_id']}/assessments",
        {"status": "final", "grade": grade, "confidence": "high", "feedback": "Checked.", "evidence_refs": []},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _reason(owner_api: Api) -> dict:
    (item,) = owner_api.get("/reviews/due", horizon_days=30).json()["items"]
    return {**item["due_reason"], "due_at": item["due_at"]}


def test_review_dates_follow_the_study_target(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    conn.post("/concepts/known", {"concept_ids": [ids["concept_id"]], "reason": "Covered in lectures."})
    _solid(owner_api, conn, ids["question_id"])  # day 0 (19 Nov)
    frozen.advance(days=1)
    _solid(owner_api, conn, ids["question_id"])
    frozen.advance(days=3)
    _solid(owner_api, conn, ids["question_id"])  # day 4: the ladder's next review is 30 Nov
    assert _reason(owner_api)["code"] == "promoted"

    target = owner_api.post(
        "/targets",
        {
            "course_id": ids["course_id"],
            "kind": "kolokvij",
            "name": "1. kolokvij",
            "due_date": "2026-11-29",
            "scope_description": "Everything so far",
            "goal": "exam_only",
        },
    )
    assert target.status_code == 201, target.text
    tid = target.json()["id"]
    capped = _reason(owner_api)
    assert capped["code"] == "exam_cap" and capped["due_at"].startswith("2026-11-27T23:00")  # 28 Nov local
    assert capped["policy_due_at"].startswith("2026-11-29T23:00") and capped["exam"] == "1. kolokvij"

    assert owner_api.patch(f"/targets/{tid}", {"goal": "long_term"}).status_code == 200
    assert _reason(owner_api)["code"] == "promoted"
    assert owner_api.patch(f"/targets/{tid}", {"goal": "exam_only"}).status_code == 200
    assert _reason(owner_api)["code"] == "exam_cap"
    assert owner_api.client.delete(f"/api/v1/targets/{tid}", headers=owner_api.headers()).status_code == 200
    assert _reason(owner_api)["code"] == "promoted"
    assert owner_api.post(f"/targets/{tid}/restore").status_code == 200
    assert _reason(owner_api)["code"] == "exam_cap"

    frozen.set(datetime(2026, 11, 27, 8, 0, tzinfo=UTC))  # two days before, and the day before is full
    assert [i for i in conn.get("/plan").json()["items"] if i["category"] == "Review due"] == []
    assert conn.post("/availability", {"day": "2026-11-28", "minutes": 1, "note": "travelling"}).status_code == 200
    (early,) = [i for i in conn.get("/plan").json()["items"] if i["category"] == "Review due"]
    assert early["why_selected"].startswith("Brought forward from 28 Nov: the day before 1. kolokvij is full.")

    frozen.set(datetime(2026, 11, 28, 8, 0, tzinfo=UTC))  # the day before the exam
    (item,) = [i for i in conn.get("/plan").json()["items"] if i["category"] == "Review due"]
    assert "Last review before 1. kolokvij on 29 Nov" in item["why_selected"] and item["depth"] in ("quick", "standard")

    frozen.set(datetime(2026, 12, 1, 9, 0, tzinfo=UTC))  # the exam passed without that review
    after = _reason(owner_api)
    assert after["code"] == "promoted" and after["due_at"].startswith("2026-11-29T23:00")  # the ladder's own date


def test_a_weak_answer_before_the_exam_asks_for_another_try(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    ids = owner_api.course_with_question()
    conn.post("/concepts/known", {"concept_ids": [ids["concept_id"]], "reason": "Covered in lectures."})
    qid = ids["question_id"]
    assert "relearn" not in _solid(owner_api, conn, qid, grade=1)  # no exam yet
    target = {
        "course_id": ids["course_id"],
        "kind": "kolokvij",
        "name": "1. kolokvij",
        "due_date": "2026-11-24",
        "scope_description": "Everything so far",
        "goal": "exam_only",
    }
    assert owner_api.post("/targets", target).status_code == 201

    again = _solid(owner_api, conn, qid, grade=2)["relearn"]
    assert (again["days_left"], again["tries_today"], again["solid_needed"]) == (5, 2, 1)
    assert "not solid yet, 5 days before 1. kolokvij on 24 Nov" in again["say"] and "Glycolysis" in again["terms"]
    assert "relearn" not in _solid(owner_api, conn, qid, grade=3)  # one Solid answer is enough today

    frozen.set(datetime(2026, 11, 23, 9, 0, tzinfo=UTC))  # the day before the exam: two Solid answers
    eve = _solid(owner_api, conn, qid, grade=1)["relearn"]
    assert (eve["solid_needed"], eve["tries_today"]) == (2, 1) and "two Solid answers today" in eve["say"]
    once_more = _solid(owner_api, conn, qid, grade=3)["relearn"]
    assert "ask once more later in this session" in once_more["say"]
    assert "relearn" not in _solid(owner_api, conn, qid, grade=3)
    enough = _solid(owner_api, conn, qid, grade=2)["relearn"]
    assert enough["tries_today"] == 4 and "enough for today" in enough["say"] and "exam is tomorrow" in enough["say"]


def test_the_plan_relearns_weak_concepts_and_says_what_waited(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    ids = owner_api.course_with_question()
    second = owner_api.post(
        f"/courses/{ids['course_id']}/concepts",
        {
            "term": "Krebs cycle",
            "definition_draft": "Acetyl-CoA is oxidised",
            "source_section_ids": ids["section_ids"][:2],
        },
    ).json()
    q2 = owner_api.post(
        "/questions",
        {
            "course_id": ids["course_id"],
            "concept_ids": [second["id"]],
            "bloom_level": 4,
            "prompt": "Explain what the citric acid cycle needs from glycolysis.",
            "expected_points": ["pyruvate becomes acetyl-CoA"],
            "source_refs": ids["section_ids"][:2],
        },
    ).json()
    conn.post("/concepts/known", {"concept_ids": [ids["concept_id"], second["id"]], "reason": "Covered in lectures."})
    target = owner_api.post(
        "/targets",
        {
            "course_id": ids["course_id"],
            "kind": "kolokvij",
            "name": "1. kolokvij",
            "due_date": "2026-11-24",
            "scope_description": "Everything so far",
            "goal": "exam_only",
        },
    ).json()
    _solid(owner_api, conn, ids["question_id"], grade=2)
    _solid(owner_api, conn, q2["id"], grade=1)
    frozen.advance(days=1)  # 20 Nov: 4 days left

    plan = conn.get("/plan").json()
    assert plan["policy_version"] == "plan-v3" and plan["left_out"] == []
    relearn = [i for i in plan["items"] if i["category"] == "Relearn"]
    assert {i["term"] for i in relearn} == {"Glycolysis", "Krebs cycle"}
    assert all(i["depth"] == "relearn" and i["estimated_minutes"] >= 10 for i in relearn)
    assert "Not solid yet, 4 days before 1. kolokvij" in relearn[0]["why_selected"]

    conn.post("/availability", {"day": "2026-11-20", "minutes": 5, "note": "busy day"})
    plan = conn.get("/plan").json()
    assert len([i for i in plan["items"] if i["category"] == "Relearn"]) == 1  # the first item may run over
    (waited,) = plan["left_out"]
    assert waited["category"] == "Relearn" and waited["target"] == "1. kolokvij"
    limits = owner_api.get(f"/targets/{target['id']}/rationale").json()["limits"]
    (trimmed,) = [m for m in limits if m["code"] == "exam_tail_trimmed"]
    assert waited["term"] in trimmed["message"] and "They stay due." in trimmed["message"]


def test_recompute_reviews_replays_states_of_an_older_policy(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = owner_api.course_with_question()
    conn.post("/concepts/known", {"concept_ids": [ids["concept_id"]], "reason": "Covered in lectures."})
    for days in (0, 1, 3):
        frozen.advance(days=days)
        _solid(owner_api, conn, ids["question_id"])
    target = {
        "course_id": ids["course_id"],
        "kind": "kolokvij",
        "name": "1. kolokvij",
        "due_date": "2026-11-29",
        "scope_description": "Everything so far",
        "goal": "exam_only",
    }
    assert owner_api.post("/targets", target).status_code == 201
    with new_session() as db:  # as a state computed by rs-interval-v2 before the exam layer existed
        row = db.scalars(select(ReviewState).where(ReviewState.concept_id == uuid.UUID(ids["concept_id"]))).one()
        assert row.due_reason["code"] == "exam_cap"
        row.due_at = datetime.fromisoformat(row.due_reason["policy_due_at"])
        row.due_reason = {"code": "promoted", "message": "Old.", "policy_version": "rs-interval-v2"}
        row.policy_version = "rs-interval-v2"
        db.commit()
    assert _reason(owner_api)["code"] == "promoted"

    assert cli.main(["recompute-reviews"]) == 0
    assert "Replayed 1 review state(s) with rs-interval-v3; 1 got a new date or reason." in capsys.readouterr().out
    assert _reason(owner_api)["code"] == "exam_cap"
    with new_session() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.action == "reviews.recomputed")).one()
        assert event.details["policy_version"] == "rs-interval-v3" and event.details["changed"] == 1
