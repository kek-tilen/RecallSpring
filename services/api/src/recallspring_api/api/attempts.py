from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock
from ..ai.provider import ProviderError, SourceExcerpt, StructuredRequest
from ..ai.registry import provider_for
from ..ai.tasks import EVALUATION_PROMPT_VERSION, build_evaluation_request, validate_assessment
from ..config import get_settings
from ..db import get_db, new_session
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..models import Assessment, Attempt, Question, StudySession
from ..schemas import AttemptCreatedOut, AttemptIn, AttemptOut, ChallengeIn
from ..services import attempts as svc
from ..services.events import learning_event
from ..services.ownership import owned
from ..services.reviews import concept_ids_for_question, recompute
from ..services.sources import parse_refs, sections_in_course

router = APIRouter(tags=["attempts"])


def _created_body(attempt: Attempt) -> dict[str, Any]:
    return AttemptCreatedOut(attempt_id=attempt.id, status=attempt.status, saved_at=attempt.submitted_at).model_dump(
        mode="json"
    )


def _existing_for_client_request(db: Session, ctx: WriteCtx, payload: AttemptIn) -> JSONResponse:
    """Same client_request_id seen before (e.g. an outbox replay with a new key): never store a duplicate."""
    existing = svc.find_by_client_request(db, ctx.user.id, payload.client_request_id)
    assert existing is not None
    if existing.question_id != payload.question_id or existing.answer_text != payload.answer_text:
        raise ApiError(
            409, "client_request_id_conflict", "This client_request_id was already used for a different answer."
        )
    return JSONResponse(_created_body(existing), status_code=200, headers={"Idempotent-Replay": "true"})


@router.post("/attempts", status_code=201, response_model=AttemptCreatedOut)
def create_attempt(
    payload: AttemptIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Durably save the learner's exact answer. The 201 is sent only after the database commit (FR-09)."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    if svc.find_by_client_request(db, ctx.user.id, payload.client_request_id) is not None:
        return _existing_for_client_request(db, ctx, payload)
    question = owned(db, Question, payload.question_id, ctx.user.id)
    if payload.session_id is not None:
        owned(db, StudySession, payload.session_id, ctx.user.id)
    if len(payload.answer_text) > get_settings().max_answer_chars:
        raise ApiError(422, "answer_too_long", "The answer is too long to save.")
    try:
        attempt = svc.create_attempt(
            db,
            user=ctx.user,
            question=question,
            session_id=payload.session_id,
            client_request_id=payload.client_request_id,
            kind=payload.kind,
            answer_text=payload.answer_text,
            answer_mode=payload.answer_mode,
            captured_via="app_ui",
            request_id=ctx.request_id,
        )
    except IntegrityError:
        db.rollback()
        return _existing_for_client_request(db, ctx, payload)
    return commit_with_response(db, ctx, payload, 201, _created_body(attempt))


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(
    attempt_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return svc.attempt_view(db, owned(db, Attempt, attempt_id, ctx.user.id))


@router.post("/attempts/{attempt_id}/evaluate", response_model=AttemptOut)
async def evaluate_attempt(attempt_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx)) -> JSONResponse:
    """User-initiated evaluation by the configured in-app provider. Safe to retry; never duplicates grades.

    Phase 1 claims the attempt in its own transaction, phase 2 calls the provider outside any transaction,
    phase 3 validates and appends the assessment (or releases the claim) in a new transaction.
    """
    settings = get_settings()
    try:
        provider, model = provider_for("evaluation")
    except ProviderError as exc:
        raise ApiError(
            409, "ai_not_configured", "No in-app AI provider is configured for evaluation.", {"reason": exc.code}
        ) from exc

    def claim() -> tuple[JSONResponse | None, datetime | None, StructuredRequest | None, list[str]]:
        with new_session() as db:
            if replay := replay_if_seen(db, ctx, None):
                return replay, None, None, []
            attempt = owned(db, Attempt, attempt_id, ctx.user.id, for_update=True)
            claimed_at = svc.claim_evaluation(db, attempt, settings.ai_evaluation_lease_seconds)
            if claimed_at is None:  # already evaluated: idempotent, no second grade
                return JSONResponse(svc.attempt_view(db, attempt)), None, None, []
            question = db.get(Question, attempt.question_id)
            assert question is not None
            excerpts = [
                SourceExcerpt(str(s.id), s.citation_label, s.text)
                for s in sections_in_course(db, ctx.user.id, question.course_id, parse_refs(question.source_refs))
            ]
            allowed_refs = [e.section_id for e in excerpts]
            request = build_evaluation_request(
                model=model,
                question_prompt=question.prompt,
                bloom_level=question.bloom_level,
                expected_points=list(question.rubric.get("expected_points", [])),
                answer_text=attempt.answer_text,
                answer_mode=attempt.answer_mode,
                sources=excerpts,
            )
            db.commit()
            return None, claimed_at, request, allowed_refs

    early, claimed_at, request, allowed_refs = await run_in_threadpool(claim)
    if early is not None:
        return early
    assert claimed_at is not None and request is not None

    failure: str | None = None
    try:
        result = await asyncio.wait_for(provider.generate_structured(request), settings.ai_timeout_seconds)
        data, flags = validate_assessment(result.data, attempt_id, allowed_refs)
    except TimeoutError:
        failure = "ai_timeout"
    except ProviderError as exc:
        failure = exc.code

    def finish() -> JSONResponse:
        with new_session() as db:
            attempt = owned(db, Attempt, attempt_id, ctx.user.id, for_update=True)
            if failure is not None:
                svc.release_failed_claim(db, attempt, claimed_at, failure, ctx.request_id)
                db.commit()
                raise ApiError(
                    503,
                    "evaluation_unavailable",
                    "Answer saved. Feedback is unavailable right now; you can retry later.",
                    {"attempt_id": str(attempt_id), "status": attempt.status, "reason": failure, "retryable": True},
                )
            if not svc.holds_claim(attempt, claimed_at):
                raise ApiError(409, "evaluation_superseded", "This evaluation was superseded by a newer one.")
            row: Assessment = svc.add_assessment(
                db,
                user_id=ctx.user.id,
                attempt=attempt,
                data=data,
                evaluator_kind="ai",
                provider=result.provider,
                model=result.model,
                model_reported_by="provider",
                simulated=result.simulated,
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
                    "attempt_id": str(attempt_id),
                    "status": row.status,
                    "grade": row.grade,
                    "provider": row.provider,
                    "model": row.model,
                    "simulated": row.simulated,
                    "prompt_version": EVALUATION_PROMPT_VERSION,
                    "flags": flags,
                },
                request_id=ctx.request_id,
            )
            recompute(db, ctx.user, concept_ids_for_question(db, attempt.question_id), clock.now())
            return commit_with_response(db, ctx, None, 200, svc.attempt_view(db, attempt))

    return await run_in_threadpool(finish)


@router.post("/assessments/{assessment_id}/challenge", response_model=AttemptOut)
def challenge_assessment(
    assessment_id: uuid.UUID, payload: ChallengeIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Record disagreement; with ``corrected_grade`` it appends a human assessment and recomputes the schedule."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    original = db.get(Assessment, assessment_id)
    if original is None or original.user_id != ctx.user.id:
        raise ApiError(404, "not_found", "Assessment not found.")
    attempt = owned(db, Attempt, original.attempt_id, ctx.user.id, for_update=True)
    svc.record_correction(
        db,
        user=ctx.user,
        attempt=attempt,
        original=original,
        reason=payload.reason,
        corrected_grade=payload.corrected_grade,
        request_id=ctx.request_id,
    )
    return commit_with_response(db, ctx, payload, 200, svc.attempt_view(db, attempt))
