"""Check first and the practice limit (owner decisions 2026-11-22): half a green per correct closed answer, a full
green per Solid open answer, guesses count nothing, known concepts get rare reviews, red before yellow in the plan,
and the learner's Bloom limit caps practice, with a warning when the exam paper asks for more."""

from __future__ import annotations

import uuid

from .conftest import Api, ConnectorApi, FrozenClock
from .test_learning_first import course, mcq


def check(conn: ConnectorApi, cid: str, items: list[dict]) -> tuple[str, list[str]]:
    quiz = conn.post("/quizzes", {"course_id": cid, "title": "Check first", "mode": "diagnostic", "items": items})
    assert quiz.status_code == 201, quiz.text
    qid = quiz.json()["quiz_id"]
    return qid, [i["question_id"] for i in conn.get(f"/quizzes/{qid}").json()["items"]]


def submit(conn: ConnectorApi, qid: str, answers: list[dict]) -> dict:
    body = {"client_request_id": str(uuid.uuid4()), "answers": answers}
    return conn.post(f"/quizzes/{qid}/submit", body).json()


def outline(conn: ConnectorApi, cid: str) -> dict:
    return conn.get(f"/courses/{cid}/outline").json()


def results(conn: ConnectorApi, cid: str) -> dict[str, str | None]:
    return {c["term"]: (c["check"]["last"] or {}).get("result") for c in outline(conn, cid)["concepts"]}


def test_two_closed_answers_make_one_green_and_a_guess_counts_nothing(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    cid, ids = course(conn, ["Two", "One", "Three", "Guessed", "Wrong"])
    items = [mcq(ids["Two"]), mcq(ids["Two"]), mcq(ids["One"]), mcq(ids["One"])]
    items += [mcq(ids["Three"])] * 3 + [mcq(ids["Guessed"]), mcq(ids["Guessed"]), mcq(ids["Wrong"])]
    qid, q = check(conn, cid, items)
    answers = [{"question_id": q[i], "option": "A"} for i in range(7)]
    answers[3] = {"question_id": q[3], "option": "B"}  # "One": one of two correct
    answers += [
        {"question_id": q[7], "option": "A", "guessing": True},
        {"question_id": q[8], "option": "A", "guessing": True},
        {"question_id": q[9], "option": "B"},
    ]
    shown = submit(conn, qid, answers)
    assert [i["guessing"] for i in shown["items"]][7:] == [True, True, False]
    assert "marked it as a guess" in shown["items"][7]["feedback"]

    assert results(conn, cid) == {"Two": "green", "One": "yellow", "Three": "green", "Guessed": "red", "Wrong": "red"}
    status = {c["term"]: c["study_status"] for c in outline(conn, cid)["concepts"]}
    assert status == {
        "Two": "known",
        "One": "not_studied",
        "Three": "known",
        "Guessed": "not_studied",
        "Wrong": "not_studied",
    }
    # Three correct closed answers still make one green (rounded down); the ramp does not move.
    # A concept only marked known that the check does not show comes back to be learned first.
    conn.post("/concepts/known", {"concept_ids": [ids["Wrong"]], "reason": "I think I know it."})
    frozen.advance(hours=1)
    qid, q = check(conn, cid, [mcq(ids["Wrong"])])
    submit(conn, qid, [{"question_id": q[0], "option": "B"}])
    assert next(c for c in outline(conn, cid)["concepts"] if c["term"] == "Wrong")["study_status"] == "not_studied"
    three = next(c for c in outline(conn, cid)["concepts"] if c["term"] == "Three")
    assert three["check"]["last"]["greens"] == 1 and three["practice"]["next_level"] == 3


def test_known_concepts_get_rare_reviews_and_the_plan_puts_red_before_yellow(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    cid, ids = course(conn, ["Known", "Partly", "Not yet"])
    qid, q = check(conn, cid, [mcq(ids["Known"]), mcq(ids["Known"]), mcq(ids["Partly"]), mcq(ids["Not yet"])])
    submit(
        conn,
        qid,
        [
            {"question_id": q[0], "option": "A"},
            {"question_id": q[1], "option": "A"},
            {"question_id": q[2], "option": "A"},
            {"question_id": q[3], "option": "B"},
        ],
    )
    assert owner_api.get("/reviews/due", horizon_days=20).json()["items"] == []
    due = owner_api.get("/reviews/due", horizon_days=21).json()["items"]
    assert [i["term"] for i in due] == ["Known"]

    plan = conn.get("/plan", course_id=cid, minutes=180).json()
    learn = [i for i in plan["items"] if i["category"] == "Learn next"]
    assert [i["term"] for i in learn] == ["Not yet", "Partly"]
    assert "only the gaps" in learn[1]["why_selected"] and "optional" in learn[1]["why_selected"]


def test_the_outline_plans_checks_per_chapter_and_for_everything(conn: ConnectorApi) -> None:
    cid, ids = course(conn, [f"C{i:02d}" for i in range(20)])
    view = outline(conn, cid)
    assert "gently" in view["check_first"]["how"]
    (chapter,) = view["check_first"]["chapters"]
    assert len(chapter["concept_ids"]) == 20 and len(chapter["check_concept_ids"]) == 12
    assert chapter["counts"]["unchecked"] == 20
    everything = view["check_first"]["everything"]
    assert everything["scope"] == "the whole course" and len(everything["concept_ids"]) == 15
    first = view["concepts"][0]["check"]
    assert (first["level"], first["item"], first["last"]) == (2, "open", None)  # not studied yet: Understand


def test_the_practice_limit_caps_practice_and_warns_about_the_exam_paper(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    cid, ids = course(conn, ["Topic"])
    conn.post("/concepts/known", {"concept_ids": [ids["Topic"]], "reason": "Covered in lectures."})
    limit = owner_api.put(f"/courses/{cid}/practice-limit", {"level": 4})
    assert limit.status_code == 200 and limit.json()["level"] == 4 and limit.json()["warning"] is None

    high = {**mcq(ids["Topic"]), "bloom_level": 5}
    refused = conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [high]})
    assert refused.status_code == 409 and refused.json()["code"] == "above_practice_limit"
    assert (
        conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [{**high, "bloom_level": 4}]}).status_code
        == 201
    )

    target = conn.post(
        "/targets",
        {
            "course_id": cid,
            "kind": "kolokvij",
            "name": "1st midterm",
            "due_date": "2026-12-20",
            "scope_description": "All",
        },
    ).json()
    profile = conn.post(f"/targets/{target['id']}/profile", {"bloom_mix": {"3": 0.5, "4": 0.2, "5": 0.3}})
    assert profile.status_code in (200, 201), profile.text
    warned = outline(conn, cid)["practice_limit"]
    assert warned["exam_profile_above"]["share"] == 0.3 and "30 %" in warned["warning"]
    kept = owner_api.put(f"/courses/{cid}/practice-limit", {"level": 4, "keep_despite_exam": True}).json()
    assert kept["warning"] is None and kept["exam_profile_above"]["confirmed"] is True

    practice = next(c for c in outline(conn, cid)["concepts"])["practice"]
    assert practice["next_level"] == 3 and "your limit is 4" not in practice["why"]  # nothing solid yet
    owner_api.put(f"/courses/{cid}/practice-limit", {"level": 2})
    assert next(c for c in outline(conn, cid)["concepts"])["practice"]["phase"] == "limited"
