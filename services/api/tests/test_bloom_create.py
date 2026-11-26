"""Bloom 6 Create (owner notes 2026-11-26, migration 0034): the practice limit may be 6. Without a limit of their own
the learner practises up to 5 Evaluate, or 6 Create while an upcoming exam paper asks for it; at 6 RecallSpring
recommends a more capable model."""

from __future__ import annotations

from recallspring_api.services.bloom import CREATE_TIP, _suggest

from .conftest import Api, ConnectorApi, FrozenClock
from .test_bloom_ramp import graded
from .test_check_first import outline
from .test_learning_first import course, mcq


def test_the_ramp_goes_on_to_create_only_with_a_limit_of_six() -> None:
    solid_to_five = graded((3, 3), (4, 3), (5, 3))
    assert _suggest(solid_to_five)["phase"] == "mixed"  # the default limit is 5
    up = _suggest(solid_to_five, 6)
    assert (up["next_level"], up["phase"]) == (6, "ramp") and "6 Create" in up["why"]
    mixed = _suggest(graded((3, 3), (4, 3), (5, 3), (6, 3)), 6)
    assert mixed["phase"] == "mixed" and mixed["next_level"] == 3  # least recently practised
    assert _suggest(graded((3, 3), (4, 3), (5, 3), (6, 1)), 6)["next_level"] == 5  # a weak Create answer steps back


def test_the_limit_is_five_until_the_learner_or_an_exam_paper_asks_for_create(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    cid, ids = course(conn, ["Topic"])
    conn.post("/concepts/known", {"concept_ids": [ids["Topic"]], "reason": "Covered in lectures."})
    create = {**mcq(ids["Topic"]), "bloom_level": 6}

    auto = outline(conn, cid)["practice_limit"]
    assert (auto["level"], auto["set_by_learner"], auto["model_tip"]) == (5, False, None)
    assert auto["automatic"].startswith("5 Evaluate")
    assert conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [create]}).status_code == 409

    # an upcoming exam whose paper has Create questions raises the automatic limit to 6, with the model tip
    midterm = {"kind": "kolokvij", "name": "1st midterm", "due_date": "2026-12-20", "scope_description": "All"}
    target = conn.post("/targets", {"course_id": cid, **midterm}).json()
    conn.post(f"/targets/{target['id']}/profile", {"bloom_mix": {"4": 0.7, "6": 0.3}})
    raised = outline(conn, cid)["practice_limit"]
    assert raised["level"] == 6 and raised["label"] == "Create" and raised["warning"] is None
    assert "1st midterm paper" in raised["automatic"] and raised["model_tip"] == CREATE_TIP
    assert conn.post("/quizzes", {"course_id": cid, "title": "Sim", "items": [create]}).status_code == 201

    # the learner's own 5 stays 5 (and is warned about the paper); null is automatic again
    five = owner_api.put(f"/courses/{cid}/practice-limit", {"level": 5}).json()
    assert (five["level"], five["set_by_learner"], five["automatic"]) == (5, True, None)
    assert "30 %" in five["warning"] and five["model_tip"] is None
    assert owner_api.put(f"/courses/{cid}/practice-limit", {"level": None}).json()["level"] == 6
    assert owner_api.put(f"/courses/{cid}/practice-limit", {"level": 7}).status_code == 422


def test_the_learner_can_choose_create_without_an_exam_paper(owner_api: Api, conn: ConnectorApi) -> None:
    cid, ids = course(conn, ["Topic"])
    conn.post("/concepts/known", {"concept_ids": [ids["Topic"]], "reason": "Covered in lectures."})
    chosen = owner_api.put(f"/courses/{cid}/practice-limit", {"level": 6}).json()
    assert (chosen["level"], chosen["set_by_learner"], chosen["model_tip"]) == (6, True, CREATE_TIP)
    practice = outline(conn, cid)["concepts"][0]["practice"]
    assert practice["next_level"] == 3 and "your limit" not in practice["why"]
