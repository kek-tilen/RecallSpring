"""Personal interests (learning without a deadline) and the focus period: university first by default, a share of
the day or a focus only when the learner chooses it (ADR-007, plan-v2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi, FrozenClock
from .test_planning_and_simulations import course_with_concepts, target

COURSE_TERMS = [f"Statistika {i}" for i in range(12)]  # 12 × 18 min of work: more than 3 days can hold
ML_TERMS = ["Convolution", "Pooling", "Data augmentation"]


def interest(conn: ConnectorApi, title: str = "Machine learning", terms: list[str] = ML_TERMS, **extra: Any) -> str:
    r = conn.post("/courses", {"title": title, "kind": "interest", **extra})
    assert r.status_code == 201 and r.json()["kind"] == "interest", r.text
    course = r.json()["id"]
    assert conn.post(f"/courses/{course}/concepts", {"concepts": [{"term": t} for t in terms]}).status_code == 201
    return course


def setup_behind(owner_api: Api, conn: ConnectorApi) -> tuple[str, dict, str]:
    """A course whose kolokvij in 3 days is at risk, and an interest."""
    course, _ = course_with_concepts(owner_api, conn, COURSE_TERMS, title="Statistika")
    kolokvij = target(conn, course, "1. kolokvij", "2026-11-22", [])
    return course, kolokvij, interest(conn)


def plan(conn: ConnectorApi, **params: Any) -> dict[str, Any]:
    r = conn.get("/plan", **params)
    assert r.status_code == 200, r.text
    return r.json()


def kinds(p: dict[str, Any]) -> list[str]:
    return [i["course_kind"] for i in p["items"]]


def test_an_interest_has_a_goal_instead_of_exams(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    ml = interest(conn)
    ctx = conn.get(f"/courses/{ml}/context").json()
    assert ctx["course"]["kind"] == "interest" and ctx["needs_setup"] is True
    assert ctx["setup_reasons"] == ["no goal is set for this interest"] and len(ctx["ask_learner"]) == 4
    assert "university first" in ctx["ask_learner"][3]

    saved = conn.post(f"/courses/{ml}/goal", {"goal": "Train an image classifier on my own photos."})
    assert saved.status_code == 200 and saved.json()["goal"].startswith("Train an image")
    ctx = conn.get(f"/courses/{ml}/context").json()
    assert ctx["needs_setup"] is False and ctx["goal"].startswith("Train") and ctx["learning"]["not_studied"] == 3
    assert any("no exam" in rule for rule in ctx["rules"])
    listed = {c["id"]: c for c in conn.get("/courses").json()}
    assert listed[ml]["kind"] == "interest" and listed[ml]["goal"].startswith("Train")

    exam = conn.post(
        "/targets",
        {"course_id": ml, "kind": "other", "name": "Kaggle", "due_date": "2026-12-01", "scope_description": "x"},
    )
    assert exam.status_code == 422 and exam.json()["code"] == "interest_has_no_exams"
    filed = conn.post("/courses/organise", {"course_ids": [ml], "semester": "5. semester"})
    assert filed.status_code == 422 and filed.json()["code"] == "interest_not_filed"

    course, _ = course_with_concepts(owner_api, conn, ["Nmap"])
    assert conn.post(f"/courses/{course}/goal", {"goal": "x"}).json()["code"] == "not_an_interest"
    assert conn.get(f"/courses/{course}/context").json()["course"]["kind"] == "course"
    summary = {c["id"]: c for c in owner_api.get("/overview/courses").json()}
    assert summary[ml]["kind"] == "interest" and summary[course]["kind"] == "course"
    with new_session() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "course.goal_changed")) is not None


def test_university_first_gives_interests_only_time_left_while_exams_are_on_track(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, kolokvij, ml = setup_behind(owner_api, conn)

    behind = plan(conn, minutes=120)  # 6 course items take 72 min; 48 min are free, but the kolokvij is at risk
    assert behind["policy_version"] == "plan-v2" and set(kinds(behind)) == {"course"}
    assert behind["targets"][0]["status"] == "at_risk"
    assert behind["interests"]["policy"] == "university_first" and behind["interests"]["planned_minutes"] == 0
    assert "University first: 1. kolokvij (Statistika) is at risk" in behind["interests"]["message"]

    assert conn.post(f"/targets/{kolokvij['id']}/update", {"due_date": "2027-02-01"}).status_code == 200
    on_track = plan(conn, minutes=120)
    assert on_track["targets"][0]["status"] == "ok"
    assert kinds(on_track) == ["course"] * 6 + ["interest"] * 3  # interests after today's course work
    ml_item = on_track["items"][-1]
    assert ml_item["course_title"] == "Machine learning" and "Personal interest" in ml_item["why_selected"]
    assert on_track["interests"]["planned_minutes"] == 36
    assert "your exams are on track, so 36 min" in on_track["interests"]["message"]

    full_day = plan(conn)  # 60 min: the course work fills the day
    assert set(kinds(full_day)) == {"course"} and "lighter days" in full_day["interests"]["message"]

    alone = plan(conn, course_id=ml)  # the learner asked for this interest: no university-first rule
    assert kinds(alone) == ["interest"] * 3 and alone["interests"] is None


def test_a_share_of_the_day_is_kept_for_interests(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, _, ml = setup_behind(owner_api, conn)
    before = plan(conn)["targets"][0]["available_minutes"]

    r = owner_api.client.put("/api/v1/settings/study", json={"interest_percent": 20}, headers=owner_api.headers())
    assert r.status_code == 200 and r.json()["interest_percent"] == 20
    shared = plan(conn)
    assert kinds(shared) == ["course"] * 4 + ["interest"]  # 12 of 60 min kept for interests, even when behind
    assert shared["interests"]["policy"] == "share" and shared["interests"]["reserved_minutes"] == 12
    assert shared["interests"]["message"].startswith("20 % of today (12 min) is kept for your interests.")
    assert "smaller interest share" in shared["interests"]["message"]
    assert shared["targets"][0]["available_minutes"] < before  # the exam check counts only the rest of the day

    too_much = owner_api.client.put(
        "/api/v1/settings/study", json={"interest_percent": 60}, headers=owner_api.headers()
    )
    assert too_much.status_code == 422
    back = conn.post("/availability", {"interest_percent": 0})
    assert back.status_code == 200 and back.json()["interest_percent"] == 0
    assert plan(conn)["interests"]["policy"] == "university_first"


def test_focus_puts_one_interest_first_until_its_day(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, _, ml = setup_behind(owner_api, conn)

    set_focus = conn.post("/focus", {"course_id": ml, "until": "2026-11-21"})
    assert set_focus.status_code == 200 and set_focus.json()["focus"]["until"] == "2026-11-21"
    focused = plan(conn)
    assert kinds(focused) == ["interest"] * 3 + ["course"] * 2  # focus first, other work gets the time left
    assert all(i["focus"] for i in focused["items"][:3])
    assert focused["items"][0]["why_selected"].startswith("Focus: you chose Machine learning until 2026-11-21.")
    assert focused["focus"]["course_title"] == "Machine learning"
    assert "Meanwhile 1. kolokvij (Statistika) is at risk" in focused["focus"]["message"]
    capacity = focused["targets"][0]
    assert capacity["available_minutes"] == 0 and "Days of your focus on Machine learning" in capacity["message"]
    assert owner_api.get("/settings/study").json()["focus"]["course_title"] == "Machine learning"

    # A focus on the course replaces the one on the interest: at most one focus at a time.
    assert conn.post("/focus", {"course_id": course}).json()["focus"]["until"] == "2026-11-19"
    assert plan(conn)["items"][0]["course_title"] == "Statistika"
    assert owner_api.get("/settings/study").json()["focus"]["course_id"] == course

    assert conn.post("/focus", {"course_id": ml, "until": "2026-11-18"}).json()["code"] == "focus_in_past"
    assert conn.post("/focus", {"course_id": ml, "until": "2027-03-01"}).json()["code"] == "focus_too_long"
    owner_api.patch(f"/courses/{ml}", {"archived": True})
    assert conn.post("/focus", {"course_id": ml}).json()["code"] == "course_not_active"
    owner_api.patch(f"/courses/{ml}", {"archived": False})

    frozen.advance(days=1)  # the focus on the course was for one day only
    assert plan(conn)["focus"] is None and owner_api.get("/settings/study").json()["focus"] is None

    r = owner_api.client.put(
        "/api/v1/settings/focus", json={"course_id": ml, "until": "2026-11-22"}, headers=owner_api.headers()
    )
    assert r.status_code == 200 and r.json()["focus"]["kind"] == "interest"
    assert conn.post("/focus", {"course_id": None}).json()["focus"] is None
    assert plan(conn)["focus"] is None
    with new_session() as db:
        changes = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "study.focus_changed")))
    assert len(changes) == 4 and changes[-1].details["to"] is None


def test_a_course_becomes_an_interest_only_without_upcoming_exams(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], title="Python")
    kolokvij = target(conn, course, "1. kolokvij", "2026-12-01", [])
    conn.post("/courses/organise", {"course_ids": [course], "semester": "5. semester"})
    refused = owner_api.patch(f"/courses/{course}", {"kind": "interest"})
    assert refused.status_code == 409 and refused.json()["code"] == "course_has_exams"

    assert conn.post(f"/targets/{kolokvij['id']}/update", {"status": "passed", "result": "9"}).status_code == 200
    changed = owner_api.patch(f"/courses/{course}", {"kind": "interest"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["kind"] == "interest" and changed.json()["group_id"] is None  # leaves its semester
    groups = owner_api.get("/groups").json()
    filed = owner_api.patch(f"/courses/{course}", {"group_id": groups[0]["id"]})
    assert filed.status_code == 422 and filed.json()["code"] == "interest_not_filed"
    assert owner_api.patch(f"/courses/{course}", {"kind": "course"}).json()["kind"] == "course"
