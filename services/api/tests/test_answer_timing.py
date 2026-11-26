"""Answer timing (ADR-014 §3): RecallSpring's answer forms report how long a question was open, timing never stops an
answer from being saved, and the plan's review estimates follow the learner's own pace once there are enough timed
answers. Time spent only, never learning or mastery."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .conftest import Api, ConnectorApi, FrozenClock
from .test_planning_and_simulations import course_with_concepts, make_quiz

DEFAULTS = {
    "quick": {"minutes": 3, "timed_answers": 0, "source": "default"},
    "standard": {"minutes": 4, "timed_answers": 0, "source": "default"},
    "relearn": {"minutes": 10, "timed_answers": 0, "source": "default"},
}


def save(api: Api | ConnectorApi, owner: Api, question: str, seconds: Any, **extra: Any) -> dict:
    body = {
        "question_id": question,
        "client_request_id": str(uuid.uuid4()),
        "kind": "answer",
        "answer_text": "In the cytoplasm.",
        "answer_seconds": seconds,
        **extra,
    }
    r = api.post("/attempts", body)
    assert r.status_code == 201, r.text
    return owner.get(f"/attempts/{r.json()['attempt_id']}").json()


def mcq(concept: str) -> dict:
    return {
        "type": "mcq",
        "prompt": "Which?",
        "concept_ids": [concept],
        "correct_option": "A",
        "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
    }


def test_answer_forms_keep_the_time_and_chat_transcriptions_have_none(owner_api: Api, conn: ConnectorApi) -> None:
    q = owner_api.course_with_question()["question_id"]
    assert save(owner_api, owner_api, q, 95)["answer_seconds"] == 95
    assert save(conn, owner_api, q, 40, captured_via="answer_form")["answer_seconds"] == 40
    # an assistant typing what the learner said in chat: no form measured anything
    assert save(conn, owner_api, q, 40, captured_via="assistant_transcription")["answer_seconds"] is None

    # timing never stops an answer from being saved: anything else is dropped, a longer time capped at two hours
    for sent, kept in [("soon", None), (0, None), (-3, None), (True, None), (12.7, 12), (99_999, 7200), (None, None)]:
        attempt = save(owner_api, owner_api, q, sent)
        assert attempt["answer_seconds"] == kept, sent
        assert attempt["answer_text"] == "In the cytoplasm."
    raw = json.dumps(
        {"question_id": q, "client_request_id": str(uuid.uuid4()), "answer_text": "x", "answer_seconds": float("inf")}
    )
    r = owner_api.client.post(
        "/api/v1/attempts", content=raw, headers={**owner_api.headers(), "Content-Type": "application/json"}
    )
    assert r.status_code == 201, r.text  # Infinity
    assert owner_api.get(f"/attempts/{r.json()['attempt_id']}").json()["answer_seconds"] is None


def test_the_plan_follows_the_learners_pace_after_ten_timed_answers(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    q = owner_api.course_with_question()["question_id"]  # Bloom 4: a standard review
    assert conn.get("/plan").json()["estimates"] == DEFAULTS

    for seconds in [240, 360] * 4 + [240]:
        save(owner_api, owner_api, q, seconds)
    save(owner_api, owner_api, q, 900, kind="dont_know", answer_text="")  # "I don't know" is not an answer's pace
    nine = conn.get("/plan").json()["estimates"]
    assert nine["standard"] == {"minutes": 4, "timed_answers": 9, "source": "default"}

    save(owner_api, owner_api, q, 360)
    plan = conn.get("/plan").json()
    # median 5 minutes + 2 for the feedback; a relearn keeps the default ratio (2.5 standard reviews)
    assert plan["estimates"] == {
        "quick": DEFAULTS["quick"],
        "standard": {"minutes": 7, "timed_answers": 10, "source": "your_pace"},
        "relearn": {"minutes": 18, "timed_answers": 10, "source": "your_pace"},
    }
    assert owner_api.get("/planner/today").json()["estimates"] == plan["estimates"]

    frozen.advance(days=1)  # the "I don't know" made a review due
    (item,) = [i for i in conn.get("/plan").json()["items"] if i["category"] == "Review due"]
    assert item["depth"] == "standard" and item["estimated_minutes"] == 7 + max(0, item["difficulty"] - 3)


def test_simulations_keep_the_time_per_question_and_check_first_does_not_count(
    owner_api: Api, conn: ConnectorApi
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    qid = make_quiz(conn, course, ids["Nmap"])["quiz_id"]
    q = [i["question_id"] for i in conn.post(f"/quizzes/{qid}/open").json()["items"]]
    draft = conn.post(
        f"/quizzes/{qid}/draft",
        {
            "answers": [
                {"question_id": q[0], "option": "A", "answer_seconds": 40},
                {"question_id": q[3], "answer_seconds": 25},  # read, not answered yet
            ]
        },
    )
    assert draft.status_code == 200, draft.text
    kept = conn.get(f"/quizzes/{qid}").json()["draft"]
    assert kept[q[0]]["answer_seconds"] == 40 and kept[q[3]]["answer_seconds"] == 25

    submit = {
        "client_request_id": str(uuid.uuid4()),
        "answers": [
            {"question_id": q[1], "option": "B", "answer_seconds": 30},
            {"question_id": q[2], "text": "No reply from either.", "answer_seconds": "junk"},
        ],
    }
    assert conn.post(f"/quizzes/{qid}/submit", submit).status_code == 200
    items = conn.get(f"/quizzes/{qid}/results").json()["items"]
    seconds = {i["position"]: owner_api.get(f"/attempts/{i['attempt_id']}").json()["answer_seconds"] for i in items}
    assert seconds == {1: 40, 2: 30, 3: None, 4: 25}  # the first and last from the draft
    assert conn.get("/plan").json()["estimates"]["standard"]["timed_answers"] == 2  # not the "I don't know"

    # a check first measures what the learner already knows, not their pace in practice
    check_course, check_ids = course_with_concepts(owner_api, conn, ["A", "B", "C", "D", "E"], title="Networks")
    check = conn.post(
        "/quizzes",
        {
            "course_id": check_course,
            "title": "Check first",
            "mode": "diagnostic",
            "items": [mcq(c) for c in check_ids.values() for _ in range(2)],
        },
    )
    assert check.status_code == 201, check.text
    check_id = check.json()["quiz_id"]
    check_q = [i["question_id"] for i in conn.get(f"/quizzes/{check_id}").json()["items"]]
    answers = [{"question_id": x, "option": "A", "answer_seconds": 30} for x in check_q]
    body = {"client_request_id": str(uuid.uuid4()), "answers": answers}
    assert conn.post(f"/quizzes/{check_id}/submit", body).status_code == 200
    assert conn.get("/plan").json()["estimates"]["standard"]["timed_answers"] == 2


def test_only_the_last_thirty_timed_answers_count(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    q = owner_api.course_with_question()["question_id"]
    for _ in range(10):
        save(owner_api, owner_api, q, 1200)  # slow at first
    for _ in range(30):
        frozen.advance(minutes=1)
        save(owner_api, owner_api, q, 120)
    assert conn.get("/plan").json()["estimates"]["standard"] == {
        "minutes": 4,
        "timed_answers": 30,
        "source": "your_pace",
    }
