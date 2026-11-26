"""Attempts and assessments: persist-first capture, evaluation claims and append-only assessment records."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import Assessment, Attempt, Question, User
from ..schemas import AssessmentOut, AttemptOut
from . import photos
from .events import audit, learning_event
from .reviews import concept_ids_for_question, effective_assessment, recompute

DONT_KNOW_FEEDBACK = (
    'You chose "I don\'t know". That is useful information: this concept will come back for a short review '
    "the next day. Re-read the related source section and explain it in your own words."
)


def assessments_for(db: Session, attempt_id: uuid.UUID) -> list[Assessment]:
    return list(
        db.scalars(select(Assessment).where(Assessment.attempt_id == attempt_id).order_by(Assessment.created_at))
    )


def attempt_view(db: Session, attempt: Attempt) -> dict[str, Any]:
    assessments = assessments_for(db, attempt.id)
    eff = effective_assessment(assessments)
    return AttemptOut(
        id=attempt.id,
        question_id=attempt.question_id,
        session_id=attempt.session_id,
        kind=attempt.kind,
        answer_text=attempt.answer_text,
        answer_mode=attempt.answer_mode,
        captured_via=attempt.captured_via,
        status=attempt.status,
        submitted_at=attempt.submitted_at,
        last_evaluation_error=attempt.last_evaluation_error,
        assessments=[AssessmentOut.model_validate(a) for a in assessments],
        effective_assessment_id=eff.id if eff else None,
        photos=photos.views(db, attempt.photo_ids),
        answer_seconds=attempt.answer_seconds,
        unsure=attempt.guessing,
    ).model_dump(mode="json")


def find_by_client_request(db: Session, user_id: uuid.UUID, client_request_id: uuid.UUID) -> Attempt | None:
    return db.scalar(select(Attempt).where(Attempt.user_id == user_id, Attempt.client_request_id == client_request_id))


def add_assessment(
    db: Session,
    *,
    user_id: uuid.UUID,
    attempt: Attempt,
    data: dict[str, Any],
    evaluator_kind: str,
    provider: str | None,
    model: str | None,
    model_reported_by: str | None,
    simulated: bool,
    flags: list[str],
    supersedes_id: uuid.UUID | None = None,
) -> Assessment:
    row = Assessment(
        user_id=user_id,
        attempt_id=attempt.id,
        evaluator_kind=evaluator_kind,
        provider=provider,
        model=model,
        model_reported_by=model_reported_by,
        simulated=simulated,
        rubric_version=data["rubric_version"],
        status=data["status"],
        grade=data["grade"],
        confidence=data["confidence"],
        feedback=data["feedback"],
        evidence_refs=data.get("evidence_refs", []),
        strengths=data.get("strengths", []),
        gaps=data.get("gaps", []),
        remediation=data.get("remediation"),
        rubric_scores=data.get("rubric_scores"),
        factuality_flags=flags,
        supersedes_id=supersedes_id,
        created_at=clock.now(),
    )
    db.add(row)
    return row


def create_attempt(
    db: Session,
    *,
    user: User,
    question: Question,
    session_id: uuid.UUID | None,
    client_request_id: uuid.UUID,
    kind: str,
    answer_text: str,
    answer_mode: str,
    captured_via: str,
    request_id: str,
    photo_ids: list[uuid.UUID] | None = None,
    answer_seconds: int | None = None,
    unsure: bool = False,
) -> Attempt:
    """Stage the attempt (and, for "I don't know", its deterministic assessment) in the current transaction."""
    now = clock.now()
    photo_ids = list(photo_ids or []) if kind == "answer" else []
    if kind == "answer" and not answer_text.strip() and not photo_ids:
        raise ApiError(422, "answer_empty", 'Write an answer or add a photo, or choose "I don\'t know" or "Skip".')
    status = {"answer": "saved_awaiting_evaluation", "dont_know": "evaluated", "skip": "not_applicable"}[kind]
    attempt = Attempt(
        user_id=user.id,
        question_id=question.id,
        session_id=session_id,
        client_request_id=client_request_id,
        kind=kind,
        answer_text=answer_text,
        answer_mode=answer_mode,
        captured_via=captured_via,
        status=status,
        photo_ids=[str(p) for p in photo_ids],
        answer_seconds=answer_seconds,
        # Unsure only marks a real answer (2026-11-26); "I don't know" and Skip carry no mark.
        guessing=unsure and kind == "answer",
        submitted_at=now,
    )
    db.add(attempt)
    db.flush()
    learning_event(
        db,
        user_id=user.id,
        entity_type="attempt",
        entity_id=attempt.id,
        event_type="attempt.submitted",
        payload={
            "question_id": str(question.id),
            "kind": kind,
            "answer_mode": answer_mode,
            "captured_via": captured_via,
            "client_request_id": str(client_request_id),
            "photos": len(photo_ids),
            "unsure": unsure and kind == "answer",
        },
        request_id=request_id,
    )
    if kind == "dont_know":
        add_assessment(
            db,
            user_id=user.id,
            attempt=attempt,
            data={
                "rubric_version": "deterministic-dont-know-v1",
                "status": "final",
                "grade": 0,
                "confidence": "high",
                "feedback": DONT_KNOW_FEEDBACK,
            },
            evaluator_kind="deterministic",
            provider=None,
            model=None,
            model_reported_by=None,
            simulated=False,
            flags=[],
        )
        recompute(db, user, concept_ids_for_question(db, question.id), now)
    return attempt


def claim_evaluation(db: Session, attempt: Attempt, lease_seconds: int) -> datetime | None:
    """Mark the attempt as being evaluated. Returns the claim timestamp, or None if already evaluated."""
    if attempt.kind != "answer":
        raise ApiError(409, "not_evaluable", "Only written answers can be evaluated.")
    if attempt.status == "evaluated":
        return None
    now = clock.now()
    if (
        attempt.status == "evaluating"
        and attempt.evaluation_started_at is not None
        and attempt.evaluation_started_at > now - timedelta(seconds=lease_seconds)
    ):
        raise ApiError(409, "evaluation_in_progress", "Feedback for this answer is already being prepared.")
    attempt.status = "evaluating"
    attempt.evaluation_started_at = now
    attempt.last_evaluation_error = None
    return now


def holds_claim(attempt: Attempt, claimed_at: datetime) -> bool:
    return attempt.status == "evaluating" and attempt.evaluation_started_at == claimed_at


def release_failed_claim(db: Session, attempt: Attempt, claimed_at: datetime, code: str, request_id: str) -> None:
    if not holds_claim(attempt, claimed_at):
        return
    attempt.status = "saved_awaiting_evaluation"
    attempt.last_evaluation_error = code
    learning_event(
        db,
        user_id=attempt.user_id,
        entity_type="attempt",
        entity_id=attempt.id,
        event_type="evaluation.failed",
        payload={"reason": code},
        request_id=request_id,
    )


def record_correction(
    db: Session,
    *,
    user: User,
    attempt: Attempt,
    original: Assessment,
    reason: str,
    corrected_grade: int | None,
    request_id: str,
) -> Assessment | None:
    """Learner disagreement. With a corrected grade it appends a human assessment and recomputes the schedule."""
    now = clock.now()
    if corrected_grade is None:
        learning_event(
            db,
            user_id=user.id,
            entity_type="assessment",
            entity_id=original.id,
            event_type="assessment.challenged",
            payload={"has_correction": False},
            request_id=request_id,
        )
        audit(
            db,
            actor_id=user.id,
            action="assessment.challenge",
            target_type="assessment",
            target_id=original.id,
            request_id=request_id,
        )
        return None
    row = add_assessment(
        db,
        user_id=user.id,
        attempt=attempt,
        data={
            "rubric_version": "human-correction-v1",
            "status": "final",
            "grade": corrected_grade,
            "confidence": "high",
            "feedback": f"Corrected by you: {reason}",
        },
        evaluator_kind="human",
        provider=None,
        model=None,
        model_reported_by=None,
        simulated=False,
        flags=[],
        supersedes_id=original.id,
    )
    db.flush()
    learning_event(
        db,
        user_id=user.id,
        entity_type="assessment",
        entity_id=row.id,
        event_type="assessment.corrected",
        payload={"supersedes": str(original.id), "old_grade": original.grade, "new_grade": corrected_grade},
        request_id=request_id,
    )
    audit(
        db,
        actor_id=user.id,
        action="assessment.grade_override",
        target_type="assessment",
        target_id=row.id,
        details={"supersedes": str(original.id), "old_grade": original.grade, "new_grade": corrected_grade},
        request_id=request_id,
    )
    recompute(db, user, concept_ids_for_question(db, attempt.question_id), now)
    return row
