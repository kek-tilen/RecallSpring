"""Read-only views for the web app: everything RecallSpring stores, in a form people can scan.

No raw learner text appears in learning-event payloads by design; the history view describes events in plain
English and links to the records themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import (
    Assessment,
    Attempt,
    AuditEvent,
    Concept,
    ConceptSource,
    Course,
    LearningEvent,
    Note,
    Question,
    QuestionConcept,
    Quiz,
    QuizItem,
    ReviewState,
    Source,
    SourceSection,
    User,
)
from . import mastery
from .attempts import assessments_for
from .learning import effective_status
from .quizzes import results_view
from .reviews import effective_assessment
from .sources import source_view
from .targets import active_target, live_targets, target_view


def _review(state: ReviewState | None, now: datetime) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "due_at": state.due_at.isoformat(),
        "is_due": state.due_at <= now,
        "step": state.step,
        "reason": state.due_reason.get("message"),
        "evidence_count": state.evidence_count,
        "lapse_count": state.lapse_count,
        "last_review_at": state.last_review_at.isoformat(),
    }


def _sections_by_concept(db: Session, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    if not concept_ids:
        return {}
    rows = db.execute(
        select(ConceptSource.concept_id, SourceSection.id, SourceSection.citation_label, Source.filename)
        .join(SourceSection, SourceSection.id == ConceptSource.section_id)
        .join(Source, Source.id == SourceSection.source_id)
        .where(ConceptSource.concept_id.in_(concept_ids))
        .order_by(Source.uploaded_at, SourceSection.page, SourceSection.position)
    ).all()
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for concept_id, section_id, label, filename in rows:
        out.setdefault(concept_id, []).append({"section_id": str(section_id), "label": label, "filename": filename})
    return out


def quiz_summary(db: Session, quiz: Quiz) -> dict[str, Any]:
    results = results_view(db, quiz, for_learner=True) if quiz.status == "submitted" else None
    return {
        "id": str(quiz.id),
        "course_id": str(quiz.course_id),
        "title": quiz.title,
        "mode": quiz.mode,
        "status": quiz.status,
        "items": db.scalar(select(func.count()).select_from(QuizItem).where(QuizItem.quiz_id == quiz.id)),
        "created_at": quiz.created_at.isoformat(),
        "submitted_at": quiz.submitted_at.isoformat() if quiz.submitted_at else None,
        "earned_points": results["earned_points"] if results else None,
        "max_points": results["max_points"] if results else None,
        "pending_items": results["pending_items"] if results else None,
    }


def course_overview(db: Session, user: User, course: Course) -> dict[str, Any]:
    now = clock.now()
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    concepts = list(
        db.scalars(
            select(Concept)
            .where(Concept.course_id == course.id, Concept.deleted_at.is_(None))
            .order_by(Concept.created_at, Concept.term)
        )
    )
    states = (
        {
            s.concept_id: s
            for s in db.scalars(
                select(ReviewState).where(
                    ReviewState.user_id == user.id, ReviewState.concept_id.in_([c.id for c in concepts])
                )
            )
        }
        if concepts
        else {}
    )
    sections = _sections_by_concept(db, [c.id for c in concepts])
    study = {"not_studied": 0, "studied": 0, "known": 0}
    bands = {b: 0 for b in mastery.BANDS}
    rows = []
    for c in concepts:
        state = states.get(c.id)
        status = effective_status(c, state is not None)
        band = mastery.band(state)
        diff = mastery.difficulty(c, state)
        study[status] += 1
        bands[band] += 1
        rows.append(
            {
                "id": str(c.id),
                "term": c.term,
                "definition_draft": c.definition_draft,
                "study_status": status,
                "band": band,
                "difficulty": diff.value,
                "difficulty_source": diff.source,
                "review": _review(state, now),
                "sections": sections.get(c.id, [])[:4],
            }
        )
    targets = live_targets(db, course.id)
    active = active_target(targets, today)
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at.desc()))
    return {
        "course": {
            "id": str(course.id),
            "title": course.title,
            "description": course.description,
            "status": course.status,
            "created_at": course.created_at.isoformat(),
        },
        "active_target_id": str(active.id) if active else None,
        "targets": [target_view(db, t, today) for t in targets],
        "progress": {"study": study, "bands": bands, "concepts": len(concepts)},
        "concepts": rows,
        "sources": [
            source_view(db, s)
            for s in db.scalars(
                select(Source)
                .where(Source.course_id == course.id, Source.deleted_at.is_(None))
                .order_by(Source.uploaded_at)
            )
        ],
        "notes": db.scalar(
            select(func.count()).select_from(Note).where(Note.course_id == course.id, Note.deleted_at.is_(None))
        ),
        "quizzes": [quiz_summary(db, q) for q in quizzes],
        "note": mastery_note(),
    }


def mastery_note() -> str:
    return "Knowledge bands are estimated from practice, not a guarantee of recall."


def concept_detail(db: Session, user: User, concept: Concept) -> dict[str, Any]:
    now = clock.now()
    state = db.get(ReviewState, (user.id, concept.id))
    diff = mastery.difficulty(concept, state)
    question_ids = list(db.scalars(select(QuestionConcept.question_id).where(QuestionConcept.concept_id == concept.id)))
    attempts = (
        list(
            db.scalars(
                select(Attempt)
                .where(Attempt.question_id.in_(question_ids), Attempt.user_id == user.id)
                .order_by(Attempt.submitted_at.desc())
            )
        )
        if question_ids
        else []
    )
    history = []
    for a in attempts:
        question = db.get(Question, a.question_id)
        assessments = assessments_for(db, a.id)
        eff = effective_assessment(assessments)
        quiz = db.get(Quiz, a.quiz_id) if a.quiz_id else None
        history.append(
            {
                "attempt_id": str(a.id),
                "question": question.prompt if question else None,
                "bloom_level": question.bloom_level if question else None,
                "answer": a.answer_text,
                "kind": a.kind,
                "captured_via": a.captured_via,
                "submitted_at": a.submitted_at.isoformat(),
                "status": a.status,
                "quiz": {"id": str(quiz.id), "title": quiz.title, "mode": quiz.mode} if quiz else None,
                "grade": eff.grade if eff else None,
                "assessment_status": eff.status if eff else None,
                "graded_by": eff.evaluator_kind if eff else None,
                "feedback": eff.feedback if eff else None,
                "assessment_id": str(eff.id) if eff else None,
            }
        )
    return {
        "id": str(concept.id),
        "course_id": str(concept.course_id),
        "term": concept.term,
        "definition_draft": concept.definition_draft,
        "study_status": effective_status(concept, state is not None),
        "study_source": concept.study_source,
        "studied_at": concept.studied_at.isoformat() if concept.studied_at else None,
        "band": mastery.band(state),
        "difficulty": diff.value,
        "difficulty_source": diff.source,
        "review": _review(state, now),
        "sections": _sections_by_concept(db, [concept.id]).get(concept.id, []),
        "attempts": history,
        "note": mastery_note(),
    }


def attempts_list(db: Session, user: User, course_id: uuid.UUID | None, limit: int) -> list[dict[str, Any]]:
    stmt = (
        select(Attempt, Question)
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.user_id == user.id)
        .order_by(Attempt.submitted_at.desc())
        .limit(limit)
    )
    if course_id is not None:
        stmt = stmt.where(Question.course_id == course_id)
    out = []
    for attempt, question in db.execute(stmt).all():
        eff = effective_assessment(assessments_for(db, attempt.id))
        out.append(
            {
                "attempt_id": str(attempt.id),
                "course_id": str(question.course_id),
                "question": question.prompt,
                "question_type": question.question_type,
                "bloom_level": question.bloom_level,
                "kind": attempt.kind,
                "captured_via": attempt.captured_via,
                "status": attempt.status,
                "submitted_at": attempt.submitted_at.isoformat(),
                "quiz_id": str(attempt.quiz_id) if attempt.quiz_id else None,
                "grade": eff.grade if eff else None,
                "assessment_status": eff.status if eff else None,
                "graded_by": eff.evaluator_kind if eff else None,
            }
        )
    return out


_EVENT_TEXT = {
    "course.created": "Course created",
    "source.added": "Material added",
    "source.parsed": "Text extracted",
    "source.reprocess": "Extraction started again",
    "note.created": "Note created",
    "note.saved": "Note saved",
    "note.conflict": "Note edit conflict kept both versions",
    "question.generated": "Question written",
    "attempt.submitted": "Answer saved",
    "evaluation.failed": "Feedback unavailable (answer kept)",
    "assessment.recorded": "Answer graded",
    "assessment.challenged": "You challenged a grade",
    "assessment.corrected": "You corrected a grade",
    "review.deferred": "Review deferred",
    "quiz.created": "Simulation created",
    "quiz.submitted": "Simulation submitted",
    "concept.studied": "Concept studied",
    "concept.known": "Concept marked as known",
    "target.profile_recorded": "Exam profile recorded",
    "study_session.summarised": "Study session summarised",
    "target.created": "Study target created",
    "target.updated": "Study target updated",
    "connector.limit_changed": "Connector limit changed",
    "connector.token_created": "Connector token created",
    "connector.token_revoked": "Connector token revoked",
    "concepts.marked_known": "You marked concepts as known",
    "study.settings_changed": "Study settings changed",
    "study.availability_changed": "Study time changed",
    "review.defer": "Review deferred",
    "assessment.grade_override": "Grade overridden",
    "auth.login": "Signed in",
    "auth.logout": "Signed out",
}


def _detail(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "assessment.recorded":
        who = "RecallSpring" if payload.get("provider") is None and payload.get("model") is None else "Claude"
        grade = payload.get("grade")
        return f"{grade}/4 ({payload.get('status')}) by {who}" if grade is not None else f"ungraded by {who}"
    if event_type == "source.parsed":
        return f"{payload.get('state')}, {payload.get('sections')} sections"
    if event_type == "attempt.submitted":
        via = {"answer_form": "answer form", "assistant_transcription": "copied by Claude", "app_ui": "web app"}
        return f"{payload.get('kind')} via {via.get(payload.get('captured_via'), payload.get('captured_via'))}"
    if event_type == "assessment.corrected":
        return f"{payload.get('old_grade')} → {payload.get('new_grade')}"
    if event_type == "note.saved":
        return f"revision {payload.get('revision')}"
    if event_type == "concept.known" or event_type == "concept.studied":
        return {
            "session": "learning session",
            "self_report": "you said you know it",
            "diagnostic": "diagnostic pre-test",
        }.get(payload.get("source"), payload.get("source"))
    if event_type == "quiz.submitted":
        return f"{payload.get('items')} questions, {payload.get('mode', 'practice')}"
    return None


def _labels(db: Session, items: list[tuple[str, uuid.UUID | None]]) -> dict[uuid.UUID, str]:
    """Readable names for referenced entities (one query per entity type)."""
    by_type: dict[str, set[uuid.UUID]] = {}
    for kind, eid in items:
        if eid is not None:
            by_type.setdefault(kind, set()).add(eid)
    labels: dict[uuid.UUID, str] = {}
    lookups = {
        "concept": (Concept, Concept.term),
        "source": (Source, Source.filename),
        "quiz": (Quiz, Quiz.title),
        "course": (Course, Course.title),
        "note": (Note, Note.title),
    }
    for kind, (model, column) in lookups.items():
        ids = by_type.get(kind)
        if ids:
            for eid, label in db.execute(select(model.id, column).where(model.id.in_(ids))).all():
                labels[eid] = label
    # Answers, grades and questions are named by their question (shortened).
    question_rows = []
    if ids := by_type.get("question"):
        question_rows += db.execute(select(Question.id, Question.prompt).where(Question.id.in_(ids))).all()
    if ids := by_type.get("attempt"):
        question_rows += db.execute(
            select(Attempt.id, Question.prompt)
            .join(Question, Question.id == Attempt.question_id)
            .where(Attempt.id.in_(ids))
        ).all()
    if ids := by_type.get("assessment"):
        question_rows += db.execute(
            select(Assessment.id, Question.prompt)
            .join(Attempt, Attempt.id == Assessment.attempt_id)
            .join(Question, Question.id == Attempt.question_id)
            .where(Assessment.id.in_(ids))
        ).all()
    for eid, prompt in question_rows:
        labels[eid] = prompt if len(prompt) <= 90 else prompt[:89].rstrip() + "…"
    return labels


def history(db: Session, user: User, limit: int) -> list[dict[str, Any]]:
    events = list(
        db.scalars(
            select(LearningEvent)
            .where(LearningEvent.user_id == user.id)
            .order_by(LearningEvent.occurred_at.desc())
            .limit(limit)
        )
    )
    audits = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.actor_id == user.id)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(limit)
        )
    )
    labels = _labels(
        db, [(e.entity_type, e.entity_id) for e in events] + [(a.target_type or "", a.target_id) for a in audits]
    )
    rows = [
        {
            "at": e.occurred_at.isoformat(),
            "kind": "learning",
            "type": e.event_type,
            "text": _EVENT_TEXT.get(e.event_type, e.event_type),
            "detail": _detail(e.event_type, e.payload),
            "entity_type": e.entity_type,
            "entity_id": str(e.entity_id),
            "label": labels.get(e.entity_id),
        }
        for e in events
    ] + [
        {
            "at": a.occurred_at.isoformat(),
            "kind": "audit",
            "type": a.action,
            "text": _EVENT_TEXT.get(a.action, a.action),
            "detail": None,
            "entity_type": a.target_type,
            "entity_id": str(a.target_id) if a.target_id else None,
            "label": labels.get(a.target_id) if a.target_id else None,
        }
        for a in audits
        if a.action not in ("auth.login", "auth.logout", "auth.login_failed")
    ]
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:limit]


def counts(db: Session, user: User) -> dict[str, int]:
    def n(model: Any, *where: Any) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.user_id == user.id, *where)) or 0

    return {
        "courses": n(Course, Course.deleted_at.is_(None)),
        "sources": n(Source, Source.deleted_at.is_(None)),
        "concepts": n(Concept, Concept.deleted_at.is_(None)),
        "notes": n(Note, Note.deleted_at.is_(None)),
        "answers": n(Attempt),
        "grades": n(Assessment),
        "simulations": n(Quiz),
    }


def attention(db: Session, user: User) -> list[dict[str, Any]]:
    """Things that need the learner: failed extractions, open simulations, answers waiting for feedback."""
    items: list[dict[str, Any]] = []
    for s in db.scalars(
        select(Source).where(
            Source.user_id == user.id,
            Source.deleted_at.is_(None),
            Source.parse_state.in_(("failed", "needs_attention")),
        )
    ):
        items.append(
            {
                "kind": "source",
                "id": str(s.id),
                "course_id": str(s.course_id),
                "title": s.filename,
                "text": source_view(db, s)["parse_message"],
            }
        )
    for q in db.scalars(select(Quiz).where(Quiz.user_id == user.id, Quiz.status == "open")):
        items.append(
            {
                "kind": "quiz",
                "id": str(q.id),
                "course_id": str(q.course_id),
                "title": q.title,
                "text": "Simulation not submitted yet." + (" (diagnostic)" if q.mode == "diagnostic" else ""),
            }
        )
    waiting = (
        db.scalar(
            select(func.count())
            .select_from(Attempt)
            .where(Attempt.user_id == user.id, Attempt.status == "saved_awaiting_evaluation")
        )
        or 0
    )
    if waiting:
        items.append(
            {
                "kind": "answers",
                "id": None,
                "course_id": None,
                "title": f"{waiting} answer(s)",
                "text": "Saved; feedback is still pending. Ask Claude to grade them.",
            }
        )
    return items


def courses_summary(db: Session, user: User) -> list[dict[str, Any]]:
    """One row per course for the Courses page: active target, study progress, library size, due reviews."""
    now = clock.now()
    out = []
    for course in db.scalars(
        select(Course).where(Course.user_id == user.id, Course.deleted_at.is_(None)).order_by(Course.created_at)
    ):
        view = course_overview(db, user, course)
        active = next((t for t in view["targets"] if t["id"] == view["active_target_id"]), None)
        out.append(
            {
                **view["course"],
                "active_target": {k: active[k] for k in ("id", "kind", "name", "due_date", "days_left", "status")}
                if active
                else None,
                "progress": view["progress"],
                "sources": len(view["sources"]),
                "notes": view["notes"],
                "simulations": len(view["quizzes"]),
                "due_reviews": sum(1 for c in view["concepts"] if c["review"] and c["review"]["is_due"]),
                "generated_at": now.isoformat(),
            }
        )
    return out
