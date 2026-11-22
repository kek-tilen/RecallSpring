"""Persist-first answers, safe evaluation retries, corrections and restart durability (T-01, T-02, T-08, T-13, T-24)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from recallspring_api.config import get_settings
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import Assessment, Attempt, LearningEvent

from .conftest import Api, FrozenClock


def count(model: type) -> int:
    with new_session() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def mock_behavior(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def set_behavior(value: str) -> None:
        monkeypatch.setattr(get_settings(), "mock_ai_behavior", value)

    return set_behavior


def test_answer_is_saved_exactly_before_any_evaluation(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    text = "  Glycolysis — läuft im Zytoplasma.\nPyruvate → citric acid cycle.  "  # exact bytes, any language
    r = owner_api.answer(ids["question_id"], text)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "saved_awaiting_evaluation" and body["saved_at"]
    stored = owner_api.get(f"/attempts/{body['attempt_id']}").json()
    assert stored["answer_text"] == text
    assert stored["assessments"] == [] and stored["captured_via"] == "app_ui"


def test_t01_ai_timeout_keeps_the_saved_answer_and_allows_retry(owner_api: Api, mock_behavior) -> None:  # type: ignore[no-untyped-def]
    ids = owner_api.course_with_question()
    attempt_id = owner_api.answer(ids["question_id"]).json()["attempt_id"]

    mock_behavior("timeout")
    r = owner_api.post(f"/attempts/{attempt_id}/evaluate")
    assert r.status_code == 503
    assert r.json()["code"] == "evaluation_unavailable"
    assert r.json()["details"] == {
        "attempt_id": attempt_id,
        "status": "saved_awaiting_evaluation",
        "reason": "ai_timeout",
        "retryable": True,
    }
    stored = owner_api.get(f"/attempts/{attempt_id}").json()
    assert stored["status"] == "saved_awaiting_evaluation" and stored["last_evaluation_error"] == "ai_timeout"
    assert count(Assessment) == 0

    mock_behavior("normal")
    r = owner_api.post(f"/attempts/{attempt_id}/evaluate")
    assert r.status_code == 200
    assert r.json()["status"] == "evaluated" and len(r.json()["assessments"]) == 1


def test_t02_retries_never_duplicate_attempts_or_grades(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    key, client_request_id = str(uuid.uuid4()), str(uuid.uuid4())
    first = owner_api.answer(ids["question_id"], client_request_id=client_request_id, key=key)
    replay = owner_api.answer(ids["question_id"], client_request_id=client_request_id, key=key)
    outbox_replay = owner_api.answer(ids["question_id"], client_request_id=client_request_id)  # new key
    assert first.status_code == 201 and replay.status_code == 201 and outbox_replay.status_code == 200
    assert first.json() == replay.json() and first.json() == outbox_replay.json()
    assert count(Attempt) == 1

    conflict = owner_api.answer(ids["question_id"], text="A different answer", client_request_id=client_request_id)
    assert conflict.status_code == 409 and conflict.json()["code"] == "client_request_id_conflict"

    attempt_id = first.json()["attempt_id"]
    eval_key = uuid.uuid4()
    a = owner_api.post(f"/attempts/{attempt_id}/evaluate", key=eval_key)
    b = owner_api.post(f"/attempts/{attempt_id}/evaluate", key=eval_key)
    c = owner_api.post(f"/attempts/{attempt_id}/evaluate")  # new key, already evaluated
    assert a.status_code == b.status_code == c.status_code == 200
    assert a.json() == b.json() == c.json()
    assert count(Assessment) == 1


def test_mock_assessment_is_labelled_simulated_and_never_lengthens_interval(
    owner_api: Api, frozen: FrozenClock
) -> None:
    ids = owner_api.course_with_question()
    attempt_id = owner_api.answer(ids["question_id"]).json()["attempt_id"]
    assessment = owner_api.post(f"/attempts/{attempt_id}/evaluate").json()["assessments"][0]
    assert assessment["simulated"] is True and assessment["provider"] == "mock"
    assert assessment["status"] == "provisional" and assessment["confidence"] == "low"
    assert assessment["feedback"].startswith("[Simulated")
    assert assessment["evidence_refs"] and set(assessment["evidence_refs"]) <= set(ids["section_ids"][:2])

    upcoming = owner_api.get("/reviews/due", horizon_days=1).json()["items"]
    assert len(upcoming) == 1
    assert upcoming[0]["due_reason"]["code"] == "uncertain_followup"
    assert upcoming[0]["due_at"].startswith("2026-11-19T23:00")  # next local midnight, not later


def test_invalid_model_output_is_rejected_without_storing_a_grade(owner_api: Api, mock_behavior) -> None:  # type: ignore[no-untyped-def]
    ids = owner_api.course_with_question()
    attempt_id = owner_api.answer(ids["question_id"]).json()["attempt_id"]
    mock_behavior("invalid")
    r = owner_api.post(f"/attempts/{attempt_id}/evaluate")
    assert r.status_code == 503 and r.json()["details"]["reason"] == "ai_invalid_output"
    assert "<script>" not in r.text
    assert count(Assessment) == 0
    assert owner_api.get(f"/attempts/{attempt_id}").json()["status"] == "saved_awaiting_evaluation"


def test_dont_know_is_an_explicit_attempt_scheduled_for_the_next_day(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    r = owner_api.answer(ids["question_id"], text="", kind="dont_know")
    assert r.status_code == 201 and r.json()["status"] == "evaluated"
    attempt = owner_api.get(f"/attempts/{r.json()['attempt_id']}").json()
    assert attempt["assessments"][0]["evaluator_kind"] == "deterministic"
    assert attempt["assessments"][0]["grade"] == 0
    frozen.advance(days=1)
    due = owner_api.get("/reviews/due").json()["items"]
    assert [i["concept_id"] for i in due] == [ids["concept_id"]]


def test_skip_creates_no_evidence_and_no_schedule(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    r = owner_api.answer(ids["question_id"], text="", kind="skip")
    assert r.status_code == 201 and r.json()["status"] == "not_applicable"
    assert owner_api.get("/reviews/due", horizon_days=30).json()["items"] == []
    evaluate = owner_api.post(f"/attempts/{r.json()['attempt_id']}/evaluate")
    assert evaluate.status_code == 409 and evaluate.json()["code"] == "not_evaluable"


def test_empty_written_answer_is_rejected(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    r = owner_api.answer(ids["question_id"], text="   ")
    assert r.status_code == 422 and r.json()["code"] == "answer_empty"
    assert count(Attempt) == 0


def test_rubric_is_hidden_until_the_learner_has_answered(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    first = owner_api.get(f"/questions/{ids['question_id']}").json()
    assert first["rubric"] is None and first["latest_attempt_id"] is None
    attempt = owner_api.answer(ids["question_id"]).json()
    q = owner_api.get(f"/questions/{ids['question_id']}").json()
    assert q["rubric"]["expected_points"]
    assert q["latest_attempt_id"] == attempt["attempt_id"]  # Chat shows this answer under the question's old form


def test_grade_correction_appends_human_assessment_and_recomputes_schedule(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    attempt_id = owner_api.answer(ids["question_id"]).json()["attempt_id"]
    ai = owner_api.post(f"/attempts/{attempt_id}/evaluate").json()["assessments"][0]

    challenge_only = owner_api.post(f"/assessments/{ai['id']}/challenge", {"reason": "I think this is wrong"})
    assert challenge_only.status_code == 200 and len(challenge_only.json()["assessments"]) == 1

    corrected = owner_api.post(
        f"/assessments/{ai['id']}/challenge", {"reason": "I covered both points", "corrected_grade": 3}
    ).json()
    assert len(corrected["assessments"]) == 2
    human = next(a for a in corrected["assessments"] if a["evaluator_kind"] == "human")
    assert human["supersedes_id"] == ai["id"] and corrected["effective_assessment_id"] == human["id"]
    assert any(a["id"] == ai["id"] for a in corrected["assessments"])  # original kept, never overwritten

    item = owner_api.get("/reviews/due", horizon_days=1).json()["items"][0]
    assert item["due_reason"]["code"] == "first_evidence" and item["due_reason"]["grade"] == 3

    with new_session() as db:
        types = set(db.scalars(select(LearningEvent.event_type)))
    assert {"attempt.submitted", "assessment.recorded", "assessment.challenged", "assessment.corrected"} <= types


def test_t13_data_survives_an_app_restart_and_review_is_still_due(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    attempt_id = owner_api.answer(ids["question_id"], kind="dont_know", text="").json()["attempt_id"]

    frozen.advance(days=2)
    with TestClient(create_app()) as restarted:
        api = Api(restarted)
        assert api.login("owner").status_code == 200
        assert api.get(f"/attempts/{attempt_id}").json()["kind"] == "dont_know"
        due = api.get("/reviews/due").json()
        assert [i["concept_id"] for i in due["items"]] == [ids["concept_id"]]
        assert due["note"] == "Estimated from practice, not a guarantee of recall."


def test_t24_storage_failure_never_acknowledges_a_save(owner_api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = owner_api.course_with_question()

    def broken_commit(self) -> None:  # type: ignore[no-untyped-def]
        raise OperationalError("COMMIT", {}, Exception("database is unreachable"))

    monkeypatch.setattr("sqlalchemy.orm.Session.commit", broken_commit)
    r = owner_api.answer(ids["question_id"])
    assert r.status_code == 503 and r.json()["code"] == "storage_unavailable"
    monkeypatch.undo()
    assert count(Attempt) == 0
