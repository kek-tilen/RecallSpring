"""Plan v1 (study targets, maintenance, capacity, availability, exam profiles) and kolokvij simulations."""

from __future__ import annotations

import uuid
from typing import Any

from recallspring_api.ingest.jobs import run_pending

from .conftest import Api, ConnectorApi, FrozenClock
from .pdfs import make_pdf


def course_with_concepts(
    api: Api, c: ConnectorApi, terms: list[str], known: bool = False, title: str = "Komunikacijska varnost"
) -> tuple[str, dict[str, str]]:
    course = c.post("/courses", {"title": title}).json()["id"]
    created = c.post(f"/courses/{course}/concepts", {"concepts": [{"term": t} for t in terms]}).json()["concepts"]
    ids = {x["term"]: x["id"] for x in created}
    if known:
        assert c.post("/concepts/known", {"concept_ids": list(ids.values()), "reason": "lectures"}).status_code == 200
    return course, ids


def target(c: ConnectorApi, course: str, name: str, due: str, scope: list[dict[str, Any]], **extra: Any) -> dict:
    r = c.post(
        "/targets",
        {
            "course_id": course,
            "kind": "kolokvij",
            "name": name,
            "due_date": due,
            "scope_description": f"{name}: as described by me",
            "scope": scope,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def question_for(api: Api, course: str, concept: str) -> str:
    r = api.post("/questions", {"course_id": course, "concept_ids": [concept], "bloom_level": 3, "prompt": "?"})
    return r.json()["id"]


# ---------------------------------------------------------------- context and targets


def test_context_asks_what_the_learner_prepares_for_until_a_target_exists(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap", "TCP"])
    ctx = conn.get(f"/courses/{course}/context").json()
    assert ctx["needs_setup"] is True and ctx["active_target"] is None and len(ctx["ask_learner"]) == 5
    assert "From which material to which material" in ctx["ask_learner"][2]

    target(
        conn,
        course,
        "2. kolokvij",
        "2026-12-03",
        [{"kind": "concept", "concept_id": ids["Nmap"]}],
        notes="Only calculations and scenarios",
    )
    ctx = conn.get(f"/courses/{course}/context").json()
    active = ctx["active_target"]
    assert ctx["needs_setup"] is False and ctx["ask_learner"] == []
    assert active["days_left"] == 14 and active["concepts_in_scope"] == 1
    assert active["scope_description"] == "2. kolokvij: as described by me" and active["notes"].startswith("Only")
    assert "75 %" in ctx["rules"][2] and "Learn first" in ctx["rules"][0]


def test_page_range_scope_resolves_to_concepts_on_those_pages(owner_api: Api, conn: ConnectorApi) -> None:
    course = conn.post("/courses", {"title": "KV"}).json()["id"]
    pdf = make_pdf(["Page one about Nmap scanning.", "Page two about TCP handshakes.", "Page three about TLS."])
    src = owner_api.upload(course, "predavanja.pdf", pdf).json()
    run_pending()
    sections = {s["page"]: s["id"] for s in conn.get(f"/sources/{src['id']}").json()["sections"]}
    conn.post(
        f"/courses/{course}/concepts",
        {
            "concepts": [
                {"term": "Nmap", "source_section_ids": [sections[1]]},
                {"term": "TCP", "source_section_ids": [sections[2]]},
                {"term": "TLS", "source_section_ids": [sections[3]]},
            ]
        },
    )
    t = target(
        conn,
        course,
        "1. kolokvij",
        "2026-12-10",
        [{"kind": "pages", "source_id": src["id"], "page_from": 1, "page_to": 2}],
    )
    assert t["concepts_in_scope"] == 2 and t["scope"][0]["pages"] == [1, 2]


def test_scope_must_belong_to_the_course(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["A"])
    _, other_ids = course_with_concepts(owner_api, conn, ["B"], title="Digitalna forenzika")
    r = conn.post(
        "/targets",
        {
            "course_id": course,
            "kind": "izpit",
            "name": "Izpit",
            "due_date": "2027-01-20",
            "scope_description": "vse",
            "scope": [{"kind": "concept", "concept_id": other_ids["B"]}],
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_scope"


# ---------------------------------------------------------------- plan v1


def test_passed_kolokvij_goes_to_maintenance_and_the_next_one_gets_priority(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Firewalls", "Nmap", "Outside scope"])
    k1 = target(conn, course, "1. kolokvij", "2026-11-18", [{"kind": "concept", "concept_id": ids["Firewalls"]}])
    target(conn, course, "2. kolokvij", "2026-11-29", [{"kind": "concept", "concept_id": ids["Nmap"]}])
    assert conn.post(f"/targets/{k1['id']}/update", {"status": "passed", "result": "8/10"}).status_code == 200
    owner_api.answer(question_for(owner_api, course, ids["Firewalls"]), kind="dont_know", text="")
    frozen.advance(days=1)  # Firewalls is now due

    plan = conn.get("/plan").json()
    cats = [(i["category"], i["term"]) for i in plan["items"]]
    assert cats == [("Learn next", "Nmap"), ("Maintain", "Firewalls")]
    assert "Maintenance of 1. kolokvij material" in plan["items"][1]["why_selected"]
    assert "Counts for 2. kolokvij in 9 days." in plan["items"][0]["why_selected"]
    assert plan["targets"][0]["target"] == "2. kolokvij" and plan["available_minutes"] == 60  # Friday default
    only_course = conn.get("/plan", course_id=course).json()
    assert [i["term"] for i in only_course["items"]] == ["Nmap", "Firewalls"]


def test_capacity_check_warns_when_time_is_short(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, ids = course_with_concepts(owner_api, conn, [f"Concept {i}" for i in range(10)])
    target(conn, course, "1. kolokvij", "2026-11-21", [])  # whole course, Thursday + Friday left
    cap = conn.get("/plan").json()["targets"][0]
    assert cap["remaining_minutes"] == 180 and cap["available_minutes"] == 102 and cap["status"] == "at_risk"
    assert "Not enough time" in cap["message"] and cap["bands"]["not_started"] == 10


def test_availability_override_sets_todays_minutes(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course_with_concepts(owner_api, conn, ["A", "B", "C"])
    r = conn.post("/availability", {"day": "2026-11-19", "minutes": 10, "note": "busy day"})
    assert r.status_code == 200
    plan = conn.get("/plan").json()
    assert plan["available_minutes"] == 10 and len(plan["items"]) == 1  # always at least one item
    conn.post("/availability", {"weekly_minutes": [30, 30, 30, 30, 30, 120, 120]})
    assert owner_api.get("/settings/study").json()["weekly_minutes"][5] == 120


def test_exam_profile_weight_raises_a_topic(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Alpha", "Zeta"], known=True)
    t = target(conn, course, "Izpit", "2026-12-20", [])
    r = conn.post(
        f"/targets/{t['id']}/profile",
        {
            "item_types": [{"type": "scenario", "share": 0.6}, {"type": "mcq", "share": 0.4}],
            "bloom_mix": {"3": 0.5, "4": 0.5},
            "topic_weights": [{"label": "Zeta", "concept_id": ids["Zeta"], "weight": 2.0}],
            "example_items": ["Analyse given scan output"],
            "model_name": "Claude Sonnet 5.5",
        },
    )
    assert r.status_code == 201 and r.json()["profile"]["item_types"][0]["type"] == "scenario"
    items = conn.get("/plan").json()["items"]
    assert [i["term"] for i in items] == ["Zeta", "Alpha"]
    assert "Frequent topic on past papers." in items[0]["why_selected"]


def test_learner_difficulty_rating_is_not_overwritten_by_claude(owner_api: Api, conn: ConnectorApi) -> None:
    _, ids = course_with_concepts(owner_api, conn, ["Crypto"])
    conn.post(
        "/concepts/difficulty", {"rated_by": "learner", "items": [{"concept_id": ids["Crypto"], "difficulty": 5}]}
    )
    r = conn.post(
        "/concepts/difficulty", {"rated_by": "claude", "items": [{"concept_id": ids["Crypto"], "difficulty": 2}]}
    )
    assert r.json()["concepts"][0] == {"concept_id": ids["Crypto"], "difficulty": 5, "kept": "learner"}
    item = conn.get("/plan").json()["items"][0]
    assert item["difficulty"] == 5 and item["difficulty_source"] == "learner" and item["estimated_minutes"] == 14


def test_owner_study_settings_are_validated(owner_api: Api) -> None:
    r = owner_api.client.put(
        "/api/v1/settings/study", json={"maintenance_percent": 20, "style_percent": 70}, headers=owner_api.headers()
    )
    assert r.status_code == 200 and r.json()["maintenance_percent"] == 20
    bad = owner_api.client.put("/api/v1/settings/study", json={"maintenance_percent": 80}, headers=owner_api.headers())
    assert bad.status_code == 422


# ---------------------------------------------------------------- kolokvij simulations


def make_quiz(c: ConnectorApi, course: str, concept: str, **extra: Any) -> dict:
    items = [
        {
            "type": "mcq",
            "prompt": "Which scan is easiest to detect?",
            "concept_ids": [concept],
            "options": [{"key": "A", "text": "-sT"}, {"key": "B", "text": "-sF"}],
            "correct_option": "A",
            "points": 1,
        },
        {
            "type": "mcq",
            "prompt": "Which flag does FIN scanning set?",
            "concept_ids": [concept],
            "options": [{"key": "A", "text": "SYN"}, {"key": "B", "text": "FIN"}],
            "correct_option": "B",
            "points": 1,
        },
        {
            "type": "open",
            "prompt": "Explain why -sF cannot tell open from filtered.",
            "concept_ids": [concept],
            "expected_points": ["no reply from open and filtered ports"],
            "points": 4,
            "bloom_level": 4,
            "style": "deeper",
        },
        {"type": "open", "prompt": "Name two Nmap timing templates.", "concept_ids": [concept], "points": 2},
    ]
    r = c.post(
        "/quizzes",
        {
            "course_id": course,
            "title": "Simulacija 2. kolokvija",
            "items": items,
            "model_name": "Claude Sonnet 5.5",
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_simulation_flow_persists_answers_grades_mcq_and_awaits_claude(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    quiz = make_quiz(conn, course, ids["Nmap"], time_limit_minutes=45)
    qid = quiz["quiz_id"]

    form = conn.post(f"/quizzes/{qid}/open").json()
    assert form["deadline"].startswith("2026-11-19T16:45") and len(form["items"]) == 4
    assert all("correct_option" not in i and "expected_points" not in i for i in form["items"])
    q = [i["question_id"] for i in form["items"]]

    draft = conn.post(f"/quizzes/{qid}/draft", {"answers": [{"question_id": q[0], "option": "A"}]})
    assert draft.status_code == 200 and draft.json()["revision"] == 1
    assert conn.get(f"/quizzes/{qid}").json()["draft"][q[0]]["option"] == "A"

    exact = "Ker ne dobi odgovora ne od odprtih ne od filtriranih vrat.\n  (moje besede)"
    submit = {
        "client_request_id": str(uuid.uuid4()),
        "answers": [{"question_id": q[1], "option": "A"}, {"question_id": q[2], "text": exact}],
    }
    learner = conn.post(f"/quizzes/{qid}/submit", submit).json()
    by_pos = {i["position"]: i for i in learner["items"]}
    assert by_pos[1]["earned"] == 1.0 and by_pos[1]["answer"] == "A) -sT"  # from the saved draft
    assert by_pos[2]["earned"] == 0.0 and by_pos[2]["correct_option"] == "B"
    assert by_pos[3]["earned"] is None and by_pos[3]["answer"] == exact
    assert by_pos[4]["kind"] == "dont_know" and by_pos[4]["earned"] == 0.0
    assert learner["pending_items"] == 1 and learner["complete"] is False and "expected_points" not in by_pos[3]

    again = conn.post(f"/quizzes/{qid}/submit", {**submit, "client_request_id": str(uuid.uuid4())})
    assert again.json()["items"] == learner["items"]  # already submitted: no new attempts
    assert conn.post(f"/quizzes/{qid}/draft", {"answers": []}).status_code == 409

    grading = conn.get(f"/quizzes/{qid}/results").json()
    assert grading["grading_scale"].startswith("RecallSpring grading scale (scale-v1)")
    open_item = next(i for i in grading["items"] if i["position"] == 3)
    assert open_item["expected_points"] == ["no reply from open and filtered ports"]
    attempt = owner_api.get(f"/attempts/{open_item['attempt_id']}").json()
    assert attempt["captured_via"] == "answer_form" and attempt["answer_text"] == exact

    batch = conn.post(
        "/assessments/batch",
        {
            "items": [
                {
                    "attempt_id": open_item["attempt_id"],
                    "status": "final",
                    "grade": 3,
                    "confidence": "high",
                    "feedback": "Correct reasoning.",
                }
            ]
        },
    )
    assert batch.status_code == 200 and batch.json()["results"][0]["grade"] == 3
    final = conn.get(f"/quizzes/{qid}/results").json()
    assert final["complete"] is True and final["earned_points"] == 4.0 and final["max_points"] == 8


def test_invalid_simulations_are_rejected(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    base = {"course_id": course, "title": "x"}
    bad_key = {
        "type": "mcq",
        "prompt": "?",
        "concept_ids": [ids["Nmap"]],
        "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
        "correct_option": "C",
    }
    assert conn.post("/quizzes", {**base, "items": [bad_key]}).json()["code"] == "invalid_mcq"
    open_with_options = {
        "type": "open",
        "prompt": "?",
        "concept_ids": [ids["Nmap"]],
        "options": [{"key": "A", "text": "a"}],
    }
    assert conn.post("/quizzes", {**base, "items": [open_with_options]}).json()["code"] == "invalid_item"
    quiz = make_quiz(conn, course, ids["Nmap"])
    form = conn.get(f"/quizzes/{quiz['quiz_id']}").json()
    r = conn.post(
        f"/quizzes/{quiz['quiz_id']}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [{"question_id": form["items"][0]["question_id"], "option": "H"}],
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_option"


def test_batch_grading_is_all_or_nothing(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    quiz = make_quiz(conn, course, ids["Nmap"])
    form = conn.get(f"/quizzes/{quiz['quiz_id']}").json()
    conn.post(
        f"/quizzes/{quiz['quiz_id']}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [{"question_id": form["items"][2]["question_id"], "text": "Some answer"}],
        },
    )
    open_attempt = next(
        i for i in conn.get(f"/quizzes/{quiz['quiz_id']}/results").json()["items"] if i["position"] == 3
    )["attempt_id"]
    r = conn.post(
        "/assessments/batch",
        {
            "items": [
                {"attempt_id": open_attempt, "status": "final", "grade": 2, "confidence": "high", "feedback": "ok"},
                {"attempt_id": str(uuid.uuid4()), "status": "final", "grade": 2, "confidence": "high", "feedback": "x"},
            ]
        },
    )
    assert r.status_code == 404 and r.json()["details"]["index"] == 1
    assert owner_api.get(f"/attempts/{open_attempt}").json()["assessments"] == []
