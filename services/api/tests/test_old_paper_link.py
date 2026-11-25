"""An exam-style analysis shows the old paper it came from, and the learner can link it later (owner 2026-11-23)."""

from __future__ import annotations

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi
from .pdfs import make_pdf
from .test_planning_and_simulations import course_with_concepts, target

PROFILE = {
    "item_types": [{"type": "mcq", "share": 1.0}],
    "topics": [{"label": "Ports", "not_in_material": True}],
    "example_items": ["Which service uses port 389?"],
}


def exam_with_profile(api: Api, conn: ConnectorApi, title: str = "Network security") -> tuple[str, dict]:
    course, _ = course_with_concepts(api, conn, ["Ports"], title=title)
    t = target(conn, course, "1. kolokvij", "2026-12-20", [])
    assert conn.post(f"/targets/{t['id']}/profile", PROFILE).status_code == 201
    return course, t


def profile_of(api: Api, course: str) -> dict:
    return api.get(f"/courses/{course}/overview").json()["targets"][0]["profile"]


def test_chat_analysis_has_no_source_until_the_learner_links_the_paper(owner_api: Api, conn: ConnectorApi) -> None:
    course, t = exam_with_profile(owner_api, conn)
    assert profile_of(owner_api, course)["source"] is None  # shared only in a chat

    paper = owner_api.upload(course, "kolokvij-2025.pdf", make_pdf(["Old paper"]), category="past_paper").json()
    r = owner_api.client.put(
        f"/api/v1/targets/{t['id']}/profile/source", json={"source_id": paper["id"]}, headers=owner_api.headers()
    )
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["source"] == {"id": paper["id"], "filename": "kolokvij-2025.pdf", "removed": False}
    assert r.json()["profile"]["example_items"] == PROFILE["example_items"]  # the analysis itself is unchanged
    assert profile_of(owner_api, course)["source"]["filename"] == "kolokvij-2025.pdf"

    unlink = owner_api.client.put(
        f"/api/v1/targets/{t['id']}/profile/source", json={"source_id": None}, headers=owner_api.headers()
    )
    assert unlink.json()["profile"]["source"] is None
    with new_session() as db:
        linked = [
            e.details for e in db.scalars(select(AuditEvent).where(AuditEvent.action == "exam_profile.source_linked"))
        ]
    assert linked == [{"from": None, "to": paper["id"]}, {"from": paper["id"], "to": None}]


def test_the_paper_must_be_material_of_the_exams_course(owner_api: Api, conn: ConnectorApi) -> None:
    _, t = exam_with_profile(owner_api, conn)
    other, _ = course_with_concepts(owner_api, conn, ["X"], title="Digitalna forenzika")
    foreign = owner_api.upload(other, "other.pdf", make_pdf(["Other"]), category="past_paper").json()

    r = owner_api.client.put(
        f"/api/v1/targets/{t['id']}/profile/source", json={"source_id": foreign["id"]}, headers=owner_api.headers()
    )
    assert r.status_code == 422 and r.json()["code"] == "source_not_in_course"
    by_assistant = conn.post(f"/targets/{t['id']}/profile", {**PROFILE, "source_id": foreign["id"]})
    assert by_assistant.status_code == 422 and by_assistant.json()["code"] == "source_not_in_course"


def test_an_assistant_can_record_the_source_directly(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Ports"])
    t = target(conn, course, "Izpit", "2027-01-20", [])
    paper = owner_api.upload(course, "izpit.pdf", make_pdf(["Exam"]), category="past_paper").json()
    assert conn.post(f"/targets/{t['id']}/profile", {**PROFILE, "source_id": paper["id"]}).status_code == 201
    assert profile_of(owner_api, course)["source"]["id"] == paper["id"]


def test_linking_needs_an_analysis(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Ports"])
    t = target(conn, course, "Izpit", "2027-01-20", [])
    r = owner_api.client.put(
        f"/api/v1/targets/{t['id']}/profile/source", json={"source_id": None}, headers=owner_api.headers()
    )
    assert r.status_code == 404 and r.json()["code"] == "no_profile"
