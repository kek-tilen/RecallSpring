"""Read-only views for the web app: everything RecallSpring stores, in a form people can scan.

No raw learner text appears in learning-event payloads by design; the history view describes events in plain
English and links to the records themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import backup, clock
from ..learning.scheduler import grade_text
from ..models import (
    Assessment,
    Attempt,
    AuditEvent,
    Concept,
    ConceptSource,
    Course,
    CourseGroup,
    FocusSession,
    LearningEvent,
    Note,
    Question,
    QuestionConcept,
    Quiz,
    QuizItem,
    ReviewState,
    Source,
    SourceSection,
    StudyTarget,
    User,
)
from . import assistants, check_first, mastery
from .attempts import assessments_for
from .folders import tree as folder_tree
from .learning import effective_status
from .quizzes import results_view
from .reviews import effective_assessment
from .sources import source_view
from .targets import active_target, duplicate_groups, live_targets, target_view


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
        "version": quiz.version,
        "retake_of": str(quiz.retake_of) if quiz.retake_of else None,
        "same_day_practice": quiz.same_day_practice,
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
    checks = check_first.results(db, user.id, [c.id for c in concepts])
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
                "check": checks.get(c.id),
            }
        )
    targets = live_targets(db, course.id)
    dupes = duplicate_groups(targets)
    active = active_target(targets, today)
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at.desc()))
    folders = folder_tree(db, user.id)
    return {
        "course": course_view(course),
        "active_target_id": str(active.id) if active else None,
        "targets": [
            {**target_view(db, t, today), "duplicates": [str(d) for d in dupes.get(t.id, [])]} for t in targets
        ],
        "progress": {"study": study, "bands": bands, "concepts": len(concepts)},
        "concepts": rows,
        "chapters": [
            {"key": g["key"], "title": g["title"], "concept_ids": [str(c) for c in g["concept_ids"]]}
            for g in check_first.chapters(db, course, concepts)
        ],
        "practice_limit": check_first.practice_limit(db, course, today),
        "sources": [  # archived material (or material in an archived folder) is left out
            view
            for view in (
                source_view(db, s, folders)
                for s in db.scalars(
                    select(Source)
                    .where(Source.course_id == course.id, Source.deleted_at.is_(None))
                    .order_by(Source.uploaded_at)
                )
            )
            if not view["hidden"]
        ],
        "notes": db.scalar(
            select(func.count()).select_from(Note).where(Note.course_id == course.id, Note.deleted_at.is_(None))
        ),
        "quizzes": [quiz_summary(db, q) for q in quizzes],
        "note": mastery_note(),
    }


def course_view(course: Course) -> dict[str, Any]:
    return {
        "id": str(course.id),
        "title": course.title,
        "description": course.description,
        "status": course.status,
        "kind": course.kind,
        "focus_until": course.focus_until.isoformat() if course.focus_until else None,
        "color": course.color,
        "group_id": str(course.group_id) if course.group_id else None,
        "long_term_retention": course.long_term_retention,
        "created_at": course.created_at.isoformat(),
    }


def group_view(group: CourseGroup, course_count: int) -> dict[str, Any]:
    return {
        "id": str(group.id),
        "parent_id": str(group.parent_id) if group.parent_id else None,
        "kind": group.kind,
        "name": group.name,
        "position": group.position,
        "status": group.status,
        "starts_on": group.starts_on.isoformat() if group.starts_on else None,
        "ends_on": group.ends_on.isoformat() if group.ends_on else None,
        "archived_at": group.archived_at.isoformat() if group.archived_at else None,
        "courses": course_count,
    }


def groups(db: Session, user: User) -> list[dict[str, Any]]:
    counts = dict(
        db.execute(
            select(Course.group_id, func.count())
            .where(Course.user_id == user.id, Course.deleted_at.is_(None), Course.group_id.is_not(None))
            .group_by(Course.group_id)
        ).all()
    )
    rows = db.scalars(
        select(CourseGroup)
        .where(CourseGroup.user_id == user.id, CourseGroup.deleted_at.is_(None))
        .order_by(CourseGroup.position, CourseGroup.created_at)
    )
    return [group_view(g, counts.get(g.id, 0)) for g in rows]


def group_path(db: Session, group_id: uuid.UUID | None) -> list[str]:
    """Names from the top (university) down to the course's own group (semester)."""
    names: list[str] = []
    seen: set[uuid.UUID] = set()
    while group_id is not None and group_id not in seen:
        seen.add(group_id)
        group = db.get(CourseGroup, group_id)
        if group is None:
            break
        names.append(group.name)
        group_id = group.parent_id
    return list(reversed(names))


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
                "unsure": a.guessing,
                "captured_via": a.captured_via,
                "submitted_at": a.submitted_at.isoformat(),
                "status": a.status,
                "quiz": {"id": str(quiz.id), "title": quiz.title, "mode": quiz.mode} if quiz else None,
                "grade": eff.grade if eff else None,
                "assessment_status": eff.status if eff else None,
                "graded_by": eff.evaluator_kind if eff else None,
                "grader": assistants.grader(eff.evaluator_kind, eff.provider, eff.model) if eff else None,
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
        .join(Course, Course.id == Question.course_id)
        .where(Attempt.user_id == user.id, Course.deleted_at.is_(None))
        .order_by(Attempt.submitted_at.desc())
        .limit(limit)
    )
    if course_id is not None:
        stmt = stmt.where(Question.course_id == course_id)
    rows = db.execute(stmt).all()
    # Results → Answers (2026-11-27): which concepts each answer was about, so a row reads "concept · feedback".
    terms: dict[uuid.UUID, list[dict[str, str]]] = {}
    if rows:
        for question_id, concept_id, term in db.execute(
            select(QuestionConcept.question_id, Concept.id, Concept.term)
            .join(Concept, Concept.id == QuestionConcept.concept_id)
            .where(QuestionConcept.question_id.in_({q.id for _, q in rows}), Concept.deleted_at.is_(None))
            .order_by(Concept.term)
        ).all():
            terms.setdefault(question_id, []).append({"id": str(concept_id), "term": term})
    out = []
    for attempt, question in rows:
        eff = effective_assessment(assessments_for(db, attempt.id))
        out.append(
            {
                "attempt_id": str(attempt.id),
                "course_id": str(question.course_id),
                "question_id": str(question.id),
                "concepts": terms.get(question.id, []),
                "feedback": eff.feedback if eff else None,
                "question": question.prompt,
                "question_type": question.question_type,
                "bloom_level": question.bloom_level,
                "kind": attempt.kind,
                "unsure": attempt.guessing,  # Unsure (open) or I'm guessing (closed), as the learner marked it
                "captured_via": attempt.captured_via,
                "status": attempt.status,
                "submitted_at": attempt.submitted_at.isoformat(),
                "quiz_id": str(attempt.quiz_id) if attempt.quiz_id else None,
                "grade": eff.grade if eff else None,
                "assessment_status": eff.status if eff else None,
                "graded_by": eff.evaluator_kind if eff else None,
                "grader": assistants.grader(eff.evaluator_kind, eff.provider, eff.model) if eff else None,
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
    "assessment.self_assessed": "You assessed your answer",
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
    "study.focus_changed": "Focus changed",
    "course.goal_changed": "Interest goal changed",
    "backup.created": "Backup made",
    "backup.failed": "Backup failed",
    "backup.folder_changed": "Backup folder changed",
    "backup.schedule_changed": "Backup schedule changed",
    "backup.encryption_on": "Backup encryption turned on",
    "backup.key_replaced": "New recovery key for backups",
    "backup.unencrypted_removed": "Unencrypted backups removed",
    "review.defer": "Review deferred",
    "assessment.grade_override": "Grade overridden",
    "auth.login": "Signed in",
    "auth.logout": "Signed out",
    "focus.completed": "Focus block finished",
    "focus.stopped": "Focus block stopped early",
    "focus.deleted": "Focus block removed",
    "focus.restored": "Focus block restored",
}


def _detail(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "assessment.recorded":
        provider, model = payload.get("provider"), payload.get("model")
        if provider is None and model is None:
            who = "RecallSpring"
        else:  # connector grades before 2026-11 had no provider in the event: they came from Claude
            who = assistants.provider_name(provider or "claude_app") + (f" ({model})" if model else "")
        grade = payload.get("grade")
        return f"{grade_text(grade)} ({payload.get('status')}) by {who}" if grade is not None else f"ungraded by {who}"
    if event_type == "source.parsed":
        n = payload.get("sections")
        return f"{payload.get('state')}, {n} section{'' if n == 1 else 's'}"
    if event_type == "attempt.submitted":
        via = {"answer_form": "answer form", "assistant_transcription": "copied by your assistant", "app_ui": "web app"}
        return f"{payload.get('kind')} via {via.get(payload.get('captured_via'), payload.get('captured_via'))}"
    if event_type == "assessment.self_assessed":
        return (
            f"{grade_text(payload.get('grade'))} (provisional; suggested {grade_text(payload.get('suggested'))}), "
            "to be checked"
        )
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
    if event_type == "backup.created":
        check = {"restored": "checked by a test restore", "listed": "dump read back"}.get(
            payload.get("check"), "not checked"
        )
        return f"{payload.get('rows')} rows, {payload.get('files')} files, {check}"
    if event_type == "backup.failed":
        return str(payload.get("message") or payload.get("code"))
    if event_type in ("backup.folder_changed", "backup.schedule_changed"):
        return f"{payload.get('from')} → {payload.get('to')}"
    if event_type in ("backup.encryption_on", "backup.key_replaced"):
        return f"key {payload.get('key_id')}"
    if event_type == "backup.unencrypted_removed":
        n = payload.get("count")
        return f"{n} backup{'' if n == 1 else 's'}"
    if event_type in ("focus.completed", "focus.stopped"):
        return f"{payload.get('minutes')} of {payload.get('planned_minutes')} min"
    if event_type in ("focus.deleted", "focus.restored"):
        return f"{payload.get('minutes')} min"
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
    if ids := by_type.get("focus_session"):
        for eid, title in db.execute(
            select(FocusSession.id, Course.title)
            .outerjoin(Course, Course.id == FocusSession.course_id)
            .where(FocusSession.id.in_(ids))
        ).all():
            labels[eid] = title or "No course"
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
            "detail": _detail(a.action, a.details) if a.action.startswith(("backup.", "focus.")) else None,
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
    """Things that need the learner: a failed or overdue backup, duplicate exams, failed extractions, open
    simulations, answers waiting for feedback."""
    items: list[dict[str, Any]] = []
    if item := backup.attention_item():
        items.append(item)
    live = list(
        db.scalars(
            select(StudyTarget)
            .join(Course, Course.id == StudyTarget.course_id)
            .where(StudyTarget.user_id == user.id, StudyTarget.deleted_at.is_(None), Course.deleted_at.is_(None))
        )
    )
    seen: set[frozenset[uuid.UUID]] = set()
    for target_id, others in duplicate_groups(live).items():
        group = frozenset([target_id, *others])
        if group in seen:
            continue
        seen.add(group)
        members = [t for t in live if t.id in group]
        course = db.get(Course, members[0].course_id)
        items.append(
            {
                "kind": "duplicates",
                "id": str(target_id),
                "course_id": str(members[0].course_id),
                "title": f"{course.title if course else 'A course'}: {len(members)} entries for the same exam",
                "text": " and ".join(f"{t.name} ({t.due_date.isoformat()})" for t in members)
                + ". Merge them or delete one in Exams.",
            }
        )
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
                "text": "Saved; feedback is still pending. Ask your assistant to grade them.",
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
        # With nothing coming up, the most recent exam that is behind the learner (passed, failed, cancelled or its
        # date gone), so the card does not read as if there never was one (owner 2026-11-23).
        behind = [t for t in view["targets"] if t["status"] != "upcoming" or t["days_left"] < 0]
        last = max(behind, key=lambda t: t["due_date"]) if behind and not active else None
        out.append(
            {
                **view["course"],
                "group_path": group_path(db, course.group_id),
                "active_target": {k: active[k] for k in ("id", "kind", "name", "due_date", "days_left", "status")}
                if active
                else None,
                "last_target": {k: last[k] for k in ("id", "kind", "name", "due_date", "days_left", "status")}
                if last
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


def targets_timeline(db: Session, user: User) -> list[dict[str, Any]]:
    """Every exam and kolokvij of courses that are not deleted, with the course's name and colour, and the other
    exams of the same course that look like the same one (possible duplicates from parallel chats)."""
    today = clock.now().astimezone(ZoneInfo(user.timezone)).date()
    rows = db.execute(
        select(StudyTarget, Course)
        .join(Course, Course.id == StudyTarget.course_id)
        .where(StudyTarget.user_id == user.id, StudyTarget.deleted_at.is_(None), Course.deleted_at.is_(None))
        .order_by(StudyTarget.due_date, StudyTarget.created_at)
    ).all()
    dupes = duplicate_groups([t for t, _ in rows])
    quiz_counts = dict(
        db.execute(
            select(Quiz.target_id, func.count())
            .where(Quiz.user_id == user.id, Quiz.target_id.is_not(None))
            .group_by(Quiz.target_id)
        ).all()
    )
    return [
        {
            **target_view(db, t, today),
            "course_id": str(c.id),
            "course_title": c.title,
            "course_color": c.color,
            "course_status": c.status,
            "revision": t.revision,
            "created_at": t.created_at.isoformat(),
            "simulations": quiz_counts.get(t.id, 0),
            "duplicates": [str(d) for d in dupes.get(t.id, [])],
        }
        for t, c in rows
    ]


def deleted_targets(db: Session, user: User, days: int) -> list[dict[str, Any]]:
    since = clock.now() - timedelta(days=days)
    rows = db.execute(
        select(StudyTarget, Course)
        .join(Course, Course.id == StudyTarget.course_id)
        .where(StudyTarget.user_id == user.id, StudyTarget.deleted_at.is_not(None), StudyTarget.deleted_at >= since)
        .order_by(StudyTarget.deleted_at.desc())
    ).all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "kind": t.kind,
            "due_date": t.due_date.isoformat(),
            "course_id": str(c.id),
            "course_title": c.title,
            "course_color": c.color,
            "deleted_at": t.deleted_at.isoformat() if t.deleted_at else None,
        }
        for t, c in rows
    ]
