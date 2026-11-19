"""Web-app overview: owner-only read views of everything RecallSpring stores, and the SPA host."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recallspring_api.config import get_settings
from recallspring_api.main import create_app

from .conftest import Api, ConnectorApi, FrozenClock, make_user
from .test_planning_and_simulations import course_with_concepts, make_quiz


def test_dashboard_course_concept_and_history_views(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap", "TCP"], known=False)
    assert conn.post("/concepts/known", {"concept_ids": [ids["Nmap"]], "reason": "lectures"}).status_code == 200
    quiz = make_quiz(conn, course, ids["Nmap"])
    form = conn.post(f"/quizzes/{quiz['quiz_id']}/open").json()
    q = [i["question_id"] for i in form["items"]]
    exact = "Ni odgovora.\n  (moje besede)"
    submitted = conn.post(
        f"/quizzes/{quiz['quiz_id']}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [{"question_id": q[0], "option": "A"}, {"question_id": q[2], "text": exact}],
        },
    )
    assert submitted.status_code == 200

    dash = owner_api.get("/dashboard").json()
    assert dash["counts"]["courses"] == 1 and dash["counts"]["concepts"] == 2 and dash["counts"]["simulations"] == 1
    assert {"plan", "attention", "recent"} <= dash.keys()
    assert any(r["type"] == "quiz.submitted" for r in dash["recent"])

    view = owner_api.get(f"/courses/{course}/overview").json()
    rows = {c["term"]: c for c in view["concepts"]}
    assert rows["Nmap"]["study_status"] == "known" and rows["TCP"]["study_status"] == "not_studied"
    assert rows["Nmap"]["review"] is not None and rows["TCP"]["review"] is None
    assert view["progress"]["study"] == {"not_studied": 1, "studied": 0, "known": 1}
    assert view["quizzes"][0]["items"] == 4 and view["quizzes"][0]["status"] == "submitted"
    assert view["quizzes"][0]["pending_items"] == 1

    summary = owner_api.get("/overview/courses").json()
    assert summary[0]["id"] == course and summary[0]["simulations"] == 1 and summary[0]["progress"]["concepts"] == 2

    detail = owner_api.get(f"/concepts/{ids['Nmap']}/detail").json()
    answers = {a["answer"]: a for a in detail["attempts"]}
    assert answers[exact]["captured_via"] == "answer_form" and answers[exact]["grade"] is None
    assert answers[exact]["quiz"]["id"] == quiz["quiz_id"]
    assert "not a guarantee" in detail["note"]

    sim = owner_api.get(f"/quizzes/{quiz['quiz_id']}").json()
    assert sim["status"] == "submitted" and "expected_points" in next(i for i in sim["items"] if i["type"] == "open")
    assert owner_api.get("/quizzes", course_id=course).json()[0]["id"] == quiz["quiz_id"]

    answers_list = owner_api.get("/attempts", course_id=course).json()
    assert len(answers_list) == 4 and {a["question"] for a in answers_list} >= {"Which scan is easiest to detect?"}

    hist = owner_api.get("/history").json()
    texts = {h["text"] for h in hist}
    assert {"Simulation submitted", "Answer saved", "Concept marked as known"} <= texts
    assert all(not h["type"].startswith("auth.") for h in hist)
    saved = [h for h in hist if h["type"] == "attempt.submitted"]
    assert "Explain why -sF cannot tell open from filtered." in {h["label"] for h in saved}
    # Learning-event payloads never carry the learner's raw text.
    assert all(exact not in (h["detail"] or "") for h in hist)


def test_open_simulation_hides_answer_keys(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    quiz = make_quiz(conn, course, ids["Nmap"])
    view = owner_api.get(f"/quizzes/{quiz['quiz_id']}").json()
    assert view["status"] == "open"
    assert all("correct_option" not in i and "expected_points" not in i for i in view["items"])
    attention = owner_api.get("/dashboard").json()["attention"]
    assert any(a["kind"] == "quiz" and a["id"] == quiz["quiz_id"] for a in attention)


def test_overview_is_owner_scoped_and_needs_a_session(owner_api: Api, conn: ConnectorApi, client: TestClient) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    quiz = make_quiz(conn, course, ids["Nmap"])

    make_user("other")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("other").status_code == 200
        for path in (f"/courses/{course}/overview", f"/concepts/{ids['Nmap']}/detail", f"/quizzes/{quiz['quiz_id']}"):
            r = other.get(path)
            assert r.status_code == 404 and r.json()["code"] == "not_found", path
        assert other.get("/quizzes").json() == [] and other.get("/history").json() == []

    with TestClient(create_app()) as anonymous:
        assert anonymous.get("/api/v1/dashboard").status_code == 401
        # A connector token cannot read the owner-only overview.
        bearer = {"Authorization": conn.auth["Authorization"]}
        assert anonymous.get("/api/v1/dashboard", headers=bearer).status_code == 401


@pytest.fixture
def web_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>RecallSpring</title>", encoding="utf-8")
    (tmp_path / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("RS_WEB_DIST", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_web_app_is_served_with_strict_headers(web_dist: Path) -> None:
    (web_dist.parent / "secret.txt").write_text("outside", encoding="utf-8")
    with TestClient(create_app()) as c:
        index = c.get("/courses/123")
        assert index.status_code == 200 and "RecallSpring" in index.text
        assert "frame-ancestors 'none'" in index.headers["content-security-policy"]
        assert "script-src 'self'" in index.headers["content-security-policy"]
        assert index.headers["x-content-type-options"] == "nosniff"
        asset = c.get("/assets/app-1234.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        assert "secret" not in c.get("/..%2Fsecret.txt").text
        missing_api = c.get("/api/v1/does-not-exist")
        assert missing_api.status_code == 404 and missing_api.json()["code"] == "not_found"
        live = c.get("/api/v1/health/live")
        assert live.status_code == 200 and "content-security-policy" not in live.headers
