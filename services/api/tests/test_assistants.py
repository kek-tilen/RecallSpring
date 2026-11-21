"""RecallSpring with Codex instead of Claude: a token per assistant, grades labelled with the assistant and the model
it reported, counted exactly like Claude's (owner decision 2026-11-21)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

from recallspring_api.main import create_app

from .conftest import Api, ConnectorApi, FrozenClock


def _codex(owner_api: Api) -> tuple[dict[str, Any], str]:
    r = owner_api.post("/settings/connector/tokens", {"client": "codex"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body, body["token"]


def _grade(conn: ConnectorApi, owner_api: Api, model: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ids = owner_api.course_with_question()
    attempt = conn.post(
        "/attempts",
        {
            "question_id": ids["question_id"],
            "client_request_id": str(uuid.uuid4()),
            "answer_text": "Glycolysis happens in the cytoplasm.",
            "captured_via": "answer_form",
        },
    ).json()
    r = conn.post(
        f"/attempts/{attempt['attempt_id']}/assessments",
        {
            "status": "final",
            "grade": 3,
            "confidence": "high",
            "feedback": "Correct.",
            "evidence_refs": [ids["section_ids"][0]],
            "model_name": model,
        },
    )
    assert r.status_code == 200, r.text
    return ids, r.json()


def test_a_codex_token_is_its_own_and_labels_its_grades(owner_api: Api, frozen: FrozenClock) -> None:
    created, token = _codex(owner_api)
    assert created["client"] == "codex" and created["label"] == "Codex"
    claude = owner_api.post("/settings/connector/tokens", {}).json()
    assert claude["client"] == "claude" and claude["label"] == "Claude Desktop"
    assert owner_api.post("/settings/connector/tokens", {"client": "gemini"}).status_code == 422

    with TestClient(create_app()) as c:
        ids, body = _grade(ConnectorApi(c, token), owner_api, "gpt-5.5-codex")
    a = body["assessments"][0]
    assert a["provider"] == "codex_app" and a["model"] == "gpt-5.5-codex" and a["model_reported_by"] == "assistant"
    # Counted like any assistant grade: the review is scheduled the same way.
    assert body["schedule"][0]["reason"] == "First practice recorded; first review is the next day."

    concept = owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()
    graded = [h for h in concept["attempts"] if h["grade"] is not None]
    assert graded[0]["graded_by"] == "ai" and graded[0]["grader"] == {"name": "Codex", "model": "gpt-5.5-codex"}

    history = [h for h in owner_api.get("/history").json() if h["type"] == "assessment.recorded"]
    assert history[0]["detail"] == "3/4 (final) by Codex (gpt-5.5-codex)"

    tokens = owner_api.get("/settings/connector").json()["tokens"]
    assert {t["client"] for t in tokens} == {"claude", "codex"}


def test_revoking_codex_leaves_claude_connected(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    created, token = _codex(owner_api)
    r = owner_api.post(f"/settings/connector/tokens/{created['id']}/revoke", {})
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    with TestClient(create_app()) as c:
        assert ConnectorApi(c, token).get("/courses").status_code == 401
    assert conn.get("/courses").status_code == 200


def test_claude_grades_keep_their_label(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    ids, body = _grade(conn, owner_api, "Claude Sonnet 5.5")
    assert body["assessments"][0]["provider"] == "claude_app"
    concept = owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()
    graded = [h for h in concept["attempts"] if h["grade"] is not None]
    assert graded[0]["grader"] == {"name": "Claude", "model": "Claude Sonnet 5.5"}


def test_an_answer_given_in_the_web_app_is_found_by_the_assistant(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    ids = owner_api.course_with_question()
    assert conn.get(f"/questions/{ids['question_id']}").json()["latest_attempt"] is None
    typed = "  Glikoliza poteka v citoplazmi.\n"
    saved = owner_api.post(
        "/attempts", {"question_id": ids["question_id"], "client_request_id": str(uuid.uuid4()), "answer_text": typed}
    )
    assert saved.status_code == 201
    latest = conn.get(f"/questions/{ids['question_id']}").json()["latest_attempt"]
    assert latest["attempt_id"] == saved.json()["attempt_id"] and latest["captured_via"] == "app_ui"
    assert conn.get(f"/attempts/{latest['attempt_id']}").json()["answer_text"] == typed


def test_a_summary_written_in_the_web_app_marks_the_concepts_studied(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    payload = {
        "course_id": ids["course_id"],
        "concept_ids": [ids["concept_id"]],
        "title": "Lecture 3",
        "text": "My own words.",
        "client_request_id": str(uuid.uuid4()),
    }
    assert owner_api.client.post("/api/v1/learning", json=payload).status_code in (400, 403)  # needs CSRF + key
    r = owner_api.post("/learning", payload)
    assert r.status_code == 201, r.text
    detail = owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()
    assert detail["study_status"] == "studied" and detail["study_source"] == "session"
    notes = [n for n in owner_api.get("/notes").json() if n["title"] == "Lecture 3"]
    assert len(notes) == 1
