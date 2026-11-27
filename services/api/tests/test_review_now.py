"""Review now and Grade my answers in… (UI direction, 2026-11-27): the learner answers due concepts in the app, from
questions already linked to them, and an assistant grades the saved answers in one go. Read-only, no model call."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import Question

from .conftest import Api, ConnectorApi, FrozenClock, make_user


def test_review_now_reuses_the_least_recently_answered_question(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    owner_api.answer(ids["question_id"], kind="dont_know", text="")
    # nothing is due yet: no questions
    first = owner_api.get("/reviews/questions", course_id=ids["course_id"]).json()
    assert first["items"] == [] and first["without_question"] == []

    newer = owner_api.post(
        "/questions",
        {
            "course_id": ids["course_id"],
            "concept_ids": [ids["concept_id"]],
            "bloom_level": 2,
            "prompt": "Where does glycolysis take place?",
            "expected_points": ["in the cytoplasm"],
            "source_refs": ids["section_ids"][:1],
        },
    ).json()
    frozen.advance(days=1)
    due = owner_api.get("/reviews/questions", course_id=ids["course_id"]).json()
    # the never-answered question comes before the one answered yesterday
    assert [(i["term"], i["question_id"]) for i in due["items"]] == [("Glycolysis", newer["id"])]

    owner_api.answer(newer["id"])
    again = owner_api.get("/reviews/questions", course_id=ids["course_id"]).json()
    assert [i["question_id"] for i in again["items"]] == [ids["question_id"]]


def test_due_concepts_without_an_open_question_are_listed_apart(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    other = owner_api.post(
        f"/courses/{ids['course_id']}/concepts",
        {
            "term": "Krebs cycle",
            "definition_draft": "Oxidises acetyl-CoA",
            "source_section_ids": ids["section_ids"][:1],
        },
    ).json()
    closed = owner_api.post(
        "/questions",
        {
            "course_id": ids["course_id"],
            "concept_ids": [other["id"]],
            "bloom_level": 1,
            "prompt": "Where does the Krebs cycle run?",
            "expected_points": ["in the mitochondria"],
            "source_refs": ids["section_ids"][:1],
        },
    ).json()
    owner_api.answer(ids["question_id"], kind="dont_know", text="")
    owner_api.answer(closed["id"], kind="dont_know", text="")
    with new_session() as db:  # a closed question is not one to answer from memory
        question = db.get(Question, uuid.UUID(closed["id"]))
        assert question is not None
        question.question_type = "mcq"
        db.commit()
    frozen.advance(days=1)
    due = owner_api.get("/reviews/questions", course_id=ids["course_id"]).json()
    assert [i["term"] for i in due["items"]] == ["Glycolysis"]
    assert due["without_question"] == [{"concept_id": other["id"], "term": "Krebs cycle"}]


def test_saved_answers_wait_for_a_grade_until_an_assistant_grades_them(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    ids = owner_api.course_with_question()
    attempt = owner_api.answer(ids["question_id"]).json()
    owner_api.answer(ids["question_id"], kind="dont_know", text="")  # graded at once: never waits

    waiting = owner_api.get("/answers/waiting").json()
    assert waiting["total"] == 1
    assert [(i["attempt_id"], i["course_title"], i["self_grade"]) for i in waiting["items"]] == [
        (attempt["attempt_id"], "Biology 101", None)
    ]
    assert owner_api.get("/answers/waiting", course_id=ids["course_id"]).json()["total"] == 1

    listed = conn.get("/answers-to-grade").json()
    assert [i["attempt_id"] for i in listed["items"]] == [attempt["attempt_id"]]
    assert "record_assessment" in listed["how_to_grade"]
    context = conn.get(f"/courses/{ids['course_id']}/context").json()
    assert context["answers_to_grade"] == 1 and context["answers_waiting"][0]["question_id"] == ids["question_id"]

    r = conn.post(
        f"/attempts/{attempt['attempt_id']}/assessments",
        {"status": "final", "grade": 3, "confidence": "high", "feedback": "Good.", "evidence_refs": []},
    )
    assert r.status_code == 200, r.text
    assert owner_api.get("/answers/waiting").json() == {"items": [], "total": 0}
    assert conn.get(f"/courses/{ids['course_id']}/context").json()["answers_to_grade"] == 0


def test_another_learner_sees_none_of_it(owner_api: Api, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()
    owner_api.answer(ids["question_id"])
    make_user("intruder")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("intruder").status_code == 200
        assert other.get("/answers/waiting").json()["total"] == 0
        assert other.get("/reviews/questions", course_id=ids["course_id"]).status_code == 404
        assert other.get("/answers/waiting", course_id=ids["course_id"]).status_code == 404
