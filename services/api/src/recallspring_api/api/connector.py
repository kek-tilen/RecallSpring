"""Claude connector surface (Mode A): read learning data and append records. No destructive operations exist here.

Source and note text is returned marked as untrusted learner material; the MCP server wraps it accordingly.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..ai.provider import ProviderInvalidOutput
from ..ai.tasks import validate_assessment
from ..config import get_settings
from ..connector_auth import connector_ctx, connector_write_ctx
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, replay_if_seen
from ..errors import ApiError
from ..ingest import renderer, visuals
from ..ingest.storage import blob_path
from ..learning.grading import GRADE_NAMES, GRADING_SCALE, TELL_THE_LEARNER, UNSURE_NOTE
from ..models import (
    Assessment,
    Attempt,
    AvailabilityOverride,
    Concept,
    ConceptSource,
    Course,
    CourseGroup,
    Note,
    Question,
    Quiz,
    ReviewState,
    Source,
    SourceSection,
    StudySession,
    StudyTarget,
    SyllabusItem,
    TargetProfile,
    User,
)
from ..schemas import (
    AssessmentBatchIn,
    AvailabilityIn,
    ChatNoteIn,
    ConnectorAssessmentIn,
    ConnectorAttemptIn,
    ConnectorConceptsIn,
    ConnectorPaceIn,
    ConnectorQuestionsIn,
    ConnectorSessionIn,
    ConnectorSourceTextIn,
    ConnectorSummaryIn,
    CourseIn,
    CourseOut,
    DifficultyIn,
    ExplanationFeedbackIn,
    ExplanationVersionIn,
    FocusIn,
    InterestGoalIn,
    KnownConceptsIn,
    LearningSummaryIn,
    MaterialCategory,
    OrganiseCoursesIn,
    PlanOut,
    ProfileConfirmIn,
    ProfilePaperIn,
    QuizDraftIn,
    QuizIn,
    QuizSubmitIn,
    RetakeIn,
    ReviewQueueOut,
    SearchHitOut,
    SearchOut,
    StudySessionOut,
    TargetIn,
    TargetProfileIn,
    TargetUpdateIn,
    WebSourceIn,
)
from ..services import assistants, bloom, check_first, explanation_pace, focus, overview, readiness, relearn, week
from ..services import attempts as attempt_svc
from ..services import explanations as explanation_svc
from ..services import folders as folder_svc
from ..services import interests as interest_svc
from ..services import quizzes as quiz_svc
from ..services import rationale as rationale_svc
from ..services import self_assessment as self_svc
from ..services import sources as source_svc
from ..services import targets as target_svc
from ..services.courses import ensure_new_title
from ..services.events import audit, learning_event
from ..services.learning import effective_status, mark, require_studied, save_summary
from ..services.learning import save_chat_note as save_chat_note_svc
from ..services.note_refs import references as note_references
from ..services.ownership import course_alive, owned
from ..services.planner import today_plan
from ..services.reviews import concept_ids_for_question, recompute, refresh_exam_overlays, review_queue
from ..services.targets import (
    check_profile_topics,
    computed_topics,
    evidence_gaps,
    papers_not_looked_at,
    study_context,
    target_view,
)
from ..services.targets import confirm_profile as confirm_exam_profile
from .attempts import save_attempt
from .questions import _add_question, _course_concepts, question_view
from .reviews import _item as review_item
from .settings import apply_study_settings
from .sources import handle_paste, handle_upload, handle_web

router = APIRouter(prefix="/connector", tags=["connector"])

UNTRUSTED = "learner_material"  # marker the MCP server turns into an untrusted-content wrapper


@router.get("/plan", response_model=PlanOut)
def plan(
    minutes: int | None = Query(default=None, ge=0, le=720, description="Default: today's availability"),
    course_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """All courses (overview) or one course; respects study targets, maintenance share and availability."""
    if course_id is not None:
        owned(db, Course, course_id, ctx.user.id)
    return today_plan(db, ctx.user, clock.now(), minutes, course_id)


@router.get("/targets/{target_id}/rationale")
def plan_rationale(
    target_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Why this plan (ADR-013 §2), computed by RecallSpring: explain it, never add claims it does not contain."""
    return rationale_svc.rationale(db, ctx.user, target_id, clock.now())


@router.get("/readiness")
def exam_readiness(
    target_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """What is left before an exam (``target_id``, or the next exam of ``course_id``): states by material, the
    weakest concepts with the gaps from their last feedback, next steps and the time check."""
    now = clock.now()
    if target_id is None:
        if course_id is None:
            raise ApiError(422, "target_or_course_required", "Give target_id or course_id.")
        target_id = readiness.for_course(db, ctx.user, course_id, now)
    return readiness.compact(readiness.readiness(db, ctx.user, target_id, now))


@router.get("/week")
def week_review(
    weeks_ago: int = Query(default=0, ge=0, le=52),
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Weekly review: activity, grades and their trend, study time, overdue reviews and the next exams."""
    return week.week_review(db, ctx.user, clock.now(), weeks_ago)


@router.get("/courses")
def courses(ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    now = clock.now()
    refresh_exam_overlays(db, ctx.user, now)
    rows = db.scalars(
        select(Course).where(Course.user_id == ctx.user.id, Course.deleted_at.is_(None)).order_by(Course.created_at)
    )
    out = []
    for c in rows:
        concept_count = db.scalar(
            select(func.count()).select_from(Concept).where(Concept.course_id == c.id, Concept.deleted_at.is_(None))
        )
        due = db.scalar(
            select(func.count())
            .select_from(ReviewState)
            .join(Concept, Concept.id == ReviewState.concept_id)
            .where(Concept.course_id == c.id, ReviewState.user_id == ctx.user.id, ReviewState.due_at <= now)
        )
        sources = db.scalar(
            select(func.count()).select_from(Source).where(Source.course_id == c.id, Source.deleted_at.is_(None))
        )
        out.append(
            {
                "id": str(c.id),
                "title": c.title,
                "kind": c.kind,
                "goal": c.description if c.kind == "interest" else None,
                "focus_until": c.focus_until.isoformat() if c.focus_until else None,
                "status": c.status,
                "semester": " › ".join(overview.group_path(db, c.group_id)) or None,
                "concepts": concept_count,
                "due_reviews": due,
                "sources": sources,
            }
        )
    return out


@router.get("/courses/{course_id}/outline")
def outline(course_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    course = owned(db, Course, course_id, ctx.user.id)
    now = clock.now()
    topics = db.scalars(
        select(SyllabusItem)
        .where(SyllabusItem.course_id == course_id, SyllabusItem.deleted_at.is_(None))
        .order_by(SyllabusItem.position)
    )
    concepts = []
    rows = list(
        db.scalars(
            select(Concept).where(Concept.course_id == course_id, Concept.deleted_at.is_(None)).order_by(Concept.term)
        )
    )
    # The next practice level per concept (3 → 4 → 5, then mixed; services/bloom.py), only for studied concepts,
    # never above the learner's practice limit; and what Check first would ask (services/check_first.py).
    today = _today(ctx)
    levels = bloom.suggestions(db, ctx.user.id, [c.id for c in rows], check_first.ceiling(db, course))
    states = {c.id: db.get(ReviewState, (ctx.user.id, c.id)) for c in rows}
    statuses = {c.id: effective_status(c, states[c.id] is not None) for c in rows}
    check = check_first.plan(db, course, rows, statuses, levels, today)
    for c in rows:
        state = states[c.id]
        status = statuses[c.id]
        links = [str(s) for s in db.scalars(select(ConceptSource.section_id).where(ConceptSource.concept_id == c.id))]
        concepts.append(
            {
                "id": str(c.id),
                "term": c.term,
                "study_status": status,
                "definition_draft": c.definition_draft,
                "topic_id": str(c.syllabus_item_id) if c.syllabus_item_id else None,
                "source_section_ids": links,
                "review": None
                if state is None
                else {
                    "due_at": state.due_at.isoformat(),
                    "is_due": state.due_at <= now,
                    "step": state.step,
                    "reason": state.due_reason.get("message"),
                    "evidence_count": state.evidence_count,
                },
                "practice": None if status == "not_studied" else levels[c.id],
                "check": check["concepts"][c.id],
            }
        )
    folder_tree = folder_svc.tree(db, ctx.user.id)
    sources = [
        {
            k: v
            for k, v in source_svc.source_view(db, s, folder_tree).items()
            if k
            in (
                "id",
                "filename",
                "kind",
                "category",
                "folder",
                "hidden",
                "parse_state",
                "parse_message",
                "section_count",
                "page_count",
            )
        }
        for s in db.scalars(
            select(Source)
            .where(Source.course_id == course_id, Source.deleted_at.is_(None))
            .order_by(Source.uploaded_at)
        )
    ]
    return {
        "course": {"id": str(course.id), "title": course.title, "description": course.description},
        "topics": [
            {"id": str(t.id), "title": t.title, "parent_id": str(t.parent_id) if t.parent_id else None} for t in topics
        ],
        "concepts": concepts,
        "practice_limit": check_first.practice_limit(db, course, today),
        "check_first": {k: check[k] for k in ("how", "chapters", "everything", "closed_share")},
        "sources": sources,
        "folders": [
            folder_tree.path(f.id)
            for f in folder_tree.by_id.values()
            if f.course_id == course_id and not folder_tree.hidden(f.id)
        ],
    }


@router.get("/sources/search", response_model=SearchOut)
def search(
    q: str = Query(min_length=1, max_length=200),
    course_id: uuid.UUID | None = None,
    limit: int = Query(default=5, ge=1, le=20),
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> SearchOut:
    rows = source_svc.search_sections(db, ctx.user.id, q, course_id, limit)
    return SearchOut(hits=[SearchHitOut(**dict(r)) for r in rows])


@router.get("/sections/{section_id}")
def section(section_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    sec = owned(db, SourceSection, section_id, ctx.user.id)
    src = db.get(Source, sec.source_id)
    if src is None or src.deleted_at is not None:
        raise ApiError(404, "not_found", "Section not found.")
    return {
        **source_svc.section_view(sec),
        "filename": src.filename,
        "course_id": str(src.course_id),
        "content_kind": UNTRUSTED,
    }


@router.get("/notes")
def notes(
    course_id: uuid.UUID,
    topic_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    owned(db, Course, course_id, ctx.user.id)
    limit = get_settings().connector_note_chars
    stmt = select(Note).where(Note.user_id == ctx.user.id, Note.course_id == course_id, Note.deleted_at.is_(None))
    if topic_id is not None:
        stmt = stmt.where(Note.syllabus_item_id == topic_id)
    rows = list(db.scalars(stmt.order_by(Note.saved_at.desc())))
    refs = note_references(db, ctx.user.id, rows)
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "topic_id": str(n.syllabus_item_id) if n.syllabus_item_id else None,
            "revision": n.revision,
            "saved_at": n.saved_at.isoformat(),
            "captured_via": n.captured_via,
            "body": n.body[:limit],
            "truncated": len(n.body) > limit,
            # Files the note links as [name](source:<id>): the source_id works with get_source_status,
            # view_image (pictures) and view_page; missing ones were deleted.
            "references": [
                {"source_id": r["id"], "filename": r["filename"], "kind": r["kind"], "missing": r["missing"]}
                for r in refs[n.id]
            ],
            "content_kind": UNTRUSTED,
        }
        for n in rows
    ]


@router.get("/reviews/due", response_model=ReviewQueueOut)
def due(
    horizon_days: int = Query(default=0, ge=0, le=60),
    course_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> ReviewQueueOut:
    now = clock.now()
    rows = [
        (s, c)
        for s, c in review_queue(db, ctx.user, now, horizon_days)
        if course_id is None or c.course_id == course_id
    ]
    return ReviewQueueOut(items=[review_item(s, c, now) for s, c in rows], generated_at=now)


@router.post("/study-sessions", status_code=201, response_model=StudySessionOut)
def start_session(
    payload: ConnectorSessionIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if payload.course_id is not None:
        owned(db, Course, payload.course_id, ctx.user.id)
    row = StudySession(
        user_id=ctx.user.id, course_id=payload.course_id, mode=payload.mode, origin="connector", started_at=clock.now()
    )
    db.add(row)
    db.flush()
    return commit_with_response(db, ctx, payload, 201, StudySessionOut.model_validate(row).model_dump(mode="json"))


@router.post("/study-sessions/{session_id}/summary", response_model=StudySessionOut)
def session_summary(
    session_id: uuid.UUID,
    payload: ConnectorSummaryIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    row = owned(db, StudySession, session_id, ctx.user.id, for_update=True)
    if row.summary is not None:
        raise ApiError(409, "summary_exists", "This study session already has a summary.")
    row.summary = payload.summary
    row.ended_at = clock.now()
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="study_session",
        entity_id=row.id,
        event_type="study_session.summarised",
        payload={"origin": "connector"},
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 200, StudySessionOut.model_validate(row).model_dump(mode="json"))


@router.post("/questions", status_code=201)
def create_questions(
    payload: ConnectorQuestionsIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Questions written by Claude in the Claude app. Rubrics stay hidden from the learner until they answer."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    provenance = assistants.provenance(ctx.client, ctx.model, payload.model_name)
    require_studied(db, ctx.user.id, [cid for item in payload.questions for cid in item.concept_ids])
    check_first.require_within_limit(
        db, ctx.user.id, payload.course_id, [item.bloom_level for item in payload.questions]
    )
    created = []
    for item in payload.questions:
        _course_concepts(db, ctx.user.id, payload.course_id, item.concept_ids)
        source_svc.sections_in_course(db, ctx.user.id, payload.course_id, source_svc.parse_refs(item.source_refs))
        q = _add_question(
            db,
            user_id=ctx.user.id,
            course_id=payload.course_id,
            concept_ids=item.concept_ids,
            bloom_level=item.bloom_level,
            prompt=item.prompt,
            expected_points=item.expected_points,
            source_refs=item.source_refs,
            difficulty=item.difficulty,
            provenance=provenance,
        )
        learning_event(
            db,
            user_id=ctx.user.id,
            entity_type="question",
            entity_id=q.id,
            event_type="question.generated",
            payload=provenance,
            request_id=ctx.request_id,
        )
        created.append(q)
    body = {"questions": [question_view(db, q, ctx.user.id) for q in created]}
    return commit_with_response(db, ctx, payload, 201, body)


@router.get("/questions/{question_id}")
def get_question(
    question_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The question, and its latest answer if any: the learner may have answered in the RecallSpring web app (from
    the link an assistant gives when it cannot show the answer form)."""
    question = owned(db, Question, question_id, ctx.user.id)
    latest = db.scalar(
        select(Attempt)
        .where(Attempt.question_id == question.id, Attempt.user_id == ctx.user.id)
        .order_by(Attempt.submitted_at.desc())
        .limit(1)
    )
    view = question_view(db, question, ctx.user.id)
    view["latest_attempt"] = (
        {
            "attempt_id": str(latest.id),
            "status": latest.status,
            "captured_via": latest.captured_via,
            "submitted_at": latest.submitted_at.isoformat(),
        }
        if latest
        else None
    )
    return view


@router.post("/attempts", status_code=201)
def submit_attempt(
    payload: ConnectorAttemptIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Persist-first answer capture from the connector's answer form (exact typed text) or, as a fallback,
    from Claude's transcription of a chat answer."""
    return save_attempt(db, ctx, payload, captured_via=payload.captured_via)


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Everything needed to grade: exact answer, question, rubric (an attempt exists) and cited sections."""
    attempt = owned(db, Attempt, attempt_id, ctx.user.id)
    question = db.get(Question, attempt.question_id)
    assert question is not None
    sections = source_svc.sections_in_course(
        db, ctx.user.id, question.course_id, source_svc.parse_refs(question.source_refs)
    )
    unsure = attempt.guessing and question.question_type != "mcq"
    return {
        **attempt_svc.attempt_view(db, attempt),
        "grading_scale": GRADING_SCALE,
        **({"unsure_note": UNSURE_NOTE} if unsure else {}),
        "question": question_view(db, question, ctx.user.id),
        "sources": [
            {
                "section_id": str(s.id),
                "citation_label": s.citation_label,
                "text": s.text[:2500],
                "content_kind": UNTRUSTED,
            }
            for s in sections
        ],
    }


@router.post("/attempts/{attempt_id}/assessments")
def record_assessment(
    attempt_id: uuid.UUID,
    payload: ConnectorAssessmentIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Claude's grade, validated server-side. Evidence must be real sections of the question's course;
    unknown references are dropped and a final grade becomes provisional. Appends, never overwrites."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    body = record_one_assessment(db, ctx, attempt_id, payload)
    return commit_with_response(db, ctx, payload, 200, body)


def record_one_assessment(
    db: Session, ctx: WriteCtx, attempt_id: uuid.UUID, payload: ConnectorAssessmentIn
) -> dict[str, Any]:
    """Validate and append one assessment written by Claude; the caller commits."""
    attempt = owned(db, Attempt, attempt_id, ctx.user.id, for_update=True)
    if attempt.kind != "answer":
        raise ApiError(409, "not_evaluable", "Only written answers can be assessed.")
    if db.scalar(select(Assessment.id).where(Assessment.attempt_id == attempt.id, Assessment.evaluator_kind == "ai")):
        raise ApiError(
            409,
            "already_assessed",
            "This answer already has an AI assessment. The learner can challenge it in RecallSpring.",
        )
    question = db.get(Question, attempt.question_id)
    assert question is not None
    own = next((a for a in attempt_svc.assessments_for(db, attempt.id) if a.evaluator_kind == "self"), None)
    candidate_ids = []
    for ref in payload.evidence_refs:
        try:
            candidate_ids.append(uuid.UUID(ref))
        except ValueError:
            continue
    allowed = [
        str(s)
        for s in db.scalars(
            select(SourceSection.id)
            .join(Source, Source.id == SourceSection.source_id)
            .where(
                SourceSection.id.in_(candidate_ids),
                SourceSection.user_id == ctx.user.id,
                Source.course_id == question.course_id,
            )
        )
    ]
    raw = payload.model_dump(exclude={"model_name"})
    if raw.get("rubric_scores") is None:
        raw.pop("rubric_scores", None)
    try:
        data, flags = validate_assessment(raw, attempt.id, allowed)
    except ProviderInvalidOutput as exc:
        raise ApiError(422, "invalid_assessment", "The assessment is not valid.", {"reason": str(exc)}) from exc
    row = attempt_svc.add_assessment(
        db,
        user_id=ctx.user.id,
        attempt=attempt,
        data=data,
        evaluator_kind="ai",
        provider=assistants.provider_for(ctx.client),
        model=ctx.model or payload.model_name,
        model_reported_by="provider" if ctx.model else "assistant",
        simulated=False,
        flags=flags,
    )
    attempt.status = "evaluated"
    attempt.last_evaluation_error = None
    db.flush()
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="assessment",
        entity_id=row.id,
        event_type="assessment.recorded",
        payload={
            "attempt_id": str(attempt.id),
            "status": row.status,
            "grade": row.grade,
            "provider": assistants.provider_for(ctx.client),
            "model": ctx.model or payload.model_name,
            "flags": flags,
        },
        request_id=ctx.request_id,
    )
    now = clock.now()
    schedules = recompute(db, ctx.user, concept_ids_for_question(db, attempt.question_id), now)
    if attempt.quiz_id is not None:
        quiz = db.get(Quiz, attempt.quiz_id)
        if quiz is not None and quiz.mode == "diagnostic":
            quiz_svc.apply_diagnostic(db, ctx.user, quiz, ctx.request_id)
    body = {
        **attempt_svc.attempt_view(db, attempt),
        "schedule": [
            {"concept_id": str(cid), "due_at": s.due_at.isoformat(), "reason": s.reason.message}
            for cid, s in schedules.items()
            if s is not None
        ],
        "grade_name": GRADE_NAMES.get(row.grade) if row.grade is not None else None,
        "tell_the_learner": TELL_THE_LEARNER,
    }
    course = db.get(Course, question.course_id)
    offer = bloom.harder_offer(db, ctx.user.id, attempt, check_first.ceiling(db, course)) if course else None
    if offer is not None:
        body["offer_harder"] = offer  # owner 2026-11-25: harder questions once learning goes well
    again = relearn.offer(db, ctx.user, attempt, now)
    if again is not None:
        body["relearn"] = again  # ADR-014: weak before an exam, another try later in the session
    if own is not None:
        # The learner had graded this answer themselves; tell them when the check differs by 2 or more.
        body["self_assessment"] = {
            "grade": own.grade,
            "differs": own.grade is not None and row.grade is not None and abs(own.grade - row.grade) >= 2,
        }
    return body


# ---------------------------------------------------------------- building the library from Claude (append-only)


@router.post("/courses", status_code=201, response_model=CourseOut)
def create_course(
    payload: CourseIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    ensure_new_title(db, ctx.user.id, payload.title)
    course = Course(user_id=ctx.user.id, **payload.model_dump())
    db.add(course)
    db.flush()
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="course",
        entity_id=course.id,
        event_type="course.created",
        payload={"origin": "connector"},
        request_id=ctx.request_id,
    )
    db.flush()
    db.refresh(course)
    return commit_with_response(db, ctx, payload, 201, CourseOut.model_validate(course).model_dump(mode="json"))


@router.post("/courses/{course_id}/concepts", status_code=201)
def create_concepts(
    course_id: uuid.UUID,
    payload: ConnectorConceptsIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Concepts proposed by Claude from the learner's material. Each links to real source sections or is marked
    ``inferred``; an existing term in the course is reused instead of duplicated."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, course_id, ctx.user.id)
    existing = {
        c.term.casefold(): c
        for c in db.scalars(select(Concept).where(Concept.course_id == course_id, Concept.deleted_at.is_(None)))
    }
    out = []
    for item in payload.concepts:
        sections = source_svc.sections_in_course(db, ctx.user.id, course_id, item.source_section_ids)
        if item.topic_id is not None:
            topic = db.get(SyllabusItem, item.topic_id)
            if topic is None or topic.user_id != ctx.user.id or topic.course_id != course_id:
                raise ApiError(404, "not_found", "Topic not found.")
        concept = existing.get(item.term.casefold())
        created = concept is None
        if concept is None:
            concept = Concept(
                user_id=ctx.user.id,
                course_id=course_id,
                term=item.term,
                definition_draft=item.definition_draft,
                syllabus_item_id=item.topic_id,
                source_confidence="medium" if sections else "inferred",
            )
            db.add(concept)
            db.flush()
            existing[item.term.casefold()] = concept
        linked = set(db.scalars(select(ConceptSource.section_id).where(ConceptSource.concept_id == concept.id)))
        for section in sections:
            if section.id not in linked:
                db.add(ConceptSource(concept_id=concept.id, section_id=section.id))
        db.flush()
        out.append(
            {
                "id": str(concept.id),
                "term": concept.term,
                "created": created,
                "source_section_ids": [str(s.id) for s in sections],
            }
        )
    return commit_with_response(db, ctx, payload, 201, {"concepts": out})


@router.post("/sources/text", status_code=201)
def add_text_source(
    payload: ConnectorSourceTextIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if payload.folder and payload.folder_id is None:
        folder = folder_svc.resolve_path(db, ctx.user, payload.course_id, payload.folder, ctx.request_id)
        payload = payload.model_copy(update={"folder_id": folder.id if folder else None})
    return handle_paste(payload, ctx, db)


@router.post("/sources/web", status_code=201)
def add_web_source(
    payload: WebSourceIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Only after the learner agreed: what you read on the web for something on an old paper that the course
    material does not cover, saved apart from the material with the pages it came from (ADR-013 §5)."""
    folder = folder_svc.resolve_path(db, ctx.user, payload.course_id, payload.folder, ctx.request_id)
    return handle_web(payload, ctx, db, folder.id if folder else None)


@router.post("/sources", status_code=201)
def import_file(
    request: Request,
    course_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    category: MaterialCategory = Form("material"),
    folder: str | None = Form(None, max_length=600),
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """A local file the learner asked the connector to import (same checks as the web upload), optionally into a
    folder named by its path ("Lectures / Week 3"; missing folders are created)."""
    target = folder_svc.resolve_path(db, ctx.user, course_id, folder, ctx.request_id)
    return handle_upload(request, course_id, file, ctx, db, category, target.id if target else None)


@router.get("/sources/{source_id}")
def source_status(
    source_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Extraction status plus the list of citable sections (IDs and labels only, no text)."""
    source = owned(db, Source, source_id, ctx.user.id)
    sections, total = source_svc.current_sections(db, source, 0, 200)
    return {
        **source_svc.source_view(db, source),
        "sections": [
            {
                "id": str(s.id),
                "citation_label": s.citation_label,
                "heading": s.heading,
                "page": s.page,
                "chars": len(s.text),
            }
            for s in sections
        ],
        "sections_total": total,
    }


# ---------------------------------------------------------------- study targets (kolokvij / izpit) and planning input


def _today(ctx: Ctx):  # type: ignore[no-untyped-def]
    return clock.now().astimezone(ZoneInfo(ctx.user.timezone)).date()


@router.get("/self-assessments")
def self_assessments_to_check(
    course_id: uuid.UUID | None = None, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Answers the learner graded themselves (no assistant was available), oldest first. Check each one: get_attempt,
    then record_assessment by the grading scale; your grade replaces theirs in the review schedule."""
    if course_id is not None:
        owned(db, Course, course_id, ctx.user.id)
    items = self_svc.unchecked(db, ctx.user, course_id)
    return {
        "items": items,
        "how_to_check": "For each: get_attempt(attempt_id), grade it by the grading_scale like any answer with "
        "record_assessment, and tell the learner when your grade differs from theirs by 2 or more, and why.",
    }


@router.get("/courses/{course_id}/context")
def course_context(
    course_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Start of every study session: active target, scope, exam profile, and what to ask the learner if unset."""
    course = owned(db, Course, course_id, ctx.user.id)
    view = study_context(db, course, _today(ctx), ctx.user.style_percent)
    view["learner_preferences"] = (
        {
            "text": ctx.user.study_preferences,
            "how_to_use": "The learner's own words on how they like to study (often brought over from ChatGPT). "
            "Follow them where they fit; they never override RecallSpring's rules on learning first, grading and "
            "citing sources.",
        }
        if ctx.user.study_preferences
        else None
    )
    view["focus_time"] = focus.course_focus(db, ctx.user, course.id, clock.now())
    view["explanation_pace"] = explanation_pace.view(ctx.user, course)
    to_check = self_svc.unchecked(db, ctx.user, course.id)
    view["self_assessments_to_check"] = len(to_check)
    # The oldest few, so an assistant can offer to check them right away (get_answer / get_attempt, then grade).
    view["self_assessments"] = to_check[:10]
    return view


@router.post("/targets", status_code=201)
def create_target(
    payload: TargetIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Record what the learner prepares for, with their own scope description kept verbatim."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = target_svc.create_target(db, ctx.user, payload, ctx.request_id, origin="connector")
    return commit_with_response(db, ctx, payload, 201, target_view(db, target, _today(ctx)))


@router.post("/targets/{target_id}/update")
def update_target(
    target_id: uuid.UUID,
    payload: TargetUpdateIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Move a date, mark a kolokvij passed/failed, or refine the scope. Audited; nothing is deleted."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = target_svc.update_target(db, ctx.user, target_id, payload, ctx.request_id, origin="connector")
    return commit_with_response(db, ctx, payload, 200, target_view(db, target, _today(ctx)))


@router.post("/targets/{target_id}/profile", status_code=201)
def record_profile(
    target_id: uuid.UUID,
    payload: TargetProfileIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Exam profile v2 derived by the assistant from past papers (ADR-013 §1). Every topic names concepts of the
    course or says it is not in the material; RecallSpring computes each topic's share and weight. Saved
    unconfirmed: the assistant then shows the learner the analysis and confirms it only on their yes."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = db.get(StudyTarget, target_id)
    if target is None or target.user_id != ctx.user.id or target.deleted_at is not None:
        raise ApiError(404, "not_found", "Study target not found.")
    papers = list(payload.papers)
    if not papers and payload.source_id is not None:
        papers = [ProfilePaperIn(source_id=payload.source_id)]
    for paper_in in papers:
        if paper_in.source_id is not None:
            paper = owned(db, Source, paper_in.source_id, ctx.user.id)
            if paper.course_id != target.course_id:
                raise ApiError(422, "source_not_in_course", "The old paper must be material of this exam's course.")
    for paper_in in papers:
        files = {paper_in.source_id, *paper_in.extra_source_ids}
        if any(e.source_id not in files for e in paper_in.evidence):
            raise ApiError(
                422,
                "evidence_not_for_paper",
                "Evidence can only name files of its own paper (source_id or extra_source_ids).",
            )
    for source_id in [i for p in papers for i in p.extra_source_ids] + [s.source_id for s in payload.skipped_papers]:
        if owned(db, Source, source_id, ctx.user.id).course_id != target.course_id:
            raise ApiError(422, "source_not_in_course", "The old paper must be material of this exam's course.")
    check_profile_topics(db, ctx.user, target.course_id, payload.topics, papers)
    profile = TargetProfile(
        user_id=ctx.user.id,
        target_id=target.id,
        source_id=papers[0].source_id if papers else None,
        item_types=[t.model_dump() for t in payload.item_types],
        bloom_mix=payload.bloom_mix,
        topic_weights=[],
        example_items=payload.example_items,
        notes=payload.notes,
        model=payload.model_name,
        created_at=clock.now(),
        version=2,
        topics=computed_topics(payload.topics, papers),
        papers=[p.model_dump(mode="json") for p in papers],
        skipped_papers=[s.model_dump(mode="json") for s in payload.skipped_papers],
        unreadable=payload.unreadable,
    )
    db.add(profile)
    db.flush()
    learning_event(
        db,
        user_id=ctx.user.id,
        entity_type="study_target",
        entity_id=target.id,
        event_type="target.profile_recorded",
        payload={"model": payload.model_name, "version": 2, "topics": len(payload.topics), "papers": len(papers)},
        request_id=ctx.request_id,
    )
    body = target_view(db, target, _today(ctx))
    missing = papers_not_looked_at(db, profile)
    body["not_looked_at"] = missing
    check = (
        "These past papers of the course are not in the analysis: "
        + ", ".join(m["filename"] for m in missing)
        + ". Look at each one now (view_image / view_page). Tell the learner what each shows and, when it is unclear "
        "which exam or material it belongs to, ask them. Then record the profile again with every paper in papers "
        "(further photos of the same paper in extra_source_ids) or in skipped_papers with the learner's reason. "
        "confirm_exam_profile is refused until then. "
        if missing
        else ""
    )
    gaps = evidence_gaps(db, profile)
    body["evidence_missing"] = gaps["missing"]
    body["weak_evidence"] = gaps["weak"]
    if gaps["missing"]:
        check += (
            "Say for every file what shows that it belongs to its paper (papers[].evidence with why and strength): "
            + ", ".join(m["filename"] for m in gaps["missing"])
            + ". confirm_exam_profile is refused until then. "
        )
    if gaps["weak"]:
        check += (
            "The evidence is weak for: "
            + "; ".join(f"{w['filename']} ({w['why']})" for w in gaps["weak"])
            + ". Ask the learner whether each of these belongs to that paper before they confirm. "
        )
    body["confirm"] = check + (
        "Saved unconfirmed. Show the learner a short summary (each paper with the exam it was for, each file with "
        "what shows it belongs there, and whether its "
        "topics count or only its style; topics with points and where they are on the paper, item types, Bloom mix, "
        "what you could not read) and ask whether it matches what they know about this exam. "
        "On their yes call confirm_exam_profile with profile.id; on a correction record the profile again."
    )
    return commit_with_response(db, ctx, payload, 201, body)


@router.post("/targets/{target_id}/profile/confirm")
def confirm_profile(
    target_id: uuid.UUID,
    payload: ProfileConfirmIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Only after the learner said the analysis matches the paper: marks the latest analysis confirmed (ADR-013)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    target = confirm_exam_profile(db, ctx.user, target_id, payload.profile_id, "assistant", clock.now(), ctx.request_id)
    return commit_with_response(db, ctx, payload, 200, target_view(db, target, _today(ctx)))


@router.post("/concepts/difficulty")
def set_difficulty(
    payload: DifficultyIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Difficulty prior (1-5). A learner rating is never overwritten by Claude's estimate; observed results win
    over both once there is enough evidence."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    out = []
    for item in payload.items:
        concept = owned(db, Concept, item.concept_id, ctx.user.id, for_update=True)
        if payload.rated_by == "claude" and concept.difficulty_source == "learner":
            out.append({"concept_id": str(concept.id), "difficulty": concept.difficulty_estimate, "kept": "learner"})
            continue
        concept.difficulty_estimate = item.difficulty
        concept.difficulty_source = payload.rated_by
        out.append({"concept_id": str(concept.id), "difficulty": item.difficulty, "kept": payload.rated_by})
    db.flush()
    return commit_with_response(db, ctx, payload, 200, {"concepts": out})


@router.post("/availability")
def set_availability(
    payload: AvailabilityIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Weekly study minutes (Monday first) and/or one day's override. Audited."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    details: dict[str, Any] = {}
    if payload.weekly_minutes is not None:
        details.update(apply_study_settings(user, {"weekly_minutes": payload.weekly_minutes}))
    if payload.interest_percent is not None:
        details.update(apply_study_settings(user, {"interest_percent": payload.interest_percent}))
    if payload.day is not None:
        if payload.minutes is None:
            raise ApiError(422, "minutes_required", "Give the minutes available on that day.")
        row = db.get(AvailabilityOverride, (user.id, payload.day))
        if row is None:
            db.add(AvailabilityOverride(user_id=user.id, day=payload.day, minutes=payload.minutes, note=payload.note))
        else:
            row.minutes, row.note = payload.minutes, payload.note
        details["day"] = {"day": payload.day.isoformat(), "minutes": payload.minutes}
    audit(db, actor_id=user.id, action="study.availability_changed", details=details, request_id=ctx.request_id)
    db.flush()
    body = {"weekly_minutes": user.weekly_minutes, **details, "interest_percent": user.interest_percent}
    return commit_with_response(db, ctx, payload, 200, body)


@router.post("/explanation-pace")
def save_explanation_pace(
    payload: ConnectorPaceIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Save the explanation pace the learner asked for: for one course (pace null = follow the default again) or as
    their default. Only after the learner said yes to saving it. Audited."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    course = None
    if payload.course_id is not None:
        course = owned(db, Course, payload.course_id, user.id)
        explanation_pace.set_for_course(db, user.id, course, payload.pace, ctx.request_id, origin="connector")
    elif payload.pace is None:
        raise ApiError(422, "pace_required", "Give the pace to save as the default.")
    else:
        explanation_pace.set_default(db, user, payload.pace, ctx.request_id, origin="connector")
    db.flush()
    return commit_with_response(db, ctx, payload, 200, explanation_pace.view(user, course))


@router.post("/focus")
def set_focus(
    payload: FocusIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The learner chose to concentrate on one course or interest until a day (default today); ``course_id`` null
    ends the focus. Only on the learner's clear request. Audited."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    user = db.get(User, ctx.user.id, with_for_update=True)
    assert user is not None
    focus = interest_svc.set_focus(db, user, payload.course_id, payload.until, ctx.request_id, origin="connector")
    return commit_with_response(db, ctx, payload, 200, {"focus": focus})


@router.post("/courses/{course_id}/goal")
def set_interest_goal(
    course_id: uuid.UUID,
    payload: InterestGoalIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The learner's goal for a personal interest, in their own words. Audited."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    course = interest_svc.set_goal(db, ctx.user, course_id, payload.goal, ctx.request_id)
    body = {"course_id": str(course.id), "title": course.title, "goal": course.description}
    return commit_with_response(db, ctx, payload, 200, body)


# ---------------------------------------------------------------- exam simulations


def _quiz(db: Session, ctx: Ctx, quiz_id: uuid.UUID, lock: bool = False) -> Quiz:
    quiz = db.get(Quiz, quiz_id, with_for_update=lock)
    if quiz is None or quiz.user_id != ctx.user.id or not course_alive(db, quiz.course_id):
        raise ApiError(404, "not_found", "Simulation not found.")
    return quiz


@router.post("/quizzes", status_code=201)
def create_quiz(
    payload: QuizIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    provenance = assistants.provenance(ctx.client, ctx.model, payload.model_name)
    quiz = quiz_svc.create_quiz(db, ctx.user, payload, provenance)
    body = {
        "quiz_id": str(quiz.id),
        "title": quiz.title,
        "items": len(payload.items),
        "time_limit_minutes": quiz.time_limit_minutes,
    }
    return commit_with_response(db, ctx, payload, 201, body)


@router.get("/quizzes/{quiz_id}")
def quiz_form(quiz_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    return quiz_svc.form_view(db, _quiz(db, ctx, quiz_id))


@router.post("/quizzes/{quiz_id}/open")
def open_quiz(
    quiz_id: uuid.UUID, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Form data without answer keys; starts the clock on first open."""
    quiz = _quiz(db, ctx, quiz_id, lock=True)
    quiz_svc.mark_opened(quiz)
    db.flush()
    body = quiz_svc.form_view(db, quiz)
    db.commit()
    return JSONResponse(body)


@router.post("/quizzes/{quiz_id}/draft")
def save_quiz_draft(
    quiz_id: uuid.UUID,
    payload: QuizDraftIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    quiz = _quiz(db, ctx, quiz_id, lock=True)
    quiz_svc.save_draft(quiz, payload.answers)
    db.commit()
    return JSONResponse(
        {
            "saved_at": quiz.draft_saved_at.isoformat() if quiz.draft_saved_at else None,
            "revision": quiz.draft_revision,
        }
    )


@router.post("/quizzes/{quiz_id}/submit")
def submit_quiz(
    quiz_id: uuid.UUID,
    payload: QuizSubmitIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Persist all answers exactly in one transaction, grade multiple-choice items, return the learner view."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    quiz = _quiz(db, ctx, quiz_id, lock=True)
    quiz_svc.submit(db, ctx.user, quiz, payload.client_request_id, payload.answers, ctx.request_id)
    db.flush()
    return commit_with_response(db, ctx, payload, 200, quiz_svc.results_view(db, quiz, for_learner=True))


@router.get("/quizzes/{quiz_id}/results")
def quiz_results(
    quiz_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Grading view for the assistant: answers, keys, rubrics, which open answers still need a grade and the
    grading scale. With retakes, ``comparison`` shows every version per question (the first is the benchmark)."""
    quiz = _quiz(db, ctx, quiz_id)
    return {
        **quiz_svc.results_view(db, quiz),
        "comparison": quiz_svc.comparison(db, quiz),
        "grading_scale": GRADING_SCALE,
    }


@router.post("/quizzes/{quiz_id}/retake", status_code=201)
def retake_quiz(
    quiz_id: uuid.UUID, payload: RetakeIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Only when the learner asks: a new version of a submitted simulation with the same questions (scope "all", or
    "not_full" = only those without full points). Then open_quiz with the new quiz_id."""
    key = {"retake": str(quiz_id), **payload.model_dump()}
    if replay := replay_if_seen(db, ctx, key):
        return replay
    source = _quiz(db, ctx, quiz_id, lock=True)
    quiz = quiz_svc.retake(db, ctx.user, source, payload.scope, "connector", ctx.request_id)
    body = {
        "quiz_id": str(quiz.id),
        "version": quiz.version,
        "items": len(quiz_svc.form_view(db, quiz)["items"]),
        "time_limit_minutes": quiz.time_limit_minutes,
        "next": "open_quiz with this quiz_id. The same questions again: the first version stays the benchmark, and "
        "taken today after an earlier version it is practice only (it does not change the review schedule).",
    }
    return commit_with_response(db, ctx, key, 201, body)


@router.post("/assessments/batch")
def record_assessments_batch(
    payload: AssessmentBatchIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Grade several attempts (e.g. a simulation's open answers) in one call; all or nothing."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    results = []
    for index, item in enumerate(payload.items):
        try:
            body = record_one_assessment(db, ctx, item.attempt_id, item)
        except ApiError as exc:
            raise ApiError(exc.status, exc.code, exc.message, {"index": index, **(exc.details or {})}) from exc
        latest = body["assessments"][-1]
        results.append(
            {
                "attempt_id": str(item.attempt_id),
                "grade": latest["grade"],
                "grade_name": body["grade_name"],
                "status": latest["status"],
                "schedule": body["schedule"],
                **({"offer_harder": body["offer_harder"]} if "offer_harder" in body else {}),
                **({"relearn": body["relearn"]} if "relearn" in body else {}),
            }
        )
    return commit_with_response(db, ctx, payload, 200, {"results": results, "tell_the_learner": TELL_THE_LEARNER})


# ---------------------------------------------------------------- learning first (ADR-006)


@router.post("/learning", status_code=201)
def save_learning_summary(
    payload: LearningSummaryIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """End of a learning chunk, sent by the summary form: the learner's own summary is stored exactly as a note and
    the concepts become *studied* (practice and simulations are allowed from then on)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, payload.course_id, ctx.user.id)
    body = save_summary(
        db,
        ctx.user,
        course_id=payload.course_id,
        concept_ids=payload.concept_ids,
        title=payload.title,
        text=payload.text,
        client_request_id=payload.client_request_id,
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 201, body)


@router.post("/notes", status_code=201)
def save_chat_note(
    payload: ChatNoteIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """A note or summary the learner gave in the chat, saved only after they confirmed it (ADR-011). Marked as
    transcribed by the assistant; with concept_ids it is a learning summary and those concepts become studied."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, payload.course_id, ctx.user.id)
    body = save_chat_note_svc(
        db,
        ctx.user,
        course_id=payload.course_id,
        title=payload.title,
        text=payload.text,
        concept_ids=payload.concept_ids,
        from_photo=payload.transcribed_from_photo,
        client_request_id=payload.client_request_id,
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 201, body)


# ---------------------------------------------------------------- Concept-to-Clarity (ADR-010)


@router.get("/concepts/{concept_id}/explanation")
def explanation(
    concept_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The learner's explanation of a concept: every version (exact text, source, word limit when it came from an
    exam answer) with the feedback already given, and how to give feedback."""
    return explanation_svc.view(db, ctx.user, concept_id)


@router.post("/concepts/{concept_id}/explanation/versions", status_code=201)
def add_explanation_version(
    concept_id: uuid.UUID,
    payload: ExplanationVersionIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Sent by the C2C form: the learner's own explanation, saved exactly as a new version."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    body = explanation_svc.add_version(
        db,
        ctx.user,
        concept_id,
        text=payload.text,
        source=payload.source,
        client_request_id=payload.client_request_id,
        from_attempt_id=payload.from_attempt_id,
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 201, body)


@router.post("/explanation-versions/{version_id}/feedback")
def record_explanation_feedback(
    version_id: uuid.UUID,
    payload: ExplanationFeedbackIn,
    ctx: WriteCtx = Depends(connector_write_ctx),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The assistant's feedback on one version: correct / missing / wrong with cited sections. Not a grade."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    body = explanation_svc.record_feedback(
        db,
        ctx.user,
        version_id,
        correct=payload.correct,
        missing=payload.missing,
        wrong=payload.wrong,
        evidence_refs=payload.evidence_refs,
        feedback=payload.feedback,
        client=ctx.client,
        model=ctx.model or payload.model_name,
        model_reported_by="provider" if ctx.model else "assistant",
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 200, body)


@router.post("/concepts/known")
def mark_known(
    payload: KnownConceptsIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The learner says they already learned these concepts (e.g. in lectures). Audited with their reason."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    concepts = [owned(db, Concept, cid, ctx.user.id, for_update=True) for cid in dict.fromkeys(payload.concept_ids)]
    out = mark(db, ctx.user, concepts, "known", "self_report", ctx.request_id)
    audit(
        db,
        actor_id=ctx.user.id,
        action="concepts.marked_known",
        details={"concepts": [c["id"] for c in out], "reason": payload.reason},
        request_id=ctx.request_id,
    )
    db.flush()
    return commit_with_response(db, ctx, payload, 200, {"concepts": out})


# ---------------------------------------------------------------- semesters, simulations to grade, images


@router.post("/courses/organise")
def organise_courses(
    payload: OrganiseCoursesIn, ctx: WriteCtx = Depends(connector_write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """File courses under university → faculty → semester by name; missing levels are created. Audited."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    parent_id = None
    created = []
    for kind, name in (
        ("university", payload.university),
        ("faculty", payload.faculty),
        ("semester", payload.semester),
    ):
        if not name:
            continue
        stmt = select(CourseGroup).where(
            CourseGroup.user_id == ctx.user.id,
            CourseGroup.kind == kind,
            func.lower(CourseGroup.name) == name.strip().lower(),
            CourseGroup.deleted_at.is_(None),
        )
        stmt = stmt.where(CourseGroup.parent_id.is_(None) if parent_id is None else CourseGroup.parent_id == parent_id)
        group = db.scalar(stmt.limit(1))
        if group is None:
            group = CourseGroup(user_id=ctx.user.id, kind=kind, name=name.strip(), parent_id=parent_id)
            db.add(group)
            db.flush()
            created.append({"kind": kind, "name": group.name})
        parent_id = group.id
    moved = []
    for course_id in payload.course_ids:
        course = owned(db, Course, course_id, ctx.user.id, for_update=True)
        interest_svc.refuse_interest_filing(course)
        course.group_id = parent_id
        course.revision += 1
        moved.append(course.title)
    db.flush()
    audit(
        db,
        actor_id=ctx.user.id,
        action="courses.organised",
        target_type="course_group",
        target_id=parent_id,
        details={"created": created, "courses": moved, "origin": "connector"},
        request_id=ctx.request_id,
    )
    path = " › ".join(n for n in (payload.university, payload.faculty, payload.semester) if n)
    return commit_with_response(db, ctx, payload, 200, {"placed_in": path, "courses": moved, "created": created})


@router.get("/quizzes")
def list_quizzes(
    course_id: uuid.UUID | None = None,
    needs_grading: bool = False,
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Recent simulations, newest first. needs_grading=true: submitted ones with open answers Claude has not graded
    (for example a simulation the learner answered in the RecallSpring web app)."""
    stmt = (
        select(Quiz)
        .join(Course, Course.id == Quiz.course_id)
        .where(Quiz.user_id == ctx.user.id, Course.deleted_at.is_(None))
        .order_by(Quiz.created_at.desc())
        .limit(30)
    )
    if course_id is not None:
        stmt = stmt.where(Quiz.course_id == course_id)
    rows = [overview.quiz_summary(db, q) for q in db.scalars(stmt)]
    if needs_grading:
        rows = [r for r in rows if r["status"] == "submitted" and (r["pending_items"] or 0) > 0]
    return rows


IMAGE_LIMIT_FOR_CLAUDE = 4_500_000


@router.get("/sources/{source_id}/image")
def source_image(source_id: uuid.UUID, ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)) -> Response:
    """The original image (photo of notes, notebook or exercises) so Claude can look at it on request."""
    source = owned(db, Source, source_id, ctx.user.id)
    if source.kind != "image":
        raise ApiError(409, "not_an_image", "This material is not an image; read its sections instead.")
    path = blob_path(source.storage_key)
    if not path.is_file():
        raise ApiError(410, "original_missing", "The original file is no longer available.")
    headers = {"Cache-Control": "private, no-store"}
    if source.byte_size <= IMAGE_LIMIT_FOR_CLAUDE:
        return Response(path.read_bytes(), media_type=source.mime_type, headers=headers)
    settings = get_settings()  # a large photo: a smaller copy, made in the isolated render process
    try:
        result = visuals.run(
            "image", path, 0, 0, isolation=settings.extraction_isolation, timeout=settings.extraction_timeout_seconds
        )
    except visuals.VisualFailure as exc:
        raise _visual_error(exc.code, 0) from exc
    if not result.images:
        raise ApiError(413, "image_too_large", "This photo could not be made small enough for Claude.")
    smaller = result.images[0]
    return Response(smaller.data, media_type=smaller.mime, headers={**headers, "X-RS-Converted": "true"})


VISUAL_ERRORS = {
    "page_required": (422, "Give the page number (PDF) or the slide number (PowerPoint, OpenDocument slides)."),
    "picture_required": (422, "Give picture=N, as shown by [picture N] in the text."),
    "page_needs_renderer": (
        422,
        "Pages of Word and OpenDocument text files can be shown only when LibreOffice is installed with "
        "RecallSpring. Give picture=N (as [picture N] in the text) instead, or ask the learner for a PDF export.",
    ),
    "page_out_of_range": (422, "There is no such page or slide. This file has {count}."),
    "picture_out_of_range": (422, "There is no picture with that number here."),
    "no_pictures": (
        404,
        "This slide has no embedded pictures. Its shapes, SmartArt and charts can be shown as a whole slide when "
        "LibreOffice is installed with RecallSpring; until then their text is in the slide's section, and for the "
        "drawing itself ask the learner for a screenshot or a PDF export.",
    ),
    "no_visuals": (
        409,
        "Only PDF pages, slides, and pictures inside Word, PowerPoint, OpenDocument files and notebooks can be "
        "viewed this way.",
    ),
    "notebook_unreadable": (422, "This notebook could not be opened to show its pictures."),
    "office_protected": (409, "This file is password-protected, so its pictures can't be shown."),
    "pdf_encrypted": (409, "This PDF is password-protected, so its pages can't be shown."),
    "pdf_unreadable": (422, "This PDF could not be opened to show its pages."),
    "render_failed": (422, "This page could not be rendered."),
    "office_unreadable": (422, "This file could not be opened to show its pictures."),
    "document_too_large": (422, "This file is too large to open safely."),
    "unsafe_document": (422, "This file contains XML features RecallSpring never reads."),
    "content_does_not_match_type": (422, "This file could not be opened to show its pictures."),
    "render_timeout": (504, "Showing this page took too long. Try again, or ask the learner for a screenshot."),
    "renderer_unavailable": (422, "Whole pages of this file can be shown only when LibreOffice is installed."),
    "render_crashed": (502, "Showing this page failed unexpectedly. You can retry."),
}
SKIP_REASONS = {
    "vector_drawing": (
        "a vector drawing (EMF/WMF/SVG); view the whole slide or page instead (needs LibreOffice with "
        "RecallSpring), or ask the learner for a screenshot"
    ),
    "unsupported_format": "a picture format that can't be shown; ask the learner for a screenshot",
    "too_large": "too large for Claude even when made smaller; ask the learner for a screenshot",
    "limit": "not sent in this call (at most 4 pictures per call); ask for it with picture=N",
    "missing": "the file has no data for it",
}


def _visual_error(code: str, count: int) -> ApiError:
    status, message = VISUAL_ERRORS.get(code, (422, "This could not be shown."))
    return ApiError(status, code, message.format(count=count), {"count": count})


VISUAL_KINDS = {"pdf", "pptx", "docx", "odp", "odt", "notebook"}


@router.get("/sources/{source_id}/visual")
def source_visual(
    source_id: uuid.UUID,
    page: int | None = Query(None, ge=1, le=100_000),
    picture: int | None = Query(None, ge=1, le=100_000),
    ctx: Ctx = Depends(connector_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A PDF page rendered as an image, a whole slide or page of an Office/OpenDocument file (when LibreOffice is
    installed), or the pictures inside a slide, document or notebook, so Claude can look at scanned pages,
    diagrams and formulas. Rendering runs in a separate, time-limited process."""
    source = owned(db, Source, source_id, ctx.user.id)
    if source.kind not in VISUAL_KINDS:
        raise _visual_error("no_visuals", 0)
    path = blob_path(source.storage_key)
    if not path.is_file():
        raise ApiError(410, "original_missing", "The original file is no longer available.")
    settings = get_settings()
    kind, target, whole = source.kind, path, False
    if source.kind in renderer.RENDERABLE and page and not picture:
        slides = source.kind in ("pptx", "odp")
        if renderer.available():
            try:
                target = renderer.to_pdf(path, source.sha256, source.kind)
                kind, whole = ("rendered-slides" if slides else "rendered-pages"), True
            except renderer.RenderFailure as exc:
                if not slides:  # slides fall back to their own pictures
                    raise _visual_error(exc.code, 0) from exc
        elif not slides:
            raise _visual_error("page_needs_renderer", 0)
    try:
        result = visuals.run(
            kind,
            target,
            page or 0,
            picture or 0,
            isolation=settings.extraction_isolation,
            timeout=settings.extraction_timeout_seconds,
        )
    except visuals.VisualFailure as exc:
        raise _visual_error(exc.code, 0) from exc
    if result.error:
        raise _visual_error(result.error, result.count)
    return {
        "source_id": str(source.id),
        "filename": source.filename,
        "kind": source.kind,
        "count": result.count,
        "whole_page": whole,
        "images": [
            {
                "label": v.label,
                "mime": v.mime,
                "alt": v.alt,
                "converted": v.converted,
                "data": base64.b64encode(v.data).decode("ascii"),
            }
            for v in result.images
        ],
        "skipped": [{"label": s.label, "reason": s.reason, "message": SKIP_REASONS[s.reason]} for s in result.skipped],
    }
