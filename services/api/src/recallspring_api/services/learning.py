"""Learning first (ADR-006): new material is studied before it is practised or simulated.

A concept is *not_studied* until the learner studies it in a learning session (Claude explains, the learner
summarises in their own words), says they already know it (*known*, self-report), or shows it in a diagnostic
pre-test (*known*, diagnostic). Any practice evidence also counts as studied.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import Concept, Note, NoteRevision, ReviewState, User
from .events import learning_event

NOT_STUDIED_MESSAGE = (
    "Some concepts have not been studied yet. Teach them first (explain, then open_summary_form so the learner "
    "summarises in their own words), ask whether the learner already knows them (mark_concepts_known), or create a "
    "diagnostic pre-test (create_quiz with mode='diagnostic'), which does not affect the review schedule."
)


def effective_status(concept: Concept, has_evidence: bool) -> str:
    if concept.study_status != "not_studied":
        return concept.study_status
    return "studied" if has_evidence else "not_studied"


def unstudied(db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> list[Concept]:
    if not concept_ids:
        return []
    practised = set(
        db.scalars(
            select(ReviewState.concept_id).where(
                ReviewState.user_id == user_id, ReviewState.concept_id.in_(concept_ids)
            )
        )
    )
    concepts = db.scalars(
        select(Concept).where(
            Concept.id.in_(concept_ids), Concept.user_id == user_id, Concept.study_status == "not_studied"
        )
    )
    return [c for c in concepts if c.id not in practised]


def require_studied(db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> None:
    missing = unstudied(db, user_id, list(dict.fromkeys(concept_ids)))
    if missing:
        raise ApiError(
            409,
            "concepts_not_studied",
            NOT_STUDIED_MESSAGE,
            {"concepts": [{"id": str(c.id), "term": c.term} for c in missing]},
        )


def mark(
    db: Session, user: User, concepts: list[Concept], status: str, source: str, request_id: str | None
) -> list[dict[str, Any]]:
    """``studied`` always applies; ``known`` only upgrades concepts that were not studied yet."""
    now = clock.now()
    out = []
    for concept in concepts:
        if status == "known" and concept.study_status != "not_studied":
            out.append({"id": str(concept.id), "term": concept.term, "study_status": concept.study_status})
            continue
        if concept.study_status != status:
            concept.study_status = status
            concept.study_source = source
            concept.studied_at = now
            learning_event(
                db,
                user_id=user.id,
                entity_type="concept",
                entity_id=concept.id,
                event_type=f"concept.{status}",
                payload={"source": source},
                request_id=request_id,
            )
        out.append({"id": str(concept.id), "term": concept.term, "study_status": concept.study_status})
    return out


def concepts_of_course(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Concept]:
    rows = list(
        db.scalars(
            select(Concept).where(
                Concept.id.in_(ids),
                Concept.user_id == user_id,
                Concept.course_id == course_id,
                Concept.deleted_at.is_(None),
            )
        )
    )
    if len(rows) != len(set(ids)):
        raise ApiError(404, "not_found", "One or more concepts were not found in this course.")
    return rows


def save_summary(
    db: Session,
    user: User,
    *,
    course_id: uuid.UUID,
    concept_ids: list[uuid.UUID],
    title: str,
    text: str,
    client_request_id: uuid.UUID,
    request_id: str,
) -> dict[str, Any]:
    """End of a learning chunk: store the learner's own summary exactly (as a note) and mark the concepts studied.
    An empty summary still marks them studied (the learner chose to skip writing)."""
    concepts = concepts_of_course(db, user.id, course_id, concept_ids)
    note = None
    if text.strip():
        note = db.scalar(select(Note).where(Note.user_id == user.id, Note.client_note_id == client_request_id))
        if note is None:
            now = clock.now()
            note = Note(
                user_id=user.id,
                course_id=course_id,
                client_note_id=client_request_id,
                title=title,
                body=text,
                revision=1,
                saved_at=now,
                created_at=now,
            )
            db.add(note)
            db.flush()
            db.add(
                NoteRevision(
                    user_id=user.id, note_id=note.id, kind="autosave", revision=1, title=title, body=text, saved_at=now
                )
            )
            learning_event(
                db,
                user_id=user.id,
                entity_type="note",
                entity_id=note.id,
                event_type="note.created",
                payload={"origin": "learning_summary"},
                request_id=request_id,
            )
    marked = mark(db, user, concepts, "studied", "session", request_id)
    return {
        "note_id": str(note.id) if note else None,
        "saved_at": note.saved_at.isoformat() if note else None,
        "concepts": marked,
    }
