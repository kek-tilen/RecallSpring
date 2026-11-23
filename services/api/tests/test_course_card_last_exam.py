"""Courses page: with nothing coming up, a course card shows the latest exam behind the learner (owner 2026-11-23)."""

from __future__ import annotations

from .conftest import Api, ConnectorApi
from .test_planning_and_simulations import course_with_concepts, target


def card(api: Api, course: str) -> dict:
    return next(c for c in api.get("/overview/courses").json() if c["id"] == course)


def test_passed_exam_shows_until_a_new_one_is_set(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["A"])
    assert card(owner_api, course)["last_target"] is None  # never had one

    t = target(conn, course, "1. Kolokvij", "2027-01-10", [])
    assert card(owner_api, course)["active_target"]["id"] == t["id"]
    assert card(owner_api, course)["last_target"] is None  # something is coming up

    assert (
        owner_api.client.patch(
            f"/api/v1/targets/{t['id']}", json={"status": "passed"}, headers=owner_api.headers()
        ).status_code
        == 200
    )
    c = card(owner_api, course)
    assert c["active_target"] is None
    assert c["last_target"]["id"] == t["id"] and c["last_target"]["status"] == "passed"

    target(conn, course, "Izpit", "2027-02-01", [])
    assert card(owner_api, course)["last_target"] is None
