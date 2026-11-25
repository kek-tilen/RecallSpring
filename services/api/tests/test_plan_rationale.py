"""Why this plan (rationale-v1, ADR-013 §2): from the profile, readiness and today's plan, honest about its limits."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import TargetProfile
from recallspring_api.services.planner import PRIORITY_RULES

from .conftest import Api, ConnectorApi
from .pdfs import make_pdf
from .test_planning_and_simulations import course_with_concepts, target


def _exam(api: Api, conn: ConnectorApi) -> tuple[str, dict[str, str], dict]:
    course, ids = course_with_concepts(api, conn, ["Port scanning", "Ports", "Dorking", "Hashing"])
    assert conn.post("/concepts/known", {"concept_ids": [ids["Ports"]], "reason": "lectures"}).status_code == 200
    return course, ids, target(conn, course, "1. kolokvij", "2026-12-20", [])


def _codes(body: dict) -> list[str]:
    return [limit["code"] for limit in body["limits"]]


def test_the_rationale_ties_the_paper_to_coverage_and_todays_work(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids, t = _exam(owner_api, conn)
    paper = owner_api.upload(course, "kolokvij-2025.pdf", make_pdf(["Old paper"]), category="past_paper").json()
    r = conn.post(
        f"/targets/{t['id']}/profile",
        {
            "papers": [
                {
                    "source_id": paper["id"],
                    "label": "2025",
                    "total_points": 30,
                    "evidence": [{"source_id": paper["id"], "why": "header: 2025", "strength": "strong"}],
                },
                {"label": "2024", "total_points": 30},
            ],
            "bloom_mix": {"3": 0.5, "4": 0.5},
            "topics": [
                {"label": "Dorking", "concept_ids": [ids["Dorking"]], "points": 8, "where": "Q5"},
                {
                    "label": "Scanning",
                    "concept_ids": [ids["Port scanning"], ids["Ports"]],
                    "points": 24,
                    "where": "Q2, p. 1",
                    "papers": ["2025", "2024"],
                },
                {"label": "Firewall rules", "not_in_material": True, "points": 4, "where": "Q6"},
            ],
            "unreadable": ["points of Q4"],
        },
    )
    assert r.status_code == 201, r.text

    body = owner_api.get(f"/targets/{t['id']}/rationale").json()
    assert body["policy_version"] == "rationale-v1" and body["target"]["name"] == "1. kolokvij"
    assert body["profile"]["confirmation"] == "unconfirmed"
    # topics by points, each with its concepts and where it is on the paper
    assert [x["label"] for x in body["topics"]] == ["Scanning", "Dorking", "Firewall rules"]
    scanning = body["topics"][0]
    assert scanning["points"] == 24 and scanning["where"] == "Q2, p. 1" and scanning["papers"] == ["2025", "2024"]
    assert {c["term"]: c["state"] for c in scanning["concepts"]} == {
        "Port scanning": "not_studied",
        "Ports": "not_practised",
    }
    assert scanning["status"] == "in_progress" and body["topics"][2]["status"] == "not_in_material"
    # coverage by points: Scanning is 2/3 of the counted points and half studied; Firewall rules 1/9, not in material
    assert body["coverage"] == {
        "basis": "points",
        "studied_percent": 33,
        "ready_percent": 0,
        "solid_percent": 0,
        "not_in_material_percent": 11,
    }
    # today's work for this course, each item tied to its topic on the paper
    today = {i["term"]: i for i in body["today"]["items"]}
    assert today and today["Port scanning"]["topics"] == [{"label": "Scanning", "points": 24, "share": 0.4}]
    assert "Hashing" not in today or today["Hashing"]["topics"] == []
    assert body["order_rules"] == list(PRIORITY_RULES)
    assert body["fit"]["days_left"] == body["target"]["days_left"]
    # what the basis cannot say, from the server
    assert _codes(body) == ["unconfirmed", "no_copy", "unreadable", "not_in_material", "not_on_paper"]
    by_code = {x["code"]: x["message"] for x in body["limits"]}
    assert "2024" in by_code["no_copy"] and "points of Q4" in by_code["unreadable"]
    assert "Firewall rules (4 points)" in by_code["not_in_material"]
    assert body["not_on_paper"] == {"count": 1, "terms": ["Hashing"]}
    assert body["bloom"]["paper"] == {"3": 0.5, "4": 0.5} and body["bloom"]["paper_above_limit"] == 0
    assert body["note"].startswith("Estimated from your answers")

    # the assistant gets the same, and confirming removes that limit
    conn.post(f"/targets/{t['id']}/profile/confirm", {"profile_id": body["profile"]["id"]})
    again = conn.get(f"/targets/{t['id']}/rationale").json()
    assert "unconfirmed" not in _codes(again) and again["topics"] == body["topics"]


def test_without_an_analysis_the_rationale_says_so(owner_api: Api, conn: ConnectorApi) -> None:
    _, _, t = _exam(owner_api, conn)
    body = owner_api.get(f"/targets/{t['id']}/rationale").json()
    assert body["profile"] is None and body["topics"] == [] and body["coverage"] is None
    assert _codes(body) == ["no_profile"]
    assert body["not_on_paper"] == {"count": 0, "terms": []}  # nothing to compare with


def test_an_older_analysis_names_the_topics_that_had_no_effect(owner_api: Api, conn: ConnectorApi) -> None:
    _, ids, t = _exam(owner_api, conn)
    profile_id = conn.post(f"/targets/{t['id']}/profile", {"bloom_mix": {"3": 1.0}}).json()["profile"]["id"]
    with new_session() as db:  # an analysis stored before ADR-013
        row = db.scalar(select(TargetProfile).where(TargetProfile.id == profile_id))
        assert row is not None
        row.version, row.topics = 1, []
        row.topic_weights = [
            {"label": "Ports", "concept_id": ids["Ports"], "weight": 2.0},
            {"label": "Firewalls", "weight": 1.5},
        ]
        db.commit()
    body = owner_api.get(f"/targets/{t['id']}/rationale").json()
    assert [x["status"] for x in body["topics"]] == ["in_progress", "unmapped"]
    assert _codes(body)[0] == "before_confirmation" and "Firewalls" in body["limits"][0]["message"]
    assert "no_points" in _codes(body)
    assert body["coverage"]["basis"] == "topics" and body["coverage"]["not_in_material_percent"] == 50


def test_paper_levels_above_the_practice_limit_are_named(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids, t = _exam(owner_api, conn)
    limit = owner_api.client.put(
        f"/api/v1/courses/{course}/practice-limit", json={"level": 3}, headers=owner_api.headers()
    )
    assert limit.status_code == 200, limit.text
    topics = [{"label": "Ports", "concept_ids": [ids["Ports"]], "share": 0.5}]
    conn.post(f"/targets/{t['id']}/profile", {"bloom_mix": {"3": 0.6, "5": 0.4}, "topics": topics})
    body = owner_api.get(f"/targets/{t['id']}/rationale").json()
    assert body["bloom"]["practice_limit"] == 3 and body["bloom"]["paper_above_limit"] == 0.4
    assert "About 40 % of the paper's questions are above your practice limit" in body["limits"][-1]["message"]
    assert body["coverage"]["basis"] == "share"


def test_someone_elses_or_an_unknown_exam_is_not_found(owner_api: Api) -> None:
    assert (
        owner_api.client.get(f"/api/v1/targets/{uuid.uuid4()}/rationale", headers=owner_api.headers()).status_code
        == 404
    )
