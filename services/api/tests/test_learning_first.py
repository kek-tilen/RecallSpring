"""Learning first (ADR-006): study before practice, summaries as notes, self-report, diagnostic pre-tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.ingest.jobs import run_pending
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi, FrozenClock
from .pdfs import make_pdf


def course(c: ConnectorApi, terms: list[str]) -> tuple[str, dict[str, str]]:
    cid = c.post("/courses", {"title": "Kibernetska varnost"}).json()["id"]
    made = c.post(f"/courses/{cid}/concepts", {"concepts": [{"term": t} for t in terms]}).json()["concepts"]
    return cid, {m["term"]: m["id"] for m in made}


def mcq(concept: str, correct: str = "A") -> dict:
    return {
        "type": "mcq",
        "prompt": "Which?",
        "concept_ids": [concept],
        "correct_option": correct,
        "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
    }


def test_practice_is_refused_until_the_material_is_studied(owner_api: Api, conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["Nmap", "TCP"])
    practice = conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [mcq(ids["Nmap"])]})
    assert practice.status_code == 409 and practice.json()["code"] == "concepts_not_studied"
    assert practice.json()["details"]["concepts"] == [{"id": ids["Nmap"], "term": "Nmap"}]
    assert "diagnostic" in practice.json()["message"]

    summary = "Nmap pošlje SYN; odprta vrata vrnejo SYN/ACK.\n  (moje besede)"
    saved = conn.post(
        "/learning",
        {
            "course_id": cid,
            "concept_ids": [ids["Nmap"]],
            "title": "Nmap – povzetek",
            "text": summary,
            "client_request_id": str(uuid.uuid4()),
        },
    )
    assert saved.status_code == 201 and saved.json()["concepts"][0]["study_status"] == "studied"
    note = owner_api.get(f"/notes/{saved.json()['note_id']}").json()
    assert note["body"] == summary and note["title"] == "Nmap – povzetek"
    assert conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [mcq(ids["Nmap"])]}).status_code == 201

    outline = {c["term"]: c for c in conn.get(f"/courses/{cid}/outline").json()["concepts"]}
    assert outline["Nmap"]["study_status"] == "studied" and outline["TCP"]["study_status"] == "not_studied"


def test_learning_summary_can_be_skipped_and_is_idempotent(conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["TLS"])
    body = {
        "course_id": cid,
        "concept_ids": [ids["TLS"]],
        "title": "TLS",
        "text": "  ",
        "client_request_id": str(uuid.uuid4()),
    }
    key = str(uuid.uuid4())
    first, again = conn.post("/learning", body, key=key), conn.post("/learning", body, key=key)
    assert first.json() == again.json() and first.json()["note_id"] is None
    assert first.json()["concepts"][0]["study_status"] == "studied"


def test_self_reported_knowledge_is_audited_and_allows_practice(conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["Firewalls"])
    r = conn.post("/concepts/known", {"concept_ids": [ids["Firewalls"]], "reason": "Covered in lectures 1-3"})
    assert r.json()["concepts"][0]["study_status"] == "known"
    with new_session() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "concepts.marked_known"))
        assert event is not None and event.details["reason"] == "Covered in lectures 1-3"
    assert conn.post("/quizzes", {"course_id": cid, "title": "S", "items": [mcq(ids["Firewalls"])]}).status_code == 201
    item = conn.get("/plan").json()["items"][0]
    assert item["category"] == "Practice" and item["study_status"] == "known"


def test_diagnostic_pretest_never_schedules_reviews_and_marks_shown_concepts_known(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    cid, ids = course(conn, ["Shown", "Missed", "Open"])
    quiz = conn.post(
        "/quizzes",
        {
            "course_id": cid,
            "title": "Diagnostika",
            "mode": "diagnostic",
            "items": [
                mcq(ids["Shown"]),
                mcq(ids["Missed"]),
                {
                    "type": "open",
                    "prompt": "Explain.",
                    "concept_ids": [ids["Open"]],
                    "expected_points": ["the main idea"],
                    "points": 2,
                },
            ],
        },
    )
    assert quiz.status_code == 201
    qid = quiz.json()["quiz_id"]
    q = [i["question_id"] for i in conn.get(f"/quizzes/{qid}").json()["items"]]
    learner = conn.post(
        f"/quizzes/{qid}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [
                {"question_id": q[0], "option": "A"},
                {"question_id": q[1], "option": "B"},
                {"question_id": q[2], "text": "Because of the handshake."},
            ],
        },
    ).json()
    assert learner["mode"] == "diagnostic" and "does not change your review schedule" in learner["note"]

    status = {c["term"]: c["study_status"] for c in conn.get(f"/courses/{cid}/outline").json()["concepts"]}
    assert status == {"Shown": "known", "Missed": "not_studied", "Open": "not_studied"}  # open answer not graded yet
    assert owner_api.get("/reviews/due", horizon_days=30).json()["items"] == []  # diagnostics never schedule

    open_attempt = next(i for i in conn.get(f"/quizzes/{qid}/results").json()["items"] if i["type"] == "open")
    conn.post(
        "/assessments/batch",
        {
            "items": [
                {
                    "attempt_id": open_attempt["attempt_id"],
                    "status": "final",
                    "grade": 4,
                    "confidence": "high",
                    "feedback": "Clear.",
                }
            ]
        },
    )
    status = {c["term"]: c["study_status"] for c in conn.get(f"/courses/{cid}/outline").json()["concepts"]}
    assert status["Open"] == "known" and status["Missed"] == "not_studied"
    assert owner_api.get("/reviews/due", horizon_days=30).json()["items"] == []
    cats = {i["term"]: i["category"] for i in conn.get("/plan").json()["items"]}
    assert cats["Missed"] == "Learn next" and cats["Shown"] == "Practice"


def test_new_material_is_learned_in_the_order_of_the_material(owner_api: Api, conn: ConnectorApi) -> None:
    cid = conn.post("/courses", {"title": "KV"}).json()["id"]
    src = owner_api.upload(
        cid, "predavanja.pdf", make_pdf(["Lecture one: scanning basics.", "Lecture two: TCP flags in detail."])
    ).json()
    run_pending()
    pages = {s["page"]: s["id"] for s in conn.get(f"/sources/{src['id']}").json()["sections"]}
    conn.post(
        f"/courses/{cid}/concepts",
        {
            "concepts": [
                {"term": "Aardvark flags", "source_section_ids": [pages[2]]},
                {"term": "Zulu scanning", "source_section_ids": [pages[1]]},
            ]
        },
    )
    items = conn.get("/plan").json()["items"]
    assert [i["term"] for i in items] == ["Zulu scanning", "Aardvark flags"]  # page 1 before page 2, not A-Z
    assert items[0]["category"] == "Learn next" and items[0]["sections"][0]["citation_label"] == "p. 1"
    assert "study p. 1" in items[0]["why_selected"]
    ctx = conn.get(f"/courses/{cid}/context").json()
    assert "Learn first" in ctx["rules"][0]
