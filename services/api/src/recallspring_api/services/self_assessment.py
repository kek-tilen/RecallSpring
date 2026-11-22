"""Self-assessment: the learner grades their own saved answer against the question's expected points when no
assistant is available (owner decision 2026-11-22).

* Only for written answers to questions that have expected points, and only while no other grade exists.
* The learner marks each expected point met / partly / missed; RecallSpring suggests a grade from that
  (``suggested_grade``, deterministic). The learner may choose another 0-3; 4 Transfer needs a reason.
* Stored as an append-only assessment with ``evaluator_kind = 'self'``, always ``provisional``: the scheduler then
  only plans a short follow-up and never lengthens an interval, so a self-assessment cannot make a concept reliable.
* An assistant checks it later (``unchecked``): its grade is appended and becomes the effective one.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import Assessment, Attempt, Course, Question, User
from . import attempts as attempt_svc
from .events import audit, learning_event
from .reviews import effective_assessment
from .sources import parse_refs, sections_in_course

RUBRIC_VERSION = "self-check-v1"
PointState = Literal["met", "partial", "missing"]
REASONS = {
    "not_an_answer": "Only written answers can be self-assessed.",
    "already_graded": "This answer already has a grade.",
    "already_self_assessed": "You already assessed this answer yourself; an assistant checks it next.",
    "no_expected_points": "This question has no expected points to compare with, so ask an assistant to grade it.",
}


def expected_points(question: Question) -> list[str]:
    points = (question.rubric or {}).get("expected_points") or []
    return [p for p in points if isinstance(p, str) and p.strip()]


def suggested_grade(states: list[str]) -> int:
    """All points met → 3 Solid; at least half (a partly met point counts half) → 2; something → 1; nothing → 0.
    4 Transfer is never suggested: it goes beyond the expected points."""
    met, partial = states.count("met"), states.count("partial")
    if states and met == len(states):
        return 3
    score = (met + 0.5 * partial) / len(states) if states else 0
    return 2 if score >= 0.5 else 1 if score > 0 else 0


def unavailable(attempt: Attempt, question: Question, assessments: list[Assessment]) -> str | None:
    if attempt.kind != "answer":
        return "not_an_answer"
    if any(a.evaluator_kind == "self" for a in assessments):
        return "already_self_assessed"
    if assessments:
        return "already_graded"
    if not expected_points(question):
        return "no_expected_points"
    return None


def check_view(db: Session, user: User, attempt: Attempt) -> dict[str, Any]:
    """What the learner compares their answer with. Expected points are shown only because the answer is saved."""
    question = db.get(Question, attempt.question_id)
    assert question is not None
    assessments = attempt_svc.assessments_for(db, attempt.id)
    reason = unavailable(attempt, question, assessments)
    sections = sections_in_course(db, user.id, question.course_id, parse_refs(question.source_refs))
    own = next((a for a in assessments if a.evaluator_kind == "self"), None)
    return {
        "attempt_id": str(attempt.id),
        "available": reason is None,
        "reason": reason,
        "message": REASONS.get(reason) if reason else None,
        "question": {"id": str(question.id), "prompt": question.prompt, "bloom_level": question.bloom_level},
        "expected_points": expected_points(question) if reason in (None, "already_self_assessed") else [],
        "sources": [s.citation_label for s in sections],
        "self_assessment": {"grade": own.grade, "points": (own.rubric_scores or {}).get("points")} if own else None,
    }


def record(
    db: Session,
    user: User,
    attempt: Attempt,
    states: list[str],
    grade: int,
    reason: str | None,
    request_id: str | None,
) -> Assessment:
    question = db.get(Question, attempt.question_id)
    assert question is not None
    assessments = attempt_svc.assessments_for(db, attempt.id)
    why = unavailable(attempt, question, assessments)
    if why:
        raise ApiError(409, why, REASONS[why])
    points = expected_points(question)
    if len(states) != len(points):
        raise ApiError(
            422, "points_mismatch", "Mark every expected point.", {"expected": len(points), "given": len(states)}
        )
    suggested = suggested_grade(states)
    reason = (reason or "").strip() or None
    if grade == 4 and not reason:
        raise ApiError(422, "reason_required", "4 Transfer goes beyond the expected points: say how your answer does.")
    met = [p for p, s in zip(points, states, strict=True) if s == "met"]
    gaps = [("Partly: " + p) if s == "partial" else p for p, s in zip(points, states, strict=True) if s != "met"]
    feedback = f"Self-assessed: {len(met)} of {len(points)} expected points met"
    feedback += f" (suggested {suggested}/4, chosen {grade}/4)." if grade != suggested else "."
    if reason:
        feedback += f"\nYour reason: {reason}"
    row = attempt_svc.add_assessment(
        db,
        user_id=user.id,
        attempt=attempt,
        data={
            "rubric_version": RUBRIC_VERSION,
            "status": "provisional",
            "grade": grade,
            "confidence": "medium",
            "feedback": feedback,
            "strengths": met,
            "gaps": gaps,
            "rubric_scores": {"points": states, "suggested": suggested},
        },
        evaluator_kind="self",
        provider=None,
        model=None,
        model_reported_by=None,
        simulated=False,
        flags=[],
    )
    db.flush()
    details = {"attempt_id": str(attempt.id), "grade": grade, "suggested": suggested, "points": states}
    learning_event(
        db,
        user_id=user.id,
        entity_type="assessment",
        entity_id=row.id,
        event_type="assessment.self_assessed",
        payload=details,
        request_id=request_id,
    )
    audit(
        db,
        actor_id=user.id,
        action="assessment.self_assessed",
        target_type="assessment",
        target_id=row.id,
        details=details,
        request_id=request_id,
    )
    return row


def unchecked(db: Session, user: User, course_id: uuid.UUID | None, limit: int = 50) -> list[dict[str, Any]]:
    """Answers whose grade is still the learner's own: an assistant should check them."""
    stmt = (
        select(Attempt, Question, Course)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .join(Question, Question.id == Attempt.question_id)
        .join(Course, Course.id == Question.course_id)
        .where(Attempt.user_id == user.id, Assessment.evaluator_kind == "self", Course.deleted_at.is_(None))
        .order_by(Attempt.submitted_at)
    )
    if course_id is not None:
        stmt = stmt.where(Course.id == course_id)
    rows = db.execute(stmt).all()
    out: list[dict[str, Any]] = []
    for attempt, question, course in rows:
        eff = effective_assessment(attempt_svc.assessments_for(db, attempt.id))
        if eff is None or eff.evaluator_kind != "self":
            continue
        out.append(
            {
                "attempt_id": str(attempt.id),
                "question_id": str(question.id),
                "course_id": str(course.id),
                "course_title": course.title,
                "prompt": question.prompt[:300],
                "submitted_at": attempt.submitted_at.isoformat(),
                "self_grade": eff.grade,
                "self_suggested": (eff.rubric_scores or {}).get("suggested"),
            }
        )
        if len(out) >= limit:
            break
    return out
