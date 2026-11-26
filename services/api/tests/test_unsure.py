"""Unsure on open answers (owner 2026-11-26): the learner can mark an answer they wrote as unsure. It is saved with
the answer, graded normally and only shown, so the assistant can offer more explanation; "I don't know" carries no
mark, and in a check an unsure open answer counts like any other (only a closed guess counts nothing)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import LearningEvent

from .conftest import Api, ConnectorApi
from .test_check_first import check, results, submit
from .test_learning_first import course


def test_a_single_answer_marked_unsure_is_saved_shown_and_graded_normally(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    body = {
        "question_id": ids["question_id"],
        "client_request_id": str(uuid.uuid4()),
        "answer_text": "Glycolysis runs in the cytoplasm, I think.",
        "unsure": True,
    }
    saved = owner_api.post("/attempts", body)
    assert saved.status_code == 201, saved.text
    attempt_id = saved.json()["attempt_id"]
    assert owner_api.get(f"/attempts/{attempt_id}").json()["unsure"] is True

    # the assistant sees the mark with what to do about it, next to the same grading scale
    shown = conn.get(f"/attempts/{attempt_id}").json()
    assert shown["unsure"] is True and "never raises or lowers the grade" in shown["unsure_note"]
    graded = conn.post(
        "/assessments/batch",
        {"items": [{"attempt_id": attempt_id, "status": "final", "grade": 3, "confidence": "high", "feedback": "Ok."}]},
    )
    assert graded.status_code == 200, graded.text
    row = owner_api.get("/attempts", course_id=ids["course_id"]).json()[0]
    assert row["unsure"] is True and row["grade"] == 3 and row["assessment_status"] == "final"

    # "I don't know" never carries the mark, and an answer without it has no note
    key = str(uuid.uuid4())
    dont = owner_api.post(
        "/attempts", {"question_id": ids["question_id"], "client_request_id": key, "kind": "dont_know", "unsure": True}
    ).json()
    assert owner_api.get(f"/attempts/{dont['attempt_id']}").json()["unsure"] is False
    plain = owner_api.answer(ids["question_id"]).json()
    assert "unsure_note" not in conn.get(f"/attempts/{plain['attempt_id']}").json()


def test_the_mark_is_in_the_audit_event(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    owner_api.post(
        "/attempts",
        {"question_id": ids["question_id"], "client_request_id": str(uuid.uuid4()), "answer_text": "x", "unsure": True},
    )
    with new_session() as db:
        events = db.scalars(select(LearningEvent).where(LearningEvent.event_type == "attempt.submitted")).all()
        assert [e.payload["unsure"] for e in events] == [True]


def test_an_unsure_open_answer_in_a_check_counts_like_any_other(owner_api: Api, conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["Open"])
    item = {"type": "open", "prompt": "Explain.", "concept_ids": [ids["Open"]], "expected_points": ["the main idea"]}
    qid, q = check(conn, cid, [item])
    draft = conn.post(f"/quizzes/{qid}/draft", {"answers": [{"question_id": q[0], "text": "Maybe…", "unsure": True}]})
    assert draft.status_code == 200, draft.text
    assert conn.get(f"/quizzes/{qid}").json()["draft"][q[0]]["unsure"] is True  # a reload keeps the mark

    shown = submit(conn, qid, [{"question_id": q[0], "text": "The main idea, I think.", "unsure": True}])
    assert (shown["items"][0]["unsure"], shown["items"][0]["guessing"]) == (True, False)
    attempt_id = conn.get(f"/quizzes/{qid}/results").json()["items"][0]["attempt_id"]
    assert conn.get(f"/attempts/{attempt_id}").json()["unsure_note"]
    conn.post(
        "/assessments/batch",
        {"items": [{"attempt_id": attempt_id, "status": "final", "grade": 3, "confidence": "high", "feedback": "Ok."}]},
    )
    assert results(conn, cid) == {"Open": "green"}  # graded normally: one Solid open answer is green
