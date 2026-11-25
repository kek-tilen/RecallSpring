"""On the paper but not in the material (ADR-013 §5): web sources only with the learner's yes, kept apart from the
course material; and when the assistant shows "Why this plan" on its own (§3)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.ingest.jobs import run_pending
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi
from .test_planning_and_simulations import course_with_concepts, target

NMAP = "## The -A option\n\n-A enables OS detection, version detection, script scanning and traceroute.\n"
LINK = {"url": "https://nmap.org/book/man-misc-options.html", "title": "Nmap reference guide"}


def web_source(conn: ConnectorApi, course: str, **extra: Any) -> Any:
    body = {"course_id": course, "title": "nmap -A", "text": NMAP, "links": [LINK], "learner_agreed": True}
    return conn.post("/sources/web", {**body, **extra})


def test_a_web_source_needs_the_learners_yes_and_is_labelled(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Port scanning"])
    refused = web_source(conn, course, learner_agreed=False)
    assert refused.status_code == 422 and refused.json()["code"] == "learner_not_asked"
    assert web_source(conn, course, links=[{"url": "javascript:alert(1)"}]).status_code == 422
    assert web_source(conn, course, links=[]).status_code == 422
    assert web_source(conn, course, model_said="trust me").status_code == 422  # unknown fields are refused

    r = web_source(conn, course)
    assert r.status_code == 201, r.text
    source = r.json()
    assert source["origin"] == "web" and source["filename"] == "From the web - nmap -A.md"
    assert source["web_links"] == [{**LINK, "read_on": source["uploaded_at"][:10]}]
    run_pending()
    sections = owner_api.get(f"/sources/{source['id']}/sections").json()["sections"]
    text = " ".join(s["text"] for s in sections)
    assert "From the web, not from your course material." in text and LINK["url"] in text and "-A enables" in text
    # the web app gets the same
    assert owner_api.get(f"/sources/{source['id']}").json()["web_links"][0]["url"] == LINK["url"]
    with new_session() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "source.web_added"))
        assert event is not None and event.details == {"links": [LINK["url"]]}


def test_a_title_with_a_slash_keeps_its_name(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Port scanning"])
    r = web_source(conn, course, title="nmap -A / -sV", text="Other text.")
    assert r.status_code == 201 and r.json()["filename"] == "From the web - nmap -A - -sV.md"


def test_topics_backed_only_by_the_web_are_named_in_the_rationale(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Port scanning"])
    source = web_source(conn, course).json()
    run_pending()
    section = conn.get(f"/sources/{source['id']}").json()["sections"][0]["id"]
    created = conn.post(
        f"/courses/{course}/concepts", {"concepts": [{"term": "nmap -A", "source_section_ids": [section]}]}
    ).json()["concepts"]
    t = target(conn, course, "1. kolokvij", "2026-12-20", [])
    topics = [
        {"label": "Scan options", "concept_ids": [created[0]["id"]], "points": 6, "where": "Q3"},
        {"label": "Scanning", "concept_ids": [ids["Port scanning"]], "points": 10, "where": "Q1"},
        {"label": "Firewall rules", "not_in_material": True, "points": 4, "where": "Q6"},
    ]
    assert conn.post(f"/targets/{t['id']}/profile", {"topics": topics}).status_code == 201

    body = owner_api.get(f"/targets/{t['id']}/rationale").json()
    from_web = {x["label"]: x["from_web"] for x in body["topics"]}
    assert from_web == {"Scanning": False, "Scan options": True, "Firewall rules": False}
    limits = {x["code"]: x["message"] for x in body["limits"]}
    assert "Scan options" in limits["from_web"] and "not from your course material" in limits["from_web"]
    assert "Firewall rules" in limits["not_in_material"]  # asked and not added: stays not in the material


def test_the_assistant_explains_the_plan_at_the_first_session_and_after_a_change(
    owner_api: Api, conn: ConnectorApi
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Port scanning"])
    assert conn.get(f"/courses/{course}/context").json()["explain_plan"] is None  # no exam yet
    t = target(conn, course, "1. kolokvij", "2026-12-20", [])

    first = conn.get(f"/courses/{course}/context").json()["explain_plan"]
    assert first["now"] is True and first["why"] == "First study session for this exam."
    assert "get_plan_rationale" in first["how"]

    session = conn.post("/study-sessions", {"course_id": course, "mode": "new_learning"}).json()
    assert conn.get(f"/courses/{course}/context").json()["explain_plan"]["now"] is True  # not finished yet
    assert conn.post(f"/study-sessions/{session['id']}/summary", {"summary": "Learned scanning."}).status_code == 200
    later = conn.get(f"/courses/{course}/context").json()["explain_plan"]
    assert later["now"] is False and "asks" in later["why"]

    topics = [{"label": "Scanning", "concept_ids": [ids["Port scanning"]], "points": 10}]
    assert conn.post(f"/targets/{t['id']}/profile", {"topics": topics}).status_code == 201
    changed = conn.get(f"/courses/{course}/context").json()["explain_plan"]
    assert changed["now"] is True and changed["why"] == "The exam analysis changed since the last session."
