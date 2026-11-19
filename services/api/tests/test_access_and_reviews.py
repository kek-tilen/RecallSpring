"""Cross-user isolation (T-15), explicit deferral with audit, due explanations, questions and health."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent

from .conftest import Api, FrozenClock, make_user


def test_t15_other_users_cannot_see_or_touch_owner_records(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    attempt_id = owner_api.answer(ids["question_id"]).json()["attempt_id"]

    make_user("intruder")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("intruder").status_code == 200
        for path in (
            f"/courses/{ids['course_id']}",
            f"/questions/{ids['question_id']}",
            f"/attempts/{attempt_id}",
            f"/courses/{ids['course_id']}/concepts",
        ):
            r = other.get(path)
            assert r.status_code == 404, path
        assert other.get("/courses").json() == []
        assert other.post(f"/attempts/{attempt_id}/evaluate").status_code == 404
        assert other.answer(ids["question_id"]).status_code == 404
        assert other.post(f"/reviews/{ids['concept_id']}/defer", {"days": 3}).status_code == 404


def test_defer_is_explicit_audited_and_skips_never_defer(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    owner_api.answer(ids["question_id"], kind="dont_know", text="")
    frozen.advance(days=1)
    assert len(owner_api.get("/reviews/due").json()["items"]) == 1

    owner_api.answer(ids["question_id"], kind="skip", text="")
    assert len(owner_api.get("/reviews/due").json()["items"]) == 1  # skipped reviews remain due

    r = owner_api.post(f"/reviews/{ids['concept_id']}/defer", {"days": 2, "reason": "Exam week"})
    assert r.status_code == 200
    assert r.json()["due_reason"]["code"] == "deferred" and r.json()["is_due"] is False
    assert owner_api.get("/reviews/due").json()["items"] == []
    with new_session() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "review.defer")) is not None


def test_defer_without_schedule_is_rejected(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    r = owner_api.post(f"/reviews/{ids['concept_id']}/defer", {"days": 1})
    assert r.status_code == 409 and r.json()["code"] == "not_scheduled"


def test_generated_questions_are_labelled_simulated_and_progressive(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    r = owner_api.post(
        "/questions/generate",
        {"course_id": ids["course_id"], "concept_ids": [ids["concept_id"]], "bloom_levels": [5, 3, 4]},
    )
    assert r.status_code == 201
    questions = r.json()["questions"]
    assert [q["bloom_level"] for q in questions] == [3, 4, 5]
    assert all(q["provenance"]["simulated"] is True for q in questions)
    assert all(q["rubric"] is None for q in questions)


def test_question_for_concept_in_another_course_is_rejected(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    other_course = owner_api.post("/courses", {"title": "Other"}).json()
    r = owner_api.post(
        "/questions",
        {"course_id": other_course["id"], "concept_ids": [ids["concept_id"]], "bloom_level": 3, "prompt": "?"},
    )
    assert r.status_code == 404


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200 and ready.json()["checks"] == {"database": True, "contracts": True}


def test_openapi_contract_is_published(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    for path in (
        "/api/v1/attempts",
        "/api/v1/attempts/{attempt_id}/evaluate",
        "/api/v1/reviews/due",
        "/api/v1/assessments/{assessment_id}/challenge",
    ):
        assert path in spec["paths"]
