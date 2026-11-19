"""Claude connector surface: token scope, read/append-only contract, answer capture, validated grading,
daily limit and the deterministic planner (FR-17, T-25, T-26, T-27)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from recallspring_api.config import get_settings

from .conftest import Api, ConnectorApi, FrozenClock


def test_token_is_shown_once_and_stored_only_as_hash(owner_api: Api) -> None:
    key = str(uuid.uuid4())
    first = owner_api.post("/settings/connector/tokens", {"label": "Claude Desktop"}, key=key)
    again = owner_api.post("/settings/connector/tokens", {"label": "Claude Desktop"}, key=key)
    assert first.json()["token"].startswith("rsc_") and again.json()["token"] is None
    settings = owner_api.get("/settings/connector").json()
    assert len(settings["tokens"]) == 1 and "token" not in settings["tokens"][0]
    assert first.json()["token"] not in owner_api.get("/settings/connector").text


def test_connector_token_only_works_on_connector_routes(owner_api: Api, conn: ConnectorApi) -> None:
    assert conn.get("/courses").status_code == 200
    for path in ("/api/v1/courses", "/api/v1/settings/connector", "/api/v1/planner/today"):
        assert conn.client.get(path, headers=conn.auth).status_code == 401
    r = owner_api.client.get("/api/v1/connector/courses")  # session cookie is not a connector credential
    assert r.status_code == 401 and r.json()["code"] == "connector_token_required"


def test_t25_connector_surface_is_read_and_append_only(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    connector_paths = {p: ops for p, ops in spec["paths"].items() if p.startswith("/api/v1/connector")}
    assert connector_paths
    for path, ops in connector_paths.items():
        assert set(ops) <= {"get", "post"}, path
        assert not any(word in path for word in ("delete", "export", "settings", "token", "budget", "consent"))


def test_revoked_token_is_rejected(owner_api: Api, conn: ConnectorApi) -> None:
    token_id = owner_api.get("/settings/connector").json()["tokens"][0]["id"]
    assert owner_api.post(f"/settings/connector/tokens/{token_id}/revoke").status_code == 200
    r = conn.get("/courses")
    assert r.status_code == 401 and r.json()["code"] == "connector_token_invalid"


def test_daily_limit_scales_with_owner_percentage(
    owner_api: Api, conn: ConnectorApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "connector_daily_requests_default", 10)
    assert (
        owner_api.client.put(
            "/api/v1/settings/connector", json={"limit_percent": 30}, headers=owner_api.headers()
        ).json()["daily_limit"]
        == 3
    )
    assert [conn.get("/courses").status_code for _ in range(4)] == [200, 200, 200, 429]
    assert conn.get("/courses").json()["code"] == "connector_daily_limit"
    assert owner_api.get("/settings/connector").json()["used_today"] == 5


def test_outline_and_sections_mark_learner_material_as_untrusted(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    outline = conn.get(f"/courses/{ids['course_id']}/outline").json()
    assert outline["concepts"][0]["source_section_ids"] and outline["sources"][0]["parse_state"] == "ready"
    section = conn.get(f"/sections/{ids['section_ids'][1]}").json()
    assert section["content_kind"] == "learner_material" and "Glycolysis" in section["text"]
    hits = conn.get("/sources/search", q="mitochondrial").json()["hits"]
    assert hits and hits[0]["citation_label"] == "§ Citric acid cycle"


def test_t26_answer_form_capture_is_exact_and_transcription_is_flagged(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    typed = "Glikoliza: citoplazma → 2× piruvat.\n  (my own words)"
    form = conn.post(
        "/attempts",
        {
            "question_id": ids["question_id"],
            "client_request_id": str(uuid.uuid4()),
            "answer_text": typed,
            "captured_via": "answer_form",
        },
    )
    chat = conn.post(
        "/attempts",
        {
            "question_id": ids["question_id"],
            "client_request_id": str(uuid.uuid4()),
            "answer_text": "copied by Claude",
            "captured_via": "assistant_transcription",
        },
    )
    assert form.status_code == chat.status_code == 201
    stored = owner_api.get(f"/attempts/{form.json()['attempt_id']}").json()
    assert stored["answer_text"] == typed and stored["captured_via"] == "answer_form"
    assert owner_api.get(f"/attempts/{chat.json()['attempt_id']}").json()["captured_via"] == "assistant_transcription"


def _answered(owner_api: Api, conn: ConnectorApi) -> tuple[dict[str, Any], str]:
    ids = owner_api.course_with_question()
    attempt = conn.post(
        "/attempts",
        {
            "question_id": ids["question_id"],
            "client_request_id": str(uuid.uuid4()),
            "answer_text": "Glycolysis is in the cytoplasm.",
            "captured_via": "answer_form",
        },
    )
    return ids, attempt.json()["attempt_id"]


def test_grading_context_includes_rubric_and_cited_sources(owner_api: Api, conn: ConnectorApi) -> None:
    ids, attempt_id = _answered(owner_api, conn)
    ctx = conn.get(f"/attempts/{attempt_id}").json()
    assert ctx["question"]["rubric"]["expected_points"]
    assert {s["section_id"] for s in ctx["sources"]} == set(ids["section_ids"][:2])


def test_claude_assessment_is_validated_scheduled_and_not_duplicated(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    ids, attempt_id = _answered(owner_api, conn)
    r = conn.post(
        f"/attempts/{attempt_id}/assessments",
        {
            "status": "final",
            "grade": 3,
            "confidence": "high",
            "feedback": "Correct and justified.",
            "evidence_refs": [ids["section_ids"][1]],
            "model_name": "Claude Sonnet 5.5",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assessment = body["assessments"][0]
    assert assessment["provider"] == "claude_app" and assessment["model_reported_by"] == "assistant"
    assert assessment["simulated"] is False and body["status"] == "evaluated"
    assert body["schedule"][0]["reason"] == "First practice recorded; first review is the next day."

    again = conn.post(
        f"/attempts/{attempt_id}/assessments",
        {"status": "final", "grade": 4, "confidence": "high", "feedback": "Even better."},
    )
    assert again.status_code == 409 and again.json()["code"] == "already_assessed"


def test_t27_fabricated_connector_evidence_is_dropped_and_downgraded(owner_api: Api, conn: ConnectorApi) -> None:
    _, attempt_id = _answered(owner_api, conn)
    r = conn.post(
        f"/attempts/{attempt_id}/assessments",
        {
            "status": "final",
            "grade": 4,
            "confidence": "high",
            "feedback": "See page 99.",
            "evidence_refs": [str(uuid.uuid4()), "page-99"],
        },
    )
    a = r.json()["assessments"][0]
    assert a["status"] == "provisional" and a["evidence_refs"] == []
    assert "unknown_evidence_refs_dropped" in a["factuality_flags"]


def test_inconsistent_assessment_is_rejected(owner_api: Api, conn: ConnectorApi) -> None:
    _, attempt_id = _answered(owner_api, conn)
    r = conn.post(
        f"/attempts/{attempt_id}/assessments", {"status": "final", "grade": None, "confidence": "high", "feedback": "?"}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_assessment"
    assert owner_api.get(f"/attempts/{attempt_id}").json()["assessments"] == []


def test_connector_questions_keep_provenance_and_validate_refs(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    good = {
        "concept_ids": [ids["concept_id"]],
        "bloom_level": 5,
        "prompt": "Evaluate the claim …",
        "expected_points": ["criterion"],
        "source_refs": [ids["section_ids"][1]],
    }
    refused = conn.post("/questions", {"course_id": ids["course_id"], "questions": [good]})
    assert refused.status_code == 409 and refused.json()["code"] == "concepts_not_studied"
    conn.post("/concepts/known", {"concept_ids": [ids["concept_id"]], "reason": "covered in lectures"})
    r = conn.post("/questions", {"course_id": ids["course_id"], "questions": [good], "model_name": "Claude Opus 5.5"})
    assert r.status_code == 201
    q = r.json()["questions"][0]
    assert q["provenance"] == {
        "origin": "claude_connector",
        "model": "Claude Opus 5.5",
        "model_reported_by": "assistant",
    }
    assert q["rubric"] is None
    bad = conn.post("/questions", {"course_id": ids["course_id"], "questions": [{**good, "source_refs": ["x"]}]})
    assert bad.status_code == 422


def test_session_summary_is_recorded_once(conn: ConnectorApi, owner_api: Api) -> None:
    session = conn.post("/study-sessions", {"mode": "review"}).json()
    assert conn.post(f"/study-sessions/{session['id']}/summary", {"summary": "Reviewed glycolysis."}).status_code == 200
    again = conn.post(f"/study-sessions/{session['id']}/summary", {"summary": "again"})
    assert again.status_code == 409


def test_notes_are_readable_but_not_writable_through_the_connector(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    owner_api.post(
        "/notes",
        {
            "course_id": ids["course_id"],
            "client_note_id": str(uuid.uuid4()),
            "title": "My words",
            "body": "Glycolysis splits glucose.",
        },
    )
    notes = conn.get("/notes", course_id=ids["course_id"]).json()
    assert notes[0]["body"] == "Glycolysis splits glucose." and notes[0]["content_kind"] == "learner_material"
    assert (
        conn.client.patch(
            f"/api/v1/notes/{notes[0]['id']}", json={"base_revision": 1, "body": "x"}, headers=conn.auth
        ).status_code
        == 401
    )


def test_plan_orders_due_strengthen_explore_with_reasons(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    empty = conn.get("/plan").json()
    assert empty["items"] == [] and empty["message"] == "You're caught up. Continue a topic or browse your library."

    ids = owner_api.course_with_question()
    plan = conn.get("/plan").json()
    assert [(i["category"], i["term"]) for i in plan["items"]] == [("Learn next", "Glycolysis")]

    owner_api.answer(ids["question_id"], kind="dont_know", text="")
    frozen.advance(days=1)
    item = conn.get("/plan").json()["items"][0]
    assert item["category"] == "Review due" and item["why_selected"].startswith("Due today.")
    assert owner_api.get("/planner/today").json()["items"][0]["category"] == "Review due"


def test_claude_can_build_a_course_from_pasted_material(owner_api: Api, conn: ConnectorApi) -> None:
    from recallspring_api.ingest.jobs import run_pending

    from .conftest import BIOLOGY_MD

    course = conn.post("/courses", {"title": "Biology (from Claude)"}).json()
    src = conn.post("/sources/text", {"course_id": course["id"], "title": "Lecture 1", "text": BIOLOGY_MD}).json()
    assert src["parse_state"] == "pending"
    run_pending()
    status = conn.get(f"/sources/{src['id']}").json()
    assert status["parse_state"] == "ready" and "text" not in status["sections"][0]
    glycolysis = next(s["id"] for s in status["sections"] if s["citation_label"] == "§ Glycolysis")

    body = {
        "concepts": [
            {"term": "Glycolysis", "definition_draft": "Glucose → pyruvate", "source_section_ids": [glycolysis]},
            {"term": "Metabolism"},
        ]
    }
    first = conn.post(f"/courses/{course['id']}/concepts", body).json()["concepts"]
    assert [c["created"] for c in first] == [True, True]
    again = conn.post(f"/courses/{course['id']}/concepts", {"concepts": [{"term": "glycolysis"}]}).json()
    assert again["concepts"][0] == {
        "id": first[0]["id"],
        "term": "Glycolysis",
        "created": False,
        "source_section_ids": [],
    }
    concepts = {c["term"]: c for c in owner_api.get(f"/courses/{course['id']}/concepts").json()}
    assert concepts["Glycolysis"]["source_confidence"] == "medium"
    assert concepts["Glycolysis"]["source_section_ids"] == [glycolysis]
    assert concepts["Metabolism"]["source_confidence"] == "inferred"
    bad = conn.post(
        f"/courses/{course['id']}/concepts", {"concepts": [{"term": "X", "source_section_ids": [str(uuid.uuid4())]}]}
    )
    assert bad.status_code == 422


def test_connector_file_import_applies_the_same_upload_checks(conn: ConnectorApi) -> None:
    from .pdfs import make_pdf

    course = conn.post("/courses", {"title": "Imports"}).json()
    headers = {**conn.auth, "Idempotency-Key": str(uuid.uuid4())}
    bad = conn.client.post(
        "/api/v1/connector/sources",
        data={"course_id": course["id"]},
        files={"file": ("tool.exe", b"MZ")},
        headers=headers,
    )
    assert bad.status_code == 415
    headers = {**conn.auth, "Idempotency-Key": str(uuid.uuid4())}
    ok = conn.client.post(
        "/api/v1/connector/sources",
        data={"course_id": course["id"]},
        files={"file": ("lecture.pdf", make_pdf(["Imported through the connector."]))},
        headers=headers,
    )
    assert ok.status_code == 201 and ok.json()["kind"] == "pdf"
