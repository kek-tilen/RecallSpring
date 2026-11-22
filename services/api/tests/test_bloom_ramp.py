"""The next Bloom level to practise (owner decision 2026-11-22): 3 Apply → 4 Analyze → 5 Evaluate as final answers
become Solid, one step back after a weak answer, then mixed; worked out without a model call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from recallspring_api.services.bloom import _suggest

from .conftest import Api, ConnectorApi, FrozenClock

T0 = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


def graded(*answers: tuple):
    """(level, grade[, status[, evaluator_kind]]) in the order they were answered."""
    out = []
    for i, (level, grade, *rest) in enumerate(answers):
        status = rest[0] if rest else "final"
        kind = rest[1] if len(rest) > 1 else "ai"
        out.append((T0 + timedelta(hours=i), level, SimpleNamespace(grade=grade, status=status, evaluator_kind=kind)))
    return out


def test_it_starts_at_apply_and_ramps_up_with_solid_answers() -> None:
    assert _suggest([])["next_level"] == 3
    assert _suggest(graded((3, 2)))["next_level"] == 3  # Partial: stay
    step = _suggest(graded((3, 3)))
    assert (step["next_level"], step["phase"], step["highest_solid"]) == (4, "ramp", 3)
    assert _suggest(graded((3, 3), (4, 4)))["next_level"] == 5


def test_unsure_or_own_grades_never_move_it_up() -> None:
    assert _suggest(graded((3, 3, "provisional")))["next_level"] == 3
    assert _suggest(graded((3, 3, "final", "self")))["next_level"] == 3
    assert _suggest(graded((3, 3, "final", "human")))["next_level"] == 4  # the learner's correction counts


def test_a_weak_answer_steps_back_but_never_below_apply() -> None:
    back = _suggest(graded((3, 3), (4, 3), (5, 1)))
    assert (back["next_level"], back["phase"]) == (4, "consolidate")
    assert _suggest(graded((3, 0)))["next_level"] == 3


def test_after_evaluate_it_mixes_the_least_recently_practised_level() -> None:
    mixed = _suggest(graded((3, 3), (4, 3), (5, 3)))
    assert (mixed["phase"], mixed["next_level"]) == ("mixed", 3)
    assert _suggest(graded((3, 3), (4, 3), (5, 3), (3, 3)))["next_level"] == 4
    assert "least recently" in mixed["why"]


def test_the_outline_shows_it_for_studied_concepts(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    ids = owner_api.course_with_question()  # a Bloom 4 question
    outline = conn.get(f"/courses/{ids['course_id']}/outline").json()
    (concept,) = outline["concepts"]
    if concept["study_status"] == "not_studied":
        assert concept["practice"] is None
        conn.post("/concepts/known", {"concept_ids": [ids["concept_id"]], "reason": "Covered in lectures."})
    assert conn.get(f"/courses/{ids['course_id']}/outline").json()["concepts"][0]["practice"]["next_level"] == 3

    attempt = owner_api.answer(ids["question_id"]).json()
    conn.post(
        f"/attempts/{attempt['attempt_id']}/assessments",
        {"status": "final", "grade": 3, "confidence": "high", "feedback": "Solid.", "evidence_refs": []},
    )
    practice = conn.get(f"/courses/{ids['course_id']}/outline").json()["concepts"][0]["practice"]
    assert (practice["next_level"], practice["highest_solid"]) == (5, 4)
