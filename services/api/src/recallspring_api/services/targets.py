"""Study targets (kolokvij / izpit): scope resolution, active target and the study context Claude starts from."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Concept,
    ConceptSource,
    Course,
    Quiz,
    ReviewState,
    Source,
    SourceSection,
    StudyTarget,
    StudyTargetScope,
    TargetProfile,
)

SETUP_QUESTIONS = [
    "What are you preparing for: the 1st kolokvij, the 2nd kolokvij, or the exam (whole course or only a part, "
    "because you already passed something)?",
    "When is it (date)?",
    "From which material to which material (e.g. lectures 1-6, or pages 1-80 of the script)?",
    "Do you have an old kolokvij or exam paper I can use to match the question style?",
    "Anything special to know (allowed aids, only calculations, topics the lecturer emphasises, ...)?",
]


def live_targets(db: Session, course_id: uuid.UUID) -> list[StudyTarget]:
    return list(
        db.scalars(
            select(StudyTarget)
            .where(StudyTarget.course_id == course_id, StudyTarget.deleted_at.is_(None))
            .order_by(StudyTarget.due_date, StudyTarget.created_at)
        )
    )


def active_target(targets: list[StudyTarget], today: date) -> StudyTarget | None:
    """The nearest upcoming target that is today or later; a failed target stays relevant for the retake."""
    upcoming = [t for t in targets if t.status == "upcoming" and t.due_date >= today]
    return upcoming[0] if upcoming else None


def scope_concepts(db: Session, target: StudyTarget) -> set[uuid.UUID]:
    """Concepts covered by a target. No scope rows means the whole course."""
    rows = list(db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)))
    course_concepts = select(Concept.id).where(Concept.course_id == target.course_id, Concept.deleted_at.is_(None))
    if not rows:
        return set(db.scalars(course_concepts))
    concepts: set[uuid.UUID] = set()
    for row in rows:
        if row.kind == "concept" and row.concept_id:
            concepts.add(row.concept_id)
        elif row.kind == "topic" and row.syllabus_item_id:
            concepts |= set(db.scalars(course_concepts.where(Concept.syllabus_item_id == row.syllabus_item_id)))
        elif row.kind in ("source", "pages") and row.source_id:
            section_filter = [SourceSection.source_id == row.source_id]
            if row.kind == "pages":
                section_filter += [
                    SourceSection.page >= (row.page_from or 1),
                    SourceSection.page <= (row.page_to or 100_000),
                ]
            concepts |= set(
                db.scalars(
                    select(ConceptSource.concept_id)
                    .join(SourceSection, SourceSection.id == ConceptSource.section_id)
                    .where(*section_filter)
                )
            )
    return concepts


def scope_view(db: Session, target: StudyTarget) -> list[dict[str, Any]]:
    out = []
    for row in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)):
        item: dict[str, Any] = {"kind": row.kind}
        if row.source_id:
            src = db.get(Source, row.source_id)
            item["source_id"] = str(row.source_id)
            item["filename"] = src.filename if src else None
        if row.kind == "pages":
            item["pages"] = [row.page_from, row.page_to]
        if row.syllabus_item_id:
            item["topic_id"] = str(row.syllabus_item_id)
        if row.concept_id:
            item["concept_id"] = str(row.concept_id)
        out.append(item)
    return out


def latest_profile(db: Session, target_id: uuid.UUID) -> TargetProfile | None:
    return db.scalar(
        select(TargetProfile)
        .where(TargetProfile.target_id == target_id)
        .order_by(TargetProfile.created_at.desc())
        .limit(1)
    )


def profile_view(profile: TargetProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "id": str(profile.id),
        "source_id": str(profile.source_id) if profile.source_id else None,
        "item_types": profile.item_types,
        "bloom_mix": profile.bloom_mix,
        "topic_weights": profile.topic_weights,
        "example_items": profile.example_items,
        "notes": profile.notes,
        "derived_by": profile.model or "assistant",
        "created_at": profile.created_at.isoformat(),
    }


def target_view(db: Session, target: StudyTarget, today: date) -> dict[str, Any]:
    return {
        "id": str(target.id),
        "kind": target.kind,
        "name": target.name,
        "due_date": target.due_date.isoformat(),
        "days_left": (target.due_date - today).days,
        "status": target.status,
        "result": target.result,
        "goal": target.goal,
        "scope_description": target.scope_description,
        "scope": scope_view(db, target),
        "notes": target.notes,
        "concepts_in_scope": len(scope_concepts(db, target)),
        "profile": profile_view(latest_profile(db, target.id)),
    }


def study_context(db: Session, course: Course, today: date, style_percent: int = 75) -> dict[str, Any]:
    """Everything Claude needs at the start of a study session in one course, including whether to ask the
    learner what they are preparing for."""
    targets = live_targets(db, course.id)
    active = active_target(targets, today)
    stale = [t for t in targets if t.status == "upcoming" and t.due_date < today]
    passed = [t for t in targets if t.status == "passed"]
    reasons = []
    if active is None:
        reasons.append("no upcoming target is set for this course")
    if stale:
        reasons.append(
            "a target date has passed; ask whether it was passed, failed or moved: " + ", ".join(t.name for t in stale)
        )
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at.desc()).limit(5))
    return {
        "course": {"id": str(course.id), "title": course.title},
        "today": today.isoformat(),
        "active_target": target_view(db, active, today) if active else None,
        "other_targets": [target_view(db, t, today) for t in targets if t is not active],
        "passed_targets": [t.name for t in passed],
        "needs_setup": bool(reasons),
        "setup_reasons": reasons,
        "ask_learner": SETUP_QUESTIONS if active is None else [],
        "recent_simulations": [
            {
                "quiz_id": str(q.id),
                "title": q.title,
                "status": q.status,
                "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
            }
            for q in quizzes
        ],
        "learning": _learning_counts(db, active) if active else None,
        "rules": [
            "Learn first: concepts that are not_studied are taught (explain, then the learner summarises in the "
            "summary form) before any practice or simulation. RecallSpring refuses practice on unstudied concepts "
            "unless the learner says they already know them or asks for a diagnostic pre-test.",
            "Material of passed targets is in maintenance: keep reviewing it, but give priority to the active target.",
            f"About {style_percent} % of practice questions follow the style of the target's exam profile (past "
            f"papers); the other {100 - style_percent} % are deeper Bloom 4-5 questions for understanding.",
        ],
    }


def _learning_counts(db: Session, target: StudyTarget) -> dict[str, int]:
    from .learning import effective_status

    ids = scope_concepts(db, target)
    counts = {"not_studied": 0, "studied": 0, "known": 0}
    if not ids:
        return counts
    practised = set(db.scalars(select(ReviewState.concept_id).where(ReviewState.concept_id.in_(ids))))
    for concept in db.scalars(select(Concept).where(Concept.id.in_(ids))):
        counts[effective_status(concept, concept.id in practised)] += 1
    return counts
