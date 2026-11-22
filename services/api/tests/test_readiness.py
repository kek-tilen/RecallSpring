"""Exam readiness (readiness-v1) and the weekly review (week-v1): deterministic, from recorded evidence only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from recallspring_api.ingest.jobs import run_pending
from recallspring_api.models import ReviewState
from recallspring_api.services.readiness import concept_state

from .conftest import Api, ConnectorApi, FrozenClock

LECTURE_1 = "# Energy\n\n## ATP\n\nATP stores energy in phosphate bonds.\n\n## NADH\n\nNADH carries electrons.\n"
LECTURE_2 = (
    "# Respiration\n\n## Glycolysis\n\nGlucose is split in the cytoplasm.\n\n## Krebs\n\nIt runs in the matrix.\n"
)


def _course(api: Api, conn: ConnectorApi) -> tuple[str, dict[str, str]]:
    course = api.post("/courses", {"title": "Biology 101"}).json()["id"]
    first = api.paste(course, LECTURE_1, title="Lecture 1").json()["id"]
    second = api.paste(course, LECTURE_2, title="Lecture 2").json()["id"]
    run_pending()
    s1, s2 = api.sections(first), api.sections(second)
    ids = {}
    for term, sections in (
        ("ATP", [s1[1]["id"]]),
        ("NADH", [s1[2]["id"]]),
        ("Glycolysis", [s2[1]["id"]]),
        ("Krebs cycle", [s2[2]["id"]]),
    ):
        r = api.post(f"/courses/{course}/concepts", {"term": term, "source_section_ids": sections})
        assert r.status_code == 201, r.text
        ids[term] = r.json()["id"]
    loose = conn.post(f"/courses/{course}/concepts", {"concepts": [{"term": "Fermentation"}]}).json()["concepts"]
    ids["Fermentation"] = loose[0]["id"]
    return course, ids


def _answer(api: Api, conn: ConnectorApi, course: str, concept: str, grade: int, gaps: list[str] | None = None) -> str:
    question = api.post(
        "/questions", {"course_id": course, "concept_ids": [concept], "bloom_level": 2, "prompt": "Explain it."}
    ).json()["id"]
    attempt = conn.post(
        "/attempts",
        {
            "question_id": question,
            "client_request_id": str(uuid.uuid4()),
            "answer_text": "My answer.",
            "captured_via": "answer_form",
        },
    ).json()["attempt_id"]
    r = conn.post(
        f"/attempts/{attempt}/assessments",
        {"status": "final", "grade": grade, "confidence": "high", "feedback": "Feedback.", "gaps": gaps or []},
    )
    assert r.status_code == 200, r.text
    return attempt


def _target(conn: ConnectorApi, course: str, due: str = "2026-11-29") -> str:
    r = conn.post(
        "/targets",
        {"course_id": course, "kind": "kolokvij", "name": "1. kolokvij", "due_date": due, "scope_description": "All"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_readiness_by_material_with_the_weakest_and_next_steps(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, ids = _course(owner_api, conn)
    known = [ids["ATP"], ids["NADH"], ids["Glycolysis"]]
    assert conn.post("/concepts/known", {"concept_ids": known, "reason": "lectures"}).status_code == 200
    _answer(owner_api, conn, course, ids["ATP"], 1, gaps=["Mixes up ATP and NADH", "No example"])
    _answer(owner_api, conn, course, ids["Glycolysis"], 3)
    target = _target(conn, course)

    r = owner_api.get(f"/targets/{target}/readiness")
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["policy_version"] == "readiness-v1" and view["target"]["days_left"] == 10
    summary = view["summary"]
    assert (summary["concepts"], summary["not_studied"], summary["weak"], summary["not_practised"]) == (5, 2, 1, 1)
    assert (summary["developing"], summary["solid"], summary["ready_percent"]) == (1, 0, 20)
    groups = [(g["title"], [(c["term"], c["state"]) for c in g["concepts"]]) for g in view["groups"]]
    assert [title for title, _ in groups] == ["Lecture 1.md", "Lecture 2.md", "Not linked to material"]
    assert groups[0][1] == [("ATP", "weak"), ("NADH", "not_practised")]
    assert groups[1][1] == [("Glycolysis", "developing"), ("Krebs cycle", "not_studied")]
    assert groups[2][1] == [("Fermentation", "not_studied")]
    atp = view["groups"][0]["concepts"][0]
    assert atp["last_grade"] == 1 and atp["feedback"]["gaps"] == ["Mixes up ATP and NADH", "No example"]
    assert atp["citations"] == ["Lecture 1.md, § ATP"]

    weakest = view["weakest"]
    assert [w["term"] for w in weakest] == ["ATP"]
    assert weakest[0]["reason"] == "Last answer Fragile (1/4)." and weakest[0]["gaps"][0] == "Mixes up ATP and NADH"
    steps = view["next_steps"]
    assert steps[0].startswith("Learn the 2 concepts not studied yet, starting with Lecture 2.md: about 1 a day.")
    assert steps[1].startswith("Strengthen 1 weak concept: ATP.")
    assert steps[2].startswith("Answer one question each on 1 studied concept")
    assert any("timed simulation" in s for s in steps)  # 10 days left, 60 % studied, no simulation yet
    assert view["capacity"]["status"] in ("ok", "tight", "at_risk")

    # Claude gets the same through the connector, by course (its next exam), with less per concept.
    c = conn.get("/readiness", course_id=course).json()
    assert c["summary"] == summary and c["weakest"][0]["gaps"] == ["Mixes up ATP and NADH", "No example"]
    assert set(c["groups"][0]["concepts"][0]) == {"id", "term", "state", "last_grade", "due", "exam_weight"}
    assert conn.get("/readiness", target_id=target).json()["summary"] == summary


def test_readiness_refusals(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, _ = _course(owner_api, conn)
    assert owner_api.get(f"/targets/{uuid.uuid4()}/readiness").status_code == 404
    assert conn.get("/readiness").status_code == 422
    r = conn.get("/readiness", course_id=course)
    assert r.status_code == 409 and r.json()["code"] == "no_upcoming_exam"
    target = _target(conn, course, due="2027-01-20")
    assert conn.get("/readiness", course_id=course).json()["target"]["id"] == target
    empty = owner_api.post("/courses", {"title": "Empty"}).json()["id"]
    later = _target(conn, empty)
    view = owner_api.get(f"/targets/{later}/readiness").json()
    assert view["summary"]["concepts"] == 0 and view["next_steps"][0].startswith("No concepts are in this exam's scope")


def _state(grade: int | None, code: str, step: int = 0, successes: int = 0) -> ReviewState:
    now = datetime(2026, 11, 19, tzinfo=UTC)
    return ReviewState(
        step=step,
        due_at=now,
        last_review_at=now,
        consecutive_successes=successes,
        lapse_count=0,
        evidence_count=max(1, successes),
        policy_version="test",
        due_reason={"grade": grade, "code": code},
        recomputed_at=now,
    )


def test_concept_states() -> None:
    assert concept_state("not_studied", None) == "not_studied"
    assert concept_state("known", None) == "not_practised"
    assert concept_state("studied", _state(2, "partial")) == "weak"
    assert concept_state("studied", _state(4, "lapse")) == "weak"
    assert concept_state("studied", _state(3, "first_evidence")) == "developing"
    assert concept_state("studied", _state(None, "uncertain")) == "developing"
    assert concept_state("studied", _state(4, "success", step=2, successes=3)) == "solid"


def test_weekly_review_counts_the_week_and_the_trend(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, ids = _course(owner_api, conn)
    assert conn.post("/concepts/known", {"concept_ids": [ids["ATP"], ids["NADH"]], "reason": "x"}).status_code == 200
    target = _target(conn, course)
    frozen.set(datetime(2026, 11, 12, 10, 0, tzinfo=UTC))  # the week before
    _answer(owner_api, conn, course, ids["ATP"], 1)
    frozen.set(datetime(2026, 11, 19, 15, 0, tzinfo=UTC))  # Thursday of this week
    session = conn.post("/study-sessions", {"course_id": course, "mode": "new_learning"}).json()["id"]
    _answer(owner_api, conn, course, ids["ATP"], 3)
    _answer(owner_api, conn, course, ids["NADH"], 4)
    frozen.advance(minutes=45)
    assert conn.post(f"/study-sessions/{session}/summary", {"summary": "ATP and NADH"}).status_code == 200
    conn.post("/study-sessions", {"course_id": course, "mode": "review"})  # never closed: not timed

    week: dict[str, Any] = owner_api.get("/overview/week").json()
    assert week["week"] == {
        "start": "2026-11-16",
        "end": "2026-11-22",
        "weeks_ago": 0,
        "is_current": True,
        "days_counted": 4,
    }
    assert week["planned_minutes"] == 240  # Monday to Thursday, 60 min each by default
    assert week["session_minutes"] == 45 and week["sessions"] == {"timed": 1, "untimed": 1}
    assert week["activity"]["answers"] == 2 and week["activity"]["active_days"] == ["2026-11-19"]
    assert week["grades"] == {"count": 2, "average": 3.5, "previous_average": 1.0, "distribution": [0, 0, 0, 1, 1]}
    assert week["courses"][0]["title"] == "Biology 101" and week["courses"][0]["average_grade"] == 3.5
    assert week["reviews"]["overdue"] == 0 and week["reviews"]["due_next_7_days"] >= 1
    exam = week["exams"][0]
    assert exam["id"] == target and exam["concepts"] == 5 and exam["not_studied"] == 3
    assert "Average grade 3.5/4 over 2 graded answers, up from 1.0." in week["summary"]
    assert "About 45 min in 1 study session closed with a summary; 240 min planned." in week["summary"]
    assert any(line.startswith("1. kolokvij (Biology 101) in 10 days: 3 not studied") for line in week["summary"])

    before = owner_api.get("/overview/week", weeks_ago=1).json()
    assert before["week"]["start"] == "2026-11-09" and before["planned_minutes"] == 60 * 5 + 90 * 2
    assert before["grades"]["average"] == 1.0 and before["reviews"] is None and before["exams"] == []
    assert conn.get("/week").json()["grades"] == week["grades"]
    assert owner_api.get("/overview/week", weeks_ago=53).status_code == 422
