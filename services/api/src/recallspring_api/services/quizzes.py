"""Exam simulations (kolokvij practice): several questions in one form, drafts, persist-first submission,
deterministic grading of multiple-choice items and a points summary. Open answers are graded by Claude."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError, not_found
from ..models import (
    Attempt,
    Concept,
    Course,
    Question,
    QuestionConcept,
    Quiz,
    QuizItem,
    StudySession,
    StudyTarget,
    User,
)
from ..schemas import QuizAnswer, QuizIn
from .attempts import add_assessment, assessments_for, create_attempt
from .events import learning_event
from .learning import mark, require_studied
from .reviews import concept_ids_for_question, effective_assessment, recompute
from .sources import parse_refs, sections_in_course

MCQ_RUBRIC = "mcq-key-v1"


def _check_concepts(db: Session, user_id: uuid.UUID, course_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    found = set(
        db.scalars(
            select(Concept.id).where(
                Concept.id.in_(ids),
                Concept.user_id == user_id,
                Concept.course_id == course_id,
                Concept.deleted_at.is_(None),
            )
        )
    )
    if found != set(ids):
        raise ApiError(404, "not_found", "One or more concepts were not found in this course.")


def create_quiz(db: Session, user: User, payload: QuizIn, provenance: dict[str, Any]) -> Quiz:
    course = db.get(Course, payload.course_id)
    if course is None or course.user_id != user.id or course.deleted_at is not None:
        raise not_found("Course")
    if payload.target_id is not None:
        target = db.get(StudyTarget, payload.target_id)
        if target is None or target.user_id != user.id or target.course_id != payload.course_id:
            raise not_found("Study target")
    if payload.session_id is not None:
        session = db.get(StudySession, payload.session_id)
        if session is None or session.user_id != user.id:
            raise not_found("Session")
    if payload.mode == "practice":  # learning first (ADR-006): no practice simulation on unstudied material
        require_studied(db, user.id, [cid for item in payload.items for cid in item.concept_ids])
    now = clock.now()
    quiz = Quiz(
        user_id=user.id,
        course_id=payload.course_id,
        target_id=payload.target_id,
        session_id=payload.session_id,
        title=payload.title,
        time_limit_minutes=payload.time_limit_minutes,
        mode=payload.mode,
        provenance=provenance,
        created_at=now,
    )
    db.add(quiz)
    db.flush()
    for position, item in enumerate(payload.items, start=1):
        _check_concepts(db, user.id, payload.course_id, item.concept_ids)
        sections_in_course(db, user.id, payload.course_id, parse_refs(item.source_refs))
        rubric: dict[str, Any] = {"expected_points": item.expected_points}
        options = None
        if item.type == "mcq":
            keys = [o.key for o in item.options]
            if len(keys) < 2 or len(set(keys)) != len(keys) or item.correct_option not in keys:
                raise ApiError(
                    422,
                    "invalid_mcq",
                    f"Item {position}: give 2-8 options with unique keys and the correct option among them.",
                )
            options = [o.model_dump() for o in item.options]
            rubric["correct_option"] = item.correct_option
        elif item.options or item.correct_option:
            raise ApiError(422, "invalid_item", f"Item {position}: open questions have no options.")
        question = Question(
            user_id=user.id,
            course_id=payload.course_id,
            bloom_level=item.bloom_level,
            prompt=item.prompt,
            rubric=rubric,
            source_refs=item.source_refs,
            question_type=item.type,
            options=options,
            provenance={**provenance, "quiz_id": str(quiz.id), "style": item.style},
            created_at=now,
        )
        db.add(question)
        db.flush()
        for cid in dict.fromkeys(item.concept_ids):
            db.add(QuestionConcept(question_id=question.id, concept_id=cid))
        db.add(QuizItem(quiz_id=quiz.id, position=position, question_id=question.id, points=item.points))
    db.flush()
    learning_event(
        db,
        user_id=user.id,
        entity_type="quiz",
        entity_id=quiz.id,
        event_type="quiz.created",
        payload={"items": len(payload.items), **provenance},
        request_id=None,
    )
    return quiz


def _items(db: Session, quiz: Quiz) -> list[tuple[QuizItem, Question]]:
    return [
        (item, question)
        for item, question in db.execute(
            select(QuizItem, Question)
            .join(Question, Question.id == QuizItem.question_id)
            .where(QuizItem.quiz_id == quiz.id)
            .order_by(QuizItem.position)
        )
    ]


def deadline(quiz: Quiz) -> datetime | None:
    if quiz.time_limit_minutes and quiz.opened_at:
        return quiz.opened_at + timedelta(minutes=quiz.time_limit_minutes)
    return None


def form_view(db: Session, quiz: Quiz) -> dict[str, Any]:
    """What the learner's form needs. Answer keys and rubrics are only included after submission."""
    submitted = quiz.status == "submitted"
    view: dict[str, Any] = {
        "quiz_id": str(quiz.id),
        "title": quiz.title,
        "status": quiz.status,
        "mode": quiz.mode,
        "time_limit_minutes": quiz.time_limit_minutes,
        "opened_at": quiz.opened_at.isoformat() if quiz.opened_at else None,
        "deadline": deadline(quiz).isoformat() if deadline(quiz) else None,
        "draft": quiz.draft.get("answers", {}),
        "draft_saved_at": quiz.draft_saved_at.isoformat() if quiz.draft_saved_at else None,
        "items": [
            {
                "question_id": str(q.id),
                "position": item.position,
                "type": q.question_type,
                "prompt": q.prompt,
                "options": q.options,
                "points": item.points,
                "bloom_level": q.bloom_level,
            }
            for item, q in _items(db, quiz)
        ],
    }
    if submitted:
        view["results"] = results_view(db, quiz, for_learner=True)
    return view


def mark_opened(quiz: Quiz) -> None:
    if quiz.opened_at is None and quiz.status == "open":
        quiz.opened_at = clock.now()


def _answers_map(answers: list[QuizAnswer]) -> dict[str, dict[str, Any]]:
    return {str(a.question_id): a.model_dump(mode="json", exclude={"question_id"}) for a in answers}


def save_draft(quiz: Quiz, answers: list[QuizAnswer]) -> None:
    if quiz.status != "open":
        raise ApiError(409, "quiz_submitted", "This simulation was already submitted.")
    quiz.draft = {"answers": _answers_map(answers)}
    quiz.draft_revision += 1
    quiz.draft_saved_at = clock.now()


def submit(
    db: Session, user: User, quiz: Quiz, client_request_id: uuid.UUID, answers: list[QuizAnswer], request_id: str
) -> None:
    """Persist every answer exactly (one transaction), then grade multiple-choice items from the hidden key.
    Items left empty count as "I don't know"."""
    if quiz.status == "submitted":
        return
    items = _items(db, quiz)
    known = {str(q.id) for _, q in items}
    given = _answers_map(answers)
    if set(given) - known:
        raise ApiError(422, "unknown_question", "An answer refers to a question that is not in this simulation.")
    merged = {**quiz.draft.get("answers", {}), **given}
    now = clock.now()
    for _, question in items:
        answer = merged.get(str(question.id), {})
        option = answer.get("option")
        text = answer.get("text") or ""
        if question.question_type == "mcq":
            keys = {o["key"]: o["text"] for o in (question.options or [])}
            if option is not None and option not in keys:
                raise ApiError(422, "invalid_option", "An answer selects an option that does not exist.")
            answered = option is not None and not answer.get("dont_know")
            answer_text = f"{option}) {keys[option]}" if answered else ""
        else:
            answered = bool(text.strip()) and not answer.get("dont_know")
            answer_text = text if answered else ""
        attempt = create_attempt(
            db,
            user=user,
            question=question,
            session_id=quiz.session_id,
            client_request_id=uuid.uuid5(client_request_id, str(question.id)),
            kind="answer" if answered else "dont_know",
            answer_text=answer_text,
            answer_mode="closed_notes",
            captured_via="answer_form",
            request_id=request_id,
        )
        attempt.quiz_id = quiz.id
        if question.question_type == "mcq" and answered:
            attempt.selected_option = option
            correct = question.rubric.get("correct_option")
            right = option == correct
            add_assessment(
                db,
                user_id=user.id,
                attempt=attempt,
                data={
                    "rubric_version": MCQ_RUBRIC,
                    "status": "final",
                    "grade": 3 if right else 0,
                    "confidence": "medium" if right else "high",
                    "feedback": f"Correct: {option}) {keys[option]}."
                    if right
                    else f"You chose {option}); the correct answer is {correct}) {keys[correct]}.",
                },
                evaluator_kind="deterministic",
                provider=None,
                model=None,
                model_reported_by=None,
                simulated=False,
                flags=[],
            )
            attempt.status = "evaluated"
            db.flush()
            recompute(db, user, concept_ids_for_question(db, question.id), now)
    quiz.status = "submitted"
    quiz.submitted_at = now
    learning_event(
        db,
        user_id=user.id,
        entity_type="quiz",
        entity_id=quiz.id,
        event_type="quiz.submitted",
        payload={"items": len(items), "mode": quiz.mode},
        request_id=request_id,
    )
    if quiz.mode == "diagnostic":
        apply_diagnostic(db, user, quiz, request_id)


def apply_diagnostic(db: Session, user: User, quiz: Quiz, request_id: str | None) -> list[dict[str, Any]]:
    """A concept shown in a diagnostic pre-test (every item on it graded final, not low confidence, grade >= 3)
    is marked *known*, so its learning step can be shortened; everything else stays to be learned. Concepts with
    ungraded items wait. Called after submission and after each grade."""
    if quiz.mode != "diagnostic":
        return []
    attempts = {a.question_id: a for a in db.scalars(select(Attempt).where(Attempt.quiz_id == quiz.id))}
    verdict: dict[uuid.UUID, str] = {}  # "yes" | "no" | "pending"
    for _, question in _items(db, quiz):
        attempt = attempts.get(question.id)
        eff = effective_assessment(assessments_for(db, attempt.id)) if attempt else None
        if attempt is not None and eff is None:
            outcome = "pending"
        elif eff is not None and eff.status == "final" and eff.confidence != "low" and (eff.grade or 0) >= 3:
            outcome = "yes"
        else:
            outcome = "no"
        for concept_id in concept_ids_for_question(db, question.id):
            pair = (verdict.get(concept_id, "yes"), outcome)
            verdict[concept_id] = "no" if "no" in pair else ("pending" if "pending" in pair else "yes")
    known_ids = [cid for cid, v in verdict.items() if v == "yes"]
    concepts = list(db.scalars(select(Concept).where(Concept.id.in_(known_ids)))) if known_ids else []
    return mark(db, user, concepts, "known", "diagnostic", request_id)


def results_view(db: Session, quiz: Quiz, *, for_learner: bool = False) -> dict[str, Any]:
    """Per-item answers, grades and points. Open items wait for Claude's grade (``pending``)."""
    attempts = {a.question_id: a for a in db.scalars(select(Attempt).where(Attempt.quiz_id == quiz.id))}
    out_items = []
    earned = 0.0
    max_points = 0
    pending = 0
    for item, question in _items(db, quiz):
        max_points += item.points
        attempt = attempts.get(question.id)
        eff = effective_assessment(assessments_for(db, attempt.id)) if attempt else None
        points: float | None
        if attempt is None:
            points = None
        elif eff is None:
            points = None
            pending += 1
        elif question.question_type == "mcq":
            points = float(item.points) if (eff.grade or 0) >= 3 else 0.0
        else:
            points = round(item.points * (eff.grade or 0) / 4, 2)
        if points is not None:
            earned += points
        entry: dict[str, Any] = {
            "position": item.position,
            "question_id": str(question.id),
            "attempt_id": str(attempt.id) if attempt else None,
            "type": question.question_type,
            "prompt": question.prompt,
            "options": question.options,
            "points": item.points,
            "earned": points,
            "answer": attempt.answer_text if attempt else None,
            "kind": attempt.kind if attempt else None,
            "grade": eff.grade if eff else None,
            "assessment_status": eff.status if eff else None,
            "feedback": eff.feedback if eff else None,
            "graded_by": (eff.evaluator_kind if eff else None),
        }
        if question.question_type == "mcq":
            entry["correct_option"] = question.rubric.get("correct_option")
        if not for_learner:
            entry["expected_points"] = question.rubric.get("expected_points", [])
            entry["source_refs"] = question.source_refs
        out_items.append(entry)
    return {
        "quiz_id": str(quiz.id),
        "title": quiz.title,
        "status": quiz.status,
        "submitted_at": quiz.submitted_at.isoformat() if quiz.submitted_at else None,
        "earned_points": round(earned, 2),
        "max_points": max_points,
        "pending_items": pending,
        "complete": pending == 0 and quiz.status == "submitted",
        "mode": quiz.mode,
        "items": out_items,
        "note": (
            "Diagnostic pre-test: it shows what you already know and does not change your review schedule. "
            if quiz.mode == "diagnostic"
            else ""
        )
        + "Open answers are graded by Claude (an AI estimate you can challenge); multiple-choice items are "
        "graded by RecallSpring from the answer key.",
    }
