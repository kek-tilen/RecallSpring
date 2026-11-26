"""FSRS-6 in shadow (ADR-014 §5): the pinned library and its fixtures, the grade mapping of both variants, one review
per local day in whole days, Check first as a first Easy review, the exam cap from R on the exam morning, a table
rebuilt by every replay that never shows and never stops a grade, and the local report."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from recallspring_api import cli
from recallspring_api.db import new_session
from recallspring_api.learning import fsrs_shadow
from recallspring_api.learning.fsrs_shadow import ShadowExam, ShadowReview, rating_for, run
from recallspring_api.learning.scheduler import Evidence, KnownFromCheck
from recallspring_api.models import ReviewShadow, ReviewState
from recallspring_api.services import shadow, shadow_report

from .conftest import Api, ConnectorApi, FrozenClock

DAY0 = date(2026, 11, 19)
TZ = ZoneInfo("Europe/Ljubljana")


def answer(day: int, grade: int) -> ShadowReview:
    return ShadowReview(DAY0 + timedelta(days=day), "answer", uuid.uuid4(), grade)


def exam(day: int, target: float) -> ShadowExam:
    return ShadowExam(uuid.uuid4(), DAY0 + timedelta(days=day), target)


# ---------------------------------------------------------------- the engine (pure)


def test_the_library_is_pinned_and_reproduces_the_fixtures() -> None:
    assert fsrs_shadow.LIBRARY_VERSION == "6.3.3"
    assert fsrs_shadow.PARAMS_HASH == "6eaf4ac968ce8833"  # the default FSRS-6 parameters
    assert fsrs_shadow.SCHEDULER.to_dict() | {"parameters": None} == {
        "parameters": None,
        "desired_retention": 0.9,
        "learning_steps": [],
        "relearning_steps": [],
        "maximum_interval": 120,
        "enable_fuzzing": False,
    }
    first, second = run(uuid.uuid4(), [answer(0, 3), answer(2, 3)], [], "rs-fsrs6-v1")
    assert first.s_after == pytest.approx(2.31, abs=0.005) and first.r_before is None and first.elapsed_days is None
    assert second.s_after == pytest.approx(10.96, abs=0.005) and second.elapsed_days == 2
    assert second.r_before == pytest.approx(0.909, abs=0.001) and second.s_before == first.s_after
    assert (first.fsrs_due, second.fsrs_due) == (DAY0 + timedelta(days=2), DAY0 + timedelta(days=13))
    again = run(uuid.uuid4(), [answer(0, 3), answer(2, 3)], [], "rs-fsrs6-v1")  # no fuzz: always the same
    assert [(r.s_after, r.d_after, r.fsrs_due) for r in again] == [
        (r.s_after, r.d_after, r.fsrs_due) for r in (first, second)
    ]


def test_grades_map_to_ratings_with_partial_side_by_side() -> None:
    v1 = [int(rating_for(answer(0, g), "rs-fsrs6-v1")) for g in range(5)]
    v1a = [int(rating_for(answer(0, g), "rs-fsrs6-v1a")) for g in range(5)]
    assert v1 == [1, 1, 2, 3, 3]  # No evidence, Fragile: Again; Partial: Hard; Solid, Transfer: Good
    assert v1a == [1, 1, 1, 3, 3]  # Partial: Again
    assert int(rating_for(ShadowReview(DAY0, "check_first"), "rs-fsrs6-v1")) == 4  # Easy

    hard, again = (run(uuid.uuid4(), [answer(0, 3), answer(2, 2)], [], v)[1] for v in fsrs_shadow.VARIANTS)
    assert hard.rating == 2 and again.rating == 1 and hard.s_after > again.s_after


def test_one_review_per_local_day_in_whole_days() -> None:
    late = datetime(2026, 11, 19, 22, 30, tzinfo=UTC)  # 23:30 in Ljubljana
    later = late + timedelta(minutes=20)  # 23:50: the same local day, audit only
    morning = datetime(2026, 11, 20, 7, 0, tzinfo=UTC)  # 8:00 the next day: a new day, not the same session
    ids = [uuid.uuid4() for _ in range(5)]
    events = [
        Evidence(morning, ids[0], 3, "final", "high"),
        Evidence(later, ids[1], 1, "final", "high"),
        Evidence(late, ids[2], 2, "final", "medium"),
        Evidence(morning + timedelta(days=1), ids[3], 3, "provisional", "high"),  # never in the shadow
        Evidence(morning + timedelta(days=2), ids[4], 3, "final", "low"),
    ]
    details = {i: ("ai", 3) for i in ids}
    reviews = shadow.reviews_from(events, details, TZ)
    assert [(r.local_date, r.attempt_id, r.grade) for r in reviews] == [
        (DAY0, ids[2], 2),
        (DAY0 + timedelta(days=1), ids[0], 3),
    ]
    assert run(uuid.uuid4(), reviews, [], "rs-fsrs6-v1")[1].elapsed_days == 1

    details[ids[0]] = ("self", 3)  # self-assessed grades stay out, as from mastery
    assert [r.attempt_id for r in shadow.reviews_from(events, details, TZ)] == [ids[2]]


def test_check_first_is_a_first_easy_review_with_the_21_day_overlay() -> None:
    (row,) = run(uuid.uuid4(), [ShadowReview(DAY0, "check_first")], [], "rs-fsrs6-v1")
    assert row.rating == 4 and row.fsrs_due == DAY0 + timedelta(days=8)  # FSRS's own date
    assert row.capped_due == DAY0 + timedelta(days=21)  # ADR-009's first review stays

    checked = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
    practised = Evidence(datetime(2026, 11, 20, 9, 0, tzinfo=UTC), uuid.uuid4(), 3, "final", "high")
    reviews = shadow.reviews_from([practised, KnownFromCheck(checked, uuid.uuid4())], {}, TZ)
    assert [r.source for r in reviews] == ["answer"]  # after practice a check is a diagnostic, not evidence


def test_the_exam_cap_uses_fsrs_r_on_the_exam_morning() -> None:
    reviews = [answer(0, 3), answer(2, 3)]  # FSRS's next date is day 13; the exam is on day 10
    capped = run(uuid.uuid4(), reviews, [exam(10, 0.95)], "rs-fsrs6-v1")[1]
    assert capped.exam_r == pytest.approx(0.92, abs=0.005) and capped.fsrs_due == DAY0 + timedelta(days=13)
    assert capped.capped_due == DAY0 + timedelta(days=9)  # the day before the exam
    kept = run(uuid.uuid4(), reviews, [exam(10, 0.90)], "rs-fsrs6-v1")[1]
    assert kept.capped_due == kept.fsrs_due  # 0.92 is above a long-term target
    early = run(uuid.uuid4(), reviews, [exam(3, 0.95)], "rs-fsrs6-v1")[1]
    assert early.capped_due == early.fsrs_due  # the day before the exam is the review day itself: no cap
    nearest = run(uuid.uuid4(), reviews, [exam(30, 0.95), exam(10, 0.95)], "rs-fsrs6-v1")[1]
    assert nearest.exam is not None and nearest.exam.day == DAY0 + timedelta(days=10)


# ---------------------------------------------------------------- stored beside the ladder


def _rows(variant: str = "rs-fsrs6-v1") -> list[ReviewShadow]:
    with new_session() as db:
        return list(
            db.scalars(
                select(ReviewShadow)
                .where(ReviewShadow.variant == variant)
                .order_by(ReviewShadow.concept_id, ReviewShadow.seq)
            )
        )


def _grade(conn: ConnectorApi, attempt_id: str, grade: int, status: str = "final", confidence: str = "high") -> None:
    body = {"status": status, "grade": grade, "confidence": confidence, "feedback": "Checked against the notes."}
    if status == "ungraded":
        body["grade"] = None
    r = conn.post(f"/attempts/{attempt_id}/assessments", body)
    assert r.status_code in (200, 201), r.text


def test_every_replay_rebuilds_the_shadow_from_certain_first_answers(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    ids = owner_api.course_with_question()  # Bloom 4
    first = owner_api.answer(ids["question_id"]).json()["attempt_id"]
    _grade(conn, first, 2)
    (row,) = _rows()
    assert (row.seq, row.source, row.grade, row.rating, row.bloom_level) == (1, "answer", 2, 2, 4)
    assert (row.evaluator_kind, row.confidence, row.local_date) == ("ai", "high", date(2026, 11, 19))
    assert (row.library_version, row.params_hash) == ("6.3.3", fsrs_shadow.PARAMS_HASH)
    assert [r.rating for r in _rows("rs-fsrs6-v1a")] == [1]  # Partial as Again, side by side

    frozen.advance(hours=1)
    _grade(conn, owner_api.answer(ids["question_id"]).json()["attempt_id"], 3)
    assert len(_rows()) == 1  # a later answer the same day is audit only

    frozen.advance(days=1)
    _grade(conn, owner_api.answer(ids["question_id"]).json()["attempt_id"], 3, status="provisional")
    _grade(conn, owner_api.answer(ids["question_id"]).json()["attempt_id"], 3, confidence="low")
    assert len(_rows()) == 1  # uncertain grades stay out

    frozen.advance(days=1)
    _grade(conn, owner_api.answer(ids["question_id"]).json()["attempt_id"], 3)
    rows = _rows()
    assert [(r.seq, r.grade, r.elapsed_days) for r in rows] == [(1, 2, None), (2, 3, 2)]
    assert rows[1].r_before is not None and rows[1].s_before == rows[0].s_after

    # a learner's correction replays the concept, and the shadow follows
    ai = owner_api.get(f"/attempts/{first}").json()["assessments"][0]
    fixed = owner_api.post(f"/assessments/{ai['id']}/challenge", {"reason": "Both points", "corrected_grade": 3})
    assert fixed.status_code == 200, fixed.text
    rows = _rows()
    assert [(r.grade, r.evaluator_kind) for r in rows] == [(3, "human"), (3, "ai")]
    with new_session() as db:  # the ladder is unchanged by any of this: it keeps its own state
        state = db.get(ReviewState, (rows[0].user_id, rows[0].concept_id))
        assert state is not None and state.policy_version == "rs-interval-v3"


def test_the_shadow_never_stops_a_grade(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> list:
        raise RuntimeError("shadow failure")

    monkeypatch.setattr(fsrs_shadow, "run", broken)
    ids = owner_api.course_with_question()
    attempt = owner_api.answer(ids["question_id"]).json()["attempt_id"]
    _grade(conn, attempt, 3)
    assert owner_api.get("/reviews/due", horizon_days=2).json()["items"]  # the ladder's review is there
    assert _rows() == []


def test_nothing_in_the_app_or_the_connector_shows_the_shadow(owner_api: Api) -> None:
    spec = json.dumps(owner_api.client.get("/api/v1/openapi.json").json()).lower()
    for word in ("shadow", "retrievability", "stability", "fsrs"):
        assert word not in spec


def test_the_exam_comes_from_every_target_in_scope(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    r = owner_api.post(
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
    assert r.status_code == 201, r.text
    _grade(conn, owner_api.answer(ids["question_id"]).json()["attempt_id"], 3)
    (row,) = _rows()
    assert (row.exam_date, row.exam_target) == (date(2026, 11, 29), 0.95) and row.exam_r is not None
    assert str(row.target_id) == r.json()["id"]
    assert owner_api.patch(f"/targets/{r.json()['id']}", {"before_exam": "intense"}).status_code == 200
    assert _rows()[0].exam_target == 0.97  # the target changed: the shadow followed


# ---------------------------------------------------------------- the report


def test_prediction_uses_earlier_days_only_and_a_fixed_bootstrap() -> None:
    concept = uuid.uuid4()

    def row(day: int, r: float, rating: int) -> SimpleNamespace:
        return SimpleNamespace(
            seq=2, r_before=r, source="answer", rating=rating, concept_id=concept, local_date=DAY0 + timedelta(days=day)
        )

    rows = [row(d, 0.9, 3) for d in range(12)] + [row(12, 0.9, 1)]
    out = shadow_report.prediction(rows)  # type: ignore[arg-type]
    assert out["reviews"] == 13 and out["pass_rate"] == pytest.approx(12 / 13)
    assert out["interval90"] is not None and out == shadow_report.prediction(rows)  # type: ignore[arg-type]
    same_day = [row(0, 0.9, 3), row(0, 0.9, 3)]  # the second review of the day must not see the first
    assert shadow_report.prediction(same_day)["baseline"] == pytest.approx(shadow_report._log_loss(1, 0.5))  # type: ignore[arg-type]
    assert shadow_report.prediction([])["fsrs"] is None


def test_recompute_reviews_fills_the_shadow_and_the_report_stays_local(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    ids = owner_api.course_with_question()
    for day in range(3):
        _grade(conn, owner_api.answer(ids["question_id"]).json()["attempt_id"], [2, 3, 3][day])
        frozen.advance(days=2)
    with new_session() as db:  # e.g. answers given before the shadow existed
        db.execute(delete(ReviewShadow))
        db.commit()
    assert cli.main(["shadow-report"]) == 0
    assert "No shadow data yet" in capsys.readouterr().out

    assert cli.main(["recompute-reviews"]) == 0
    assert [r.grade for r in _rows()] == [2, 3, 3]
    monkeypatch.setattr(cli, "reports_dir", lambda: tmp_path / "reports")
    assert cli.main(["shadow-report", "--save"]) == 0
    out = capsys.readouterr().out
    assert "FSRS-6 shadow report" in out and "rs-fsrs6-v1a" in out and "Phase B criteria" in out
    assert "not a chance of remembering" in out
    saved = list((tmp_path / "reports").glob("shadow-report-*.json"))
    assert len(saved) == 1 and (tmp_path / "reports" / saved[0].name.replace(".json", ".md")).exists()
    report = json.loads(saved[0].read_text(encoding="utf-8"))[0]
    assert report["data"]["reviews"] == 3 and report["data"]["evaluable_reviews"] == 2
    assert report["partial_question"]["2"]["next_reviews"] == 1
    assert report["partial_question"]["2"]["next_solid_or_better"] == 1.0
    assert report["switch_criteria"]["reviews_100"] is False
    assert report["graders"]["reviews"] == {"ai/high": 3}
