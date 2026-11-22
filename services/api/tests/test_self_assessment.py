"""Self-assessment (owner decision 2026-11-22): the learner checks a saved answer against the expected points when
no assistant is available; it is provisional, labelled as theirs, and an assistant checks it later."""

from __future__ import annotations

from typing import Any

from recallspring_api.services.self_assessment import suggested_grade

from .conftest import Api, ConnectorApi, FrozenClock


def _answered(owner_api: Api, **kw: Any) -> tuple[dict[str, str], str]:
    ids = owner_api.course_with_question(**kw)
    attempt = owner_api.answer(ids["question_id"]).json()
    return ids, attempt["attempt_id"]


def test_suggested_grade_follows_the_expected_points() -> None:
    assert suggested_grade(["met", "met"]) == 3
    assert suggested_grade(["met", "partial"]) == 2
    assert suggested_grade(["partial", "missing"]) == 1
    assert suggested_grade(["missing", "missing"]) == 0
    assert suggested_grade(["met", "missing", "missing"]) == 1  # 1 of 3 is less than half


def test_the_learner_grades_their_answer_and_it_stays_provisional(owner_api: Api, frozen: FrozenClock) -> None:
    ids, attempt_id = _answered(owner_api)
    view = owner_api.get(f"/attempts/{attempt_id}/self-assessment").json()
    assert view["available"] and view["reason"] is None
    assert view["expected_points"] == ["glycolysis happens in the cytoplasm", "pyruvate feeds the citric acid cycle"]
    assert len(view["sources"]) == 2 and view["question"]["prompt"].startswith("Compare glycolysis")

    url = f"/attempts/{attempt_id}/self-assessment"
    assert owner_api.post(url, {"points": ["met"], "grade": 2}).json()["code"] == "points_mismatch"
    assert owner_api.post(url, {"points": ["met", "met"], "grade": 4}).json()["code"] == "reason_required"
    r = owner_api.post(url, {"points": ["met", "partial"], "grade": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    own = body["assessments"][0]
    assert own["evaluator_kind"] == "self" and own["status"] == "provisional" and own["grade"] == 2
    assert own["strengths"] == ["glycolysis happens in the cytoplasm"]
    assert own["gaps"] == ["Partly: pyruvate feeds the citric acid cycle"]
    assert body["effective_assessment_id"] == own["id"]
    # Provisional: only a short follow-up, never a longer interval.
    assert "follow-up" in body["schedule"][0]["reason"]

    again = owner_api.post(url, {"points": ["met", "met"], "grade": 3})
    assert again.status_code == 409 and again.json()["code"] == "already_self_assessed"
    assert owner_api.get(url).json()["self_assessment"] == {"grade": 2, "points": ["met", "partial"]}

    concept = owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()
    graded = [h for h in concept["attempts"] if h["grade"] is not None]
    assert graded[0]["graded_by"] == "self" and graded[0]["grader"] == {"name": "You (self-assessed)", "model": None}
    history = [h for h in owner_api.get("/history").json() if h["type"] == "assessment.self_assessed"]
    assert history[0]["detail"] == "Partial (2/4) (provisional; suggested Partial (2/4)), to be checked"


def test_four_needs_a_reason_and_a_changed_grade_is_noted(owner_api: Api, frozen: FrozenClock) -> None:
    _, attempt_id = _answered(owner_api)
    r = owner_api.post(
        f"/attempts/{attempt_id}/self-assessment",
        {"points": ["met", "met"], "grade": 4, "reason": "I also explained why the cycle needs oxygen."},
    )
    own = r.json()["assessments"][0]
    assert own["grade"] == 4
    assert own["feedback"].startswith("Self-assessed: 2 of 2 expected points met (suggested Solid (3/4), chosen Transfer (4/4)).")
    assert "why the cycle needs oxygen" in own["feedback"]


def test_not_possible_without_expected_points(owner_api: Api, frozen: FrozenClock) -> None:
    _, bare = _answered(owner_api, expected_points=[])
    view = owner_api.get(f"/attempts/{bare}/self-assessment").json()
    assert not view["available"] and view["reason"] == "no_expected_points" and view["expected_points"] == []
    r = owner_api.post(f"/attempts/{bare}/self-assessment", {"points": ["met"], "grade": 3})
    assert r.status_code == 409 and r.json()["code"] == "no_expected_points"


def test_not_possible_after_a_grade(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    _, graded = _answered(owner_api)
    conn.post(
        f"/attempts/{graded}/assessments",
        {"status": "final", "grade": 3, "confidence": "high", "feedback": "Good.", "evidence_refs": []},
    )
    assert owner_api.get(f"/attempts/{graded}/self-assessment").json()["reason"] == "already_graded"


def test_an_assistant_checks_a_self_assessment(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    ids, attempt_id = _answered(owner_api)
    owner_api.post(f"/attempts/{attempt_id}/self-assessment", {"points": ["met", "met"], "grade": 3})

    assert conn.get(f"/courses/{ids['course_id']}/context").json()["self_assessments_to_check"] == 1
    listed = conn.get("/self-assessments").json()
    assert [(i["attempt_id"], i["self_grade"]) for i in listed["items"]] == [(attempt_id, 3)]
    assert "record_assessment" in listed["how_to_check"]
    assert conn.get("/self-assessments", course_id=ids["course_id"]).json()["items"]

    r = conn.post(
        f"/attempts/{attempt_id}/assessments",
        {"status": "final", "grade": 1, "confidence": "high", "feedback": "No cycle link.", "evidence_refs": []},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["self_assessment"] == {"grade": 3, "differs": True}
    effective = next(a for a in body["assessments"] if a["id"] == body["effective_assessment_id"])
    assert effective["evaluator_kind"] == "ai" and effective["grade"] == 1
    assert [a["evaluator_kind"] for a in body["assessments"]] == ["self", "ai"]  # theirs stays in the history
    assert conn.get("/self-assessments").json()["items"] == []
    assert conn.get(f"/courses/{ids['course_id']}/context").json()["self_assessments_to_check"] == 0


def test_chat_sees_them_in_the_study_context(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    from recallspring_api.services.chat_tools import INSTRUCTIONS, MAX_TOOLS, STUDY

    ids, attempt_id = _answered(owner_api)
    owner_api.post(f"/attempts/{attempt_id}/self-assessment", {"points": ["met", "missing"], "grade": 2})
    ctx = conn.get(f"/courses/{ids['course_id']}/context").json()
    assert [i["question_id"] for i in ctx["self_assessments"]] == [ids["question_id"]]
    # Chat keeps at most MAX_TOOLS per conversation: no extra tool, the context lists them and get_answer reads them.
    assert len(STUDY) <= MAX_TOOLS and "self_assessments" in INSTRUCTIONS
