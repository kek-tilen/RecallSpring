"""Concept-to-Clarity (ADR-010): the learner's explanation of one concept, in versions, with feedback per version.

* A version is the learner's own text, saved exactly before any assistant reads it. Only the learner writes
  versions; an assistant never rewrites one. Sources: written by the learner, written at the end of a Discuss, or an
  exam answer the learner added (its exact text, labelled with the answer's word limit).
* Feedback is what is correct, missing and wrong, with sections the assistant actually cited (unknown sections are
  dropped). It is never a grade and does not move reviews or the study status.
* Versions are soft-deleted after the learner confirmed it and stay restorable for 30 days.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import (
    Attempt,
    Concept,
    Explanation,
    ExplanationFeedback,
    ExplanationVersion,
    Question,
    QuestionConcept,
    Source,
    SourceSection,
    User,
)
from . import assistants
from .events import audit
from .ownership import owned

RESTORE_DAYS = 30
MAX_TEXT = 20_000

HOW = (
    "Concept-to-Clarity (C2C): the learner explains one concept in their own words; each save is a new version, kept "
    "exactly. Read the newest version (and the earlier ones to see progress), compare it with the material you read "
    "and record feedback with record_explanation_feedback: what is correct, what is missing, what is wrong, citing "
    "only section IDs you received. Not a grade; never rewrite their explanation or write a version for them. A "
    "version from an exam answer was written with a word limit: judge it as an explanation, do not count its limited "
    "scope against it."
)


def _explanation(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, *, create: bool) -> Explanation | None:
    row = db.scalar(select(Explanation).where(Explanation.user_id == user_id, Explanation.concept_id == concept_id))
    if row is None and create:
        row = Explanation(user_id=user_id, concept_id=concept_id)
        db.add(row)
        db.flush()
    return row


def _feedback_view(f: ExplanationFeedback) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "grader": assistants.grader("ai", f.provider, f.model),
        "correct": f.correct,
        "missing": f.missing,
        "wrong": f.wrong,
        "evidence_refs": f.evidence_refs,
        "feedback": f.feedback,
        "created_at": f.created_at.isoformat(),
    }


def _version_view(v: ExplanationVersion, feedback: list[ExplanationFeedback]) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "number": v.number,
        "text": v.text,
        "words": len(v.text.split()),
        "source": v.source,
        "source_attempt_id": str(v.source_attempt_id) if v.source_attempt_id else None,
        "word_limit": v.word_limit,
        "created_at": v.created_at.isoformat(),
        "deleted_at": v.deleted_at.isoformat() if v.deleted_at else None,
        "feedback": [_feedback_view(f) for f in feedback],
    }


def view(db: Session, user: User, concept_id: uuid.UUID) -> dict[str, Any]:
    """The concept's explanation: versions oldest first with their feedback, and versions deleted in the last
    30 days (restorable)."""
    concept = owned(db, Concept, concept_id, user.id)
    exp = _explanation(db, user.id, concept.id, create=False)
    versions: list[ExplanationVersion] = []
    if exp is not None:
        versions = list(
            db.scalars(
                select(ExplanationVersion)
                .where(ExplanationVersion.explanation_id == exp.id)
                .order_by(ExplanationVersion.number)
            )
        )
    feedback: dict[uuid.UUID, list[ExplanationFeedback]] = {}
    if versions:
        for f in db.scalars(
            select(ExplanationFeedback)
            .where(ExplanationFeedback.version_id.in_([v.id for v in versions]))
            .order_by(ExplanationFeedback.created_at)
        ):
            feedback.setdefault(f.version_id, []).append(f)
    cutoff = clock.now() - timedelta(days=RESTORE_DAYS)
    live = [v for v in versions if v.deleted_at is None]
    deleted = [v for v in versions if v.deleted_at is not None and v.deleted_at >= cutoff]
    return {
        "concept": {"id": str(concept.id), "term": concept.term, "course_id": str(concept.course_id)},
        "versions": [_version_view(v, feedback.get(v.id, [])) for v in live],
        "deleted": [_version_view(v, feedback.get(v.id, [])) for v in deleted],
        "how": HOW,
    }


def add_version(
    db: Session,
    user: User,
    concept_id: uuid.UUID,
    *,
    text: str,
    source: str,
    client_request_id: uuid.UUID,
    from_attempt_id: uuid.UUID | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Save a new version exactly as given (an exam answer: its exact text). A repeated client_request_id returns the
    view without saving twice."""
    concept = owned(db, Concept, concept_id, user.id, for_update=True)
    seen = db.scalar(
        select(ExplanationVersion).where(
            ExplanationVersion.user_id == user.id, ExplanationVersion.client_request_id == client_request_id
        )
    )
    if seen is not None:
        return view(db, user, concept.id)
    word_limit = None
    if from_attempt_id is not None:
        attempt = owned(db, Attempt, from_attempt_id, user.id)
        linked = db.scalar(
            select(QuestionConcept.concept_id).where(
                QuestionConcept.question_id == attempt.question_id, QuestionConcept.concept_id == concept.id
            )
        )
        if attempt.kind != "answer" or linked is None:
            raise ApiError(422, "attempt_not_for_concept", "Only a written answer to a question on this concept.")
        question = db.get(Question, attempt.question_id)
        text, source = attempt.answer_text, "exam_answer"
        word_limit = question.length_words if question is not None else None
    elif source == "exam_answer":
        raise ApiError(422, "attempt_required", "A version from an exam answer needs the answer (from_attempt_id).")
    if not text.strip():
        raise ApiError(422, "empty_explanation", "Write your explanation first.")
    if len(text) > MAX_TEXT:
        raise ApiError(422, "explanation_too_long", f"An explanation can be up to {MAX_TEXT} characters.")
    exp = _explanation(db, user.id, concept.id, create=True)
    assert exp is not None
    top = db.scalar(select(func.max(ExplanationVersion.number)).where(ExplanationVersion.explanation_id == exp.id))
    version = ExplanationVersion(
        user_id=user.id,
        explanation_id=exp.id,
        number=(top or 0) + 1,
        text=text,
        source=source,
        source_attempt_id=from_attempt_id,
        word_limit=word_limit,
        client_request_id=client_request_id,
    )
    db.add(version)
    exp.updated_at = clock.now()
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="explanation.version_saved",
        target_type="concept",
        target_id=concept.id,
        details={"version": version.number, "source": source, "words": len(text.split())},
        request_id=request_id,
    )
    return view(db, user, concept.id)


def _version(db: Session, user_id: uuid.UUID, version_id: uuid.UUID) -> tuple[ExplanationVersion, Concept]:
    version = db.scalar(
        select(ExplanationVersion).where(ExplanationVersion.id == version_id, ExplanationVersion.user_id == user_id)
    )
    exp = db.get(Explanation, version.explanation_id) if version is not None else None
    if version is None or exp is None:
        raise ApiError(404, "not_found", "Explanation version not found.")
    return version, owned(db, Concept, exp.concept_id, user_id)


def set_deleted(
    db: Session, user: User, version_id: uuid.UUID, deleted: bool, request_id: str | None = None
) -> dict[str, Any]:
    """Soft delete (after the learner confirmed it in the app) or restore within 30 days."""
    version, concept = _version(db, user.id, version_id)
    if deleted and version.deleted_at is None:
        version.deleted_at = clock.now()
    elif not deleted and version.deleted_at is not None:
        if version.deleted_at < clock.now() - timedelta(days=RESTORE_DAYS):
            raise ApiError(409, "restore_expired", "This version was deleted more than 30 days ago.")
        version.deleted_at = None
    else:
        return view(db, user, concept.id)
    audit(
        db,
        actor_id=user.id,
        action="explanation.version_deleted" if deleted else "explanation.version_restored",
        target_type="concept",
        target_id=concept.id,
        details={"version": version.number},
        request_id=request_id,
    )
    db.flush()
    return view(db, user, concept.id)


def record_feedback(
    db: Session,
    user: User,
    version_id: uuid.UUID,
    *,
    correct: list[str],
    missing: list[str],
    wrong: list[str],
    evidence_refs: list[str],
    feedback: str,
    client: str | None,
    model: str | None,
    model_reported_by: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """An assistant's feedback on one version. Cited sections must be real sections of the concept's course; others
    are dropped (and counted in the answer, so the assistant knows)."""
    version, concept = _version(db, user.id, version_id)
    if version.deleted_at is not None:
        raise ApiError(409, "version_deleted", "This version was deleted.")
    ids = []
    for ref in evidence_refs:
        try:
            ids.append(uuid.UUID(ref))
        except ValueError:
            continue
    allowed = {
        str(s)
        for s in db.scalars(
            select(SourceSection.id)
            .join(Source, Source.id == SourceSection.source_id)
            .where(SourceSection.id.in_(ids), SourceSection.user_id == user.id, Source.course_id == concept.course_id)
        )
    }
    kept = [r for r in dict.fromkeys(evidence_refs) if r in allowed]
    row = ExplanationFeedback(
        user_id=user.id,
        version_id=version.id,
        provider=assistants.provider_for(client),
        model=model,
        model_reported_by=model_reported_by,
        correct=correct,
        missing=missing,
        wrong=wrong,
        evidence_refs=kept,
        feedback=feedback,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="explanation.feedback_recorded",
        target_type="concept",
        target_id=concept.id,
        details={
            "version": version.number,
            "provider": row.provider,
            "model": model,
            "cited": len(kept),
            "dropped_refs": len(evidence_refs) - len(kept),
        },
        request_id=request_id,
    )
    return {
        "saved": True,
        "version": version.number,
        "dropped_refs": len(evidence_refs) - len(kept),
        "explanation": view(db, user, concept.id),
    }
