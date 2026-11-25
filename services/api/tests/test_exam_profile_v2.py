"""Exam profile v2 (ADR-013 §1): every topic mapped, points turned into weights, confirmed by the learner."""

from __future__ import annotations

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent, TargetProfile
from recallspring_api.services.targets import topic_weight

from .conftest import Api, ConnectorApi
from .office import PNG_1PX
from .pdfs import make_pdf
from .test_planning_and_simulations import course_with_concepts, target


def _exam(api: Api, conn: ConnectorApi) -> tuple[str, dict[str, str], dict]:
    course, ids = course_with_concepts(api, conn, ["Port scanning", "Ports", "Dorking"], known=True)
    return course, ids, target(conn, course, "1. kolokvij", "2026-12-20", [])


def test_weights_follow_points_and_recurrence() -> None:
    assert topic_weight(None, 4, 1) == 1.0  # no share: an average topic
    assert topic_weight(0.25, 4, 1) == 1.0  # the average share
    assert topic_weight(0.5, 4, 1) == 2.0  # twice the average
    assert topic_weight(0.05, 4, 1) == 0.5  # never below 0.5
    assert topic_weight(0.25, 4, 2) == 1.25 and topic_weight(0.25, 4, 3) == 1.5 and topic_weight(0.25, 4, 5) == 1.5
    assert topic_weight(0.4, 4, 3) == 2.0  # capped


def test_a_profile_with_points_papers_and_unreadable_parts(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids, t = _exam(owner_api, conn)
    paper = owner_api.upload(course, "kolokvij-2025.pdf", make_pdf(["Old paper"]), category="past_paper").json()
    r = conn.post(
        f"/targets/{t['id']}/profile",
        {
            "papers": [
                {"source_id": paper["id"], "label": "2025", "total_points": 30, "duration_minutes": 60},
                {"label": "2024", "total_points": 30},
            ],
            "item_types": [{"type": "scenario", "share": 0.6}, {"type": "mcq", "share": 0.4}],
            "bloom_mix": {"3": 0.6, "4": 0.4},
            "topics": [
                {
                    "label": "Scanning",
                    "concept_ids": [ids["Port scanning"], ids["Ports"]],
                    "points": 24,
                    "where": "Q2, p. 1",
                    "papers": ["2025", "2024"],
                },
                {"label": "Dorking", "concept_ids": [ids["Dorking"]], "points": 8, "where": "Q5"},
                {"label": "Firewall rules", "not_in_material": True, "points": 4, "where": "Q6"},
            ],
            "unreadable": ["points of Q4"],
            "model_name": "Claude Sonnet 5.5",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    profile = body["profile"]
    assert profile["version"] == 2 and profile["confirmation"] == "unconfirmed"
    assert "confirm_exam_profile" in body["confirm"]
    scanning, dorking, firewall = profile["topics"]
    # 24 of 60 points over both papers, against an average third: 1.2, on two papers x1.25 = 1.5
    assert scanning["share"] == 0.4 and scanning["weight"] == 1.5 and scanning["where"] == "Q2, p. 1"
    assert dorking["weight"] == 0.5 and firewall["not_in_material"] is True and firewall["concept_ids"] == []
    assert profile["papers"][0]["source"]["filename"] == "kolokvij-2025.pdf" and profile["papers"][1]["source"] is None
    assert profile["source"]["id"] == paper["id"] and profile["unreadable"] == ["points of Q4"]
    # both concepts of the topic carry its weight in the plan
    items = {i["term"]: i for i in conn.get("/plan").json()["items"]}
    assert "Weighs more on past papers." in items["Port scanning"]["why_selected"]
    assert "Weighs more on past papers." in items["Ports"]["why_selected"]
    assert "Weighs more" not in items["Dorking"]["why_selected"]


def test_nothing_is_silently_ignored(owner_api: Api, conn: ConnectorApi) -> None:
    _, ids, t = _exam(owner_api, conn)
    _, other_ids = course_with_concepts(owner_api, conn, ["X"], title="Statistika")

    def post(body: dict) -> dict:
        r = conn.post(f"/targets/{t['id']}/profile", body)
        assert r.status_code == 422, r.text
        return r.json()

    assert post({"topics": [{"label": "Scanning", "points": 10}]})["code"] == "topic_not_mapped"
    both = {"label": "Scanning", "concept_ids": [ids["Ports"]], "not_in_material": True}
    assert post({"topics": [both]})["code"] == "topic_mapping_unclear"
    assert post({"topics": [{"label": "X", "concept_ids": [other_ids["X"]]}]})["code"] == "invalid_weight"
    unknown = {"label": "Ports", "concept_ids": [ids["Ports"]], "papers": ["2023"]}
    assert post({"topics": [unknown]})["code"] == "unknown_paper"
    post({"topic_weights": [{"label": "Ports", "weight": 2.0}]})  # the v1 shape is refused, not stored without effect


def test_the_learner_confirms_the_latest_analysis(owner_api: Api, conn: ConnectorApi) -> None:
    _, ids, t = _exam(owner_api, conn)
    ports = {"label": "Ports", "concept_ids": [ids["Ports"]]}
    first_id = conn.post(f"/targets/{t['id']}/profile", {"topics": [ports]}).json()["profile"]["id"]
    latest_id = conn.post(f"/targets/{t['id']}/profile", {"topics": [{**ports, "where": "Q1"}]}).json()["profile"]["id"]

    stale = conn.post(f"/targets/{t['id']}/profile/confirm", {"profile_id": first_id})
    assert stale.status_code == 409 and stale.json()["code"] == "profile_changed"
    assert stale.json()["details"]["latest_profile_id"] == latest_id

    ok = conn.post(f"/targets/{t['id']}/profile/confirm", {"profile_id": latest_id})
    assert ok.status_code == 200, ok.text
    assert ok.json()["profile"]["confirmation"] == "confirmed" and ok.json()["profile"]["confirmed_via"] == "assistant"
    again = owner_api.client.post(
        f"/api/v1/targets/{t['id']}/profile/confirm", json={"profile_id": latest_id}, headers=owner_api.headers()
    )
    assert again.status_code == 200 and again.json()["profile"]["confirmed_via"] == "assistant"  # unchanged
    with new_session() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "exam_profile.confirmed"))
        assert [e.details for e in events] == [{"via": "assistant"}]


def test_an_analysis_from_before_confirmation_is_analysed_again(owner_api: Api, conn: ConnectorApi) -> None:
    _, ids, t = _exam(owner_api, conn)
    profile_id = conn.post(f"/targets/{t['id']}/profile", {"bloom_mix": {"3": 1.0}}).json()["profile"]["id"]
    with new_session() as db:  # an analysis stored before ADR-013
        row = db.scalar(select(TargetProfile).where(TargetProfile.id == profile_id))
        assert row is not None
        row.version, row.topics = 1, []
        row.topic_weights = [{"label": "Ports", "concept_id": ids["Ports"], "weight": 2.0}]
        db.commit()
    r = owner_api.client.post(
        f"/api/v1/targets/{t['id']}/profile/confirm", json={"profile_id": profile_id}, headers=owner_api.headers()
    )
    assert r.status_code == 409 and r.json()["code"] == "analyse_again"
    assert owner_api.get(f"/targets/{t['id']}/readiness").json()["target"]["name"] == "1. kolokvij"
    items = {i["term"]: i for i in conn.get("/plan").json()["items"]}
    assert "Weighs more on past papers." in items["Ports"]["why_selected"]  # v1 weights still count


def test_a_paper_of_another_exam_can_count_for_its_style_only(owner_api: Api, conn: ConnectorApi) -> None:
    """Owner 2026-11-25: a 2nd kolokvij paper used for the 1st. Its kind of questions counts; its topics are listed
    but do not weigh, do not count towards coverage and do not raise recurrence."""
    course, ids, t = _exam(owner_api, conn)
    r = conn.post(
        f"/targets/{t['id']}/profile",
        {
            "papers": [
                {"label": "2025", "exam": "1. kolokvij 2025", "total_points": 20},
                {"label": "2026", "exam": "2. kolokvij 2026", "use": "style", "total_points": 20},
            ],
            "bloom_mix": {"1": 0.5, "2": 0.5},
            "topics": [
                {"label": "Scanning", "concept_ids": [ids["Port scanning"]], "points": 10, "papers": ["2025", "2026"]},
                {"label": "Dorking", "concept_ids": [ids["Dorking"]], "points": 16, "papers": ["2026"]},
                {"label": "Ports", "concept_ids": [ids["Ports"]], "points": 4, "papers": ["2025"]},
            ],
        },
    )
    assert r.status_code == 201, r.text
    profile = r.json()["profile"]
    assert profile["papers"][1]["use"] == "style" and profile["papers"][1]["exam"] == "2. kolokvij 2026"
    assert profile["papers"][0]["use"] == "style_and_topics"
    topics = {x["label"]: x for x in profile["topics"]}
    # on the style-only paper alone: weight 1.0 although it has the most points
    assert topics["Dorking"]["style_only"] is True and topics["Dorking"]["weight"] == 1.0
    # on both papers, but only one counts for topics: no recurrence bonus (share 10/40 x 3 topics = 0.75)
    assert topics["Scanning"]["style_only"] is False and topics["Scanning"]["weight"] == 0.75

    body = owner_api.get(f"/targets/{t['id']}/rationale").json()
    assert [x["label"] for x in body["topics"]][-1] == "Dorking"  # listed last
    assert body["topics"][-1]["style_only"] is True
    # coverage counts only the topics that count: Scanning and Ports (both known = studied)
    assert body["coverage"]["studied_percent"] == 100
    by_code = {x["code"]: x["message"] for x in body["limits"]}
    assert "2026 (2. kolokvij 2026)" in by_code["style_only"] and "2025" not in by_code["style_only"]
    assert all(i["topics"] == [] or i["topics"][0]["label"] != "Dorking" for i in body["today"]["items"])
    assert conn.post(f"/targets/{t['id']}/profile", {"papers": [{"label": "x", "use": "topics"}]}).status_code == 422


def test_every_past_paper_is_looked_at_or_left_out_on_the_learners_word(owner_api: Api, conn: ConnectorApi) -> None:
    """Owner 2026-11-25: an analysis read one photo of a course's past papers and missed the other four."""
    course, ids, t = _exam(owner_api, conn)

    def upload(name: str, content: bytes) -> str:
        r = owner_api.upload(course, name, content, category="past_paper")
        assert r.status_code == 201, r.text
        return r.json()["id"]

    first = upload("3.jpg.png", PNG_1PX)
    page2 = upload("4.png", PNG_1PX + b"\x00")
    other = upload("5.png", PNG_1PX + b"\x00\x00")
    old = upload("2019.pdf", make_pdf(["Old paper"]))
    assert owner_api.post("/sources/archive", {"source_ids": [old], "archived": True}).status_code == 200
    papers = conn.get(f"/courses/{course}/context").json()["past_papers"]
    assert [p["filename"] for p in papers] == ["3.jpg.png", "4.png", "5.png"]  # archived papers are not listed

    ports = {"label": "Ports", "concept_ids": [ids["Ports"]]}
    r = conn.post(f"/targets/{t['id']}/profile", {"papers": [{"source_id": first, "label": "2026"}], "topics": [ports]})
    assert r.status_code == 201, r.text
    assert [m["filename"] for m in r.json()["not_looked_at"]] == ["4.png", "5.png"]
    assert r.json()["confirm"].startswith("These past papers of the course are not in the analysis: 4.png, 5.png.")
    profile_id = r.json()["profile"]["id"]
    refused = conn.post(f"/targets/{t['id']}/profile/confirm", {"profile_id": profile_id})
    assert refused.status_code == 409 and refused.json()["code"] == "papers_not_looked_at"
    limits = {x["code"]: x["message"] for x in owner_api.get(f"/targets/{t['id']}/rationale").json()["limits"]}
    assert "4.png and 5.png" in limits["not_looked_at"] or "4.png, 5.png" in limits["not_looked_at"]

    # the second photo is the same paper; the third is left out on the learner's word
    r = conn.post(
        f"/targets/{t['id']}/profile",
        {
            "papers": [{"source_id": first, "label": "2026", "extra_source_ids": [page2]}],
            "skipped_papers": [{"source_id": other, "reason": "2nd kolokvij; learner: does not apply"}],
            "topics": [ports],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["not_looked_at"] == [] and not body["confirm"].startswith("These past papers")
    assert body["profile"]["skipped_papers"][0]["source"]["filename"] == "5.png"
    assert [f["filename"] for f in body["profile"]["papers"][0]["files"]] == ["3.jpg.png", "4.png"]  # every file
    ok = conn.post(f"/targets/{t['id']}/profile/confirm", {"profile_id": body["profile"]["id"]})
    assert ok.status_code == 200, ok.text
    assert "not_looked_at" not in {x["code"] for x in owner_api.get(f"/targets/{t['id']}/rationale").json()["limits"]}

    # a paper of another course is refused as a further page
    other_course, _ = course_with_concepts(owner_api, conn, ["Y"], title="Statistika 2")
    foreign = owner_api.upload(other_course, "x.png", PNG_1PX + b"\x01", category="past_paper").json()["id"]
    bad = conn.post(
        f"/targets/{t['id']}/profile",
        {"papers": [{"source_id": first, "extra_source_ids": [foreign]}], "topics": [ports]},
    )
    assert bad.status_code == 422 and bad.json()["code"] == "source_not_in_course"


def test_the_learner_may_confirm_in_the_web_app_with_papers_not_looked_at(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids, t = _exam(owner_api, conn)
    owner_api.upload(course, "4.png", PNG_1PX, category="past_paper")
    r = conn.post(f"/targets/{t['id']}/profile", {"topics": [{"label": "Ports", "concept_ids": [ids["Ports"]]}]})
    profile = r.json()["profile"]
    assert [m["filename"] for m in profile["not_looked_at"]] == ["4.png"]
    ok = owner_api.post(f"/targets/{t['id']}/profile/confirm", {"profile_id": profile["id"]})
    assert ok.status_code == 200 and ok.json()["profile"]["confirmed_via"] == "web"
