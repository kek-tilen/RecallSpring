"""Simulation retakes (2026-11-26; migration 0036): a new version with the same questions (all, or
only those without full points), earlier versions kept and compared per question, the first version the benchmark,
and a retake on the same day practice only (out of the review schedule)."""

from __future__ import annotations

import uuid

from .conftest import Api, ConnectorApi, FrozenClock
from .test_check_first import submit
from .test_learning_first import course, mcq


def evidence(owner_api: Api, concept_id: str) -> int:
    return owner_api.get(f"/concepts/{concept_id}/detail").json()["review"]["evidence_count"]


def simulation(conn: ConnectorApi, cid: str, concept: str) -> tuple[str, list[str]]:
    body = {"course_id": cid, "title": "Midterm sim", "time_limit_minutes": 20, "items": [mcq(concept), mcq(concept)]}
    quiz = conn.post("/quizzes", body)
    assert quiz.status_code == 201, quiz.text
    qid = quiz.json()["quiz_id"]
    return qid, [i["question_id"] for i in conn.get(f"/quizzes/{qid}").json()["items"]]


def test_retake_the_questions_without_full_points_then_all(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    cid, ids = course(conn, ["Topic"])
    conn.post("/concepts/known", {"concept_ids": [ids["Topic"]], "reason": "Covered in lectures."})
    qid, (q1, q2) = simulation(conn, cid, ids["Topic"])
    assert conn.post(f"/quizzes/{qid}/retake", {"scope": "all"}).json()["code"] == "quiz_not_submitted"
    first = submit(conn, qid, [{"question_id": q1, "option": "A"}, {"question_id": q2, "option": "B"}])
    assert (first["earned_points"], first["version"], first["seen_questions"]) == (1, 1, False)
    before = evidence(owner_api, ids["Topic"])

    # only the question without full points, with a proportional time limit
    made = conn.post(f"/quizzes/{qid}/retake", {"scope": "not_full"})
    assert made.status_code == 201, made.text
    v2 = made.json()
    assert (v2["version"], v2["items"], v2["time_limit_minutes"]) == (2, 1, 10) and "open_quiz" in v2["next"]
    form = conn.get(f"/quizzes/{v2['quiz_id']}").json()
    assert [i["question_id"] for i in form["items"]] == [q2] and form["title"] == "Midterm sim · version 2"

    # the same day: practice only, graded and shown but out of the review schedule
    again = submit(conn, v2["quiz_id"], [{"question_id": q2, "option": "A"}])
    assert (again["earned_points"], again["seen_questions"], again["same_day_practice"]) == (1, True, True)
    assert "practice only" in again["note"] and "benchmark" in again["note"]
    assert evidence(owner_api, ids["Topic"]) == before

    # the comparison: every version per question of the first one
    view = owner_api.get(f"/quizzes/{v2['quiz_id']}").json()
    comparison = view["comparison"]
    assert comparison["benchmark_quiz_id"] == qid
    assert [(v["version"], v["scope"], v["same_day_practice"]) for v in comparison["versions"]] == [
        (1, "first", False),
        (2, "not_full", True),
    ]
    rows = {r["question_id"]: r["versions"] for r in comparison["questions"]}
    assert rows[q1][0]["earned"] == 1 and rows[q1][1] is None
    assert (rows[q2][0]["earned"], rows[q2][1]["earned"]) == (0, 1)
    assert owner_api.get(f"/quizzes/{qid}").json()["earned_points"] == 1  # the first version is unchanged
    assert conn.post(f"/quizzes/{v2['quiz_id']}/retake", {"scope": "not_full"}).json()["code"] == "nothing_to_retake"

    # every question again, the next day: it counts in the schedule
    v3 = owner_api.post(f"/quizzes/{v2['quiz_id']}/retake", {"scope": "all"}).json()
    assert v3["version"] == 3
    frozen.advance(days=1)
    third = submit(conn, v3["quiz_id"], [{"question_id": q1, "option": "A"}, {"question_id": q2, "option": "A"}])
    assert (third["earned_points"], third["same_day_practice"], third["seen_questions"]) == (2, False, True)
    assert evidence(owner_api, ids["Topic"]) == before + 2
    listed = {q["id"]: q for q in owner_api.get("/quizzes", course_id=cid).json()}
    assert (listed[v3["quiz_id"]]["version"], listed[v3["quiz_id"]]["retake_of"]) == (3, qid)


def test_open_answers_must_be_graded_before_retaking_only_the_missed(owner_api: Api, conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["Open"])
    conn.post("/concepts/known", {"concept_ids": [ids["Open"]], "reason": "Covered in lectures."})
    item = {"type": "open", "prompt": "Explain.", "concept_ids": [ids["Open"]], "expected_points": ["the idea"]}
    qid = conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [item]}).json()["quiz_id"]
    question = conn.get(f"/quizzes/{qid}").json()["items"][0]["question_id"]
    submit(conn, qid, [{"question_id": question, "text": "The idea."}])
    assert conn.post(f"/quizzes/{qid}/retake", {"scope": "not_full"}).json()["code"] == "grading_pending"
    assert conn.post(f"/quizzes/{qid}/retake", {"scope": "all"}).status_code == 201
    assert conn.post(f"/quizzes/{qid}/retake", {"scope": "some"}).status_code == 422


def test_a_check_is_not_retaken(conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["Topic"])
    body = {"course_id": cid, "title": "Check", "mode": "diagnostic", "items": [mcq(ids["Topic"])]}
    qid = conn.post("/quizzes", body).json()["quiz_id"]
    question = conn.get(f"/quizzes/{qid}").json()["items"][0]["question_id"]
    submit(conn, qid, [{"question_id": question, "option": "A"}])
    assert conn.post(f"/quizzes/{qid}/retake", {"scope": "all"}).json()["code"] == "not_a_simulation"
    assert conn.post(f"/quizzes/{uuid.uuid4()}/retake", {"scope": "all"}).status_code == 404
