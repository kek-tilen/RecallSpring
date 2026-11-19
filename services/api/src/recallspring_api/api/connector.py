"""Claude connector surface (Mode A): read learning data and append records. No destructive operations exist here.

Source and note text is returned marked as untrusted learner material; the MCP server wraps it accordingly.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
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
from ..models import (
    Assessment,
    Attempt,
    Concept,
    ConceptSource,
    Course,
    Note,
    Question,
    ReviewState,
    Source,
    SourceSection,
    StudySession,
    SyllabusItem,
)
from ..schemas import (
    ConnectorAssessmentIn,
    ConnectorAttemptIn,
    ConnectorQuestionsIn,
    ConnectorSessionIn,
    ConnectorSummaryIn,
    PlanOut,
    ReviewQueueOut,
    SearchHitOut,
    SearchOut,
    StudySessionOut,
)
from ..services import attempts as attempt_svc
from ..services import sources as source_svc
from ..services.events import learning_event
from ..services.ownership import owned
from ..services.planner import today_plan
from ..services.reviews import concept_ids_for_question, recompute, review_queue
from .attempts import save_attempt
from .questions import _add_question, _course_concepts, question_view
from .reviews import _item as review_item

router = APIRouter(prefix="/connector", tags=["connector"])

UNTRUSTED = "learner_material"  # marker the MCP server turns into an untrusted-content wrapper


@router.get("/plan", response_model=PlanOut)
def plan(
    minutes: int = Query(default=20, ge=5, le=240), ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return today_plan(db, ctx.user, clock.now(), minutes)


@router.get("/courses")
def courses(ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    now = clock.now()
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
                "status": c.status,
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
    for c in db.scalars(
        select(Concept).where(Concept.course_id == course_id, Concept.deleted_at.is_(None)).order_by(Concept.term)
    ):
        state = db.get(ReviewState, (ctx.user.id, c.id))
        links = [str(s) for s in db.scalars(select(ConceptSource.section_id).where(ConceptSource.concept_id == c.id))]
        concepts.append(
            {
                "id": str(c.id),
                "term": c.term,
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
            }
        )
    sources = [
        {
            k: v
            for k, v in source_svc.source_view(db, s).items()
            if k in ("id", "filename", "kind", "parse_state", "parse_message", "section_count", "page_count")
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
        "sources": sources,
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
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "topic_id": str(n.syllabus_item_id) if n.syllabus_item_id else None,
            "revision": n.revision,
            "saved_at": n.saved_at.isoformat(),
            "body": n.body[:limit],
            "truncated": len(n.body) > limit,
            "content_kind": UNTRUSTED,
        }
        for n in db.scalars(stmt.order_by(Note.saved_at.desc()))
    ]


@router.get("/reviews/due", response_model=ReviewQueueOut)
def due(
    horizon_days: int = Query(default=0, ge=0, le=60), ctx: Ctx = Depends(connector_ctx), db: Session = Depends(get_db)
) -> ReviewQueueOut:
    now = clock.now()
    return ReviewQueueOut(
        items=[review_item(s, c, now) for s, c in review_queue(db, ctx.user, now, horizon_days)], generated_at=now
    )


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
    provenance = {"origin": "claude_connector", "model": payload.model_name, "model_reported_by": "assistant"}
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
    return question_view(db, owned(db, Question, question_id, ctx.user.id), ctx.user.id)


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
    return {
        **attempt_svc.attempt_view(db, attempt),
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
        provider="claude_app",
        model=payload.model_name,
        model_reported_by="assistant",
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
            "provider": "claude_app",
            "model": payload.model_name,
            "flags": flags,
        },
        request_id=ctx.request_id,
    )
    now = clock.now()
    schedules = recompute(db, ctx.user, concept_ids_for_question(db, attempt.question_id), now)
    body = {
        **attempt_svc.attempt_view(db, attempt),
        "schedule": [
            {"concept_id": str(cid), "due_at": s.due_at.isoformat(), "reason": s.reason.message}
            for cid, s in schedules.items()
            if s is not None
        ],
    }
    return commit_with_response(db, ctx, payload, 200, body)
