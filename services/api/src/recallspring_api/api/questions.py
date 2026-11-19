from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .. import clock
from ..ai.provider import ProviderError
from ..ai.registry import provider_for
from ..ai.tasks import QUESTION_PROMPT_VERSION, build_question_request, validate_questions
from ..config import get_settings
from ..db import get_db, new_session
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import ApiError
from ..models import Attempt, Concept, Course, Question, QuestionConcept
from ..schemas import QuestionGenerateIn, QuestionIn, QuestionListOut, QuestionOut
from ..services.events import learning_event
from ..services.ownership import owned

router = APIRouter(tags=["questions"])


def question_view(db: Session, q: Question, user_id: uuid.UUID) -> dict[str, Any]:
    concept_ids = list(db.scalars(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == q.id)))
    answered = db.scalar(select(exists().where(Attempt.question_id == q.id, Attempt.user_id == user_id)))
    return QuestionOut(
        id=q.id,
        course_id=q.course_id,
        concept_ids=concept_ids,
        bloom_level=q.bloom_level,
        prompt=q.prompt,
        source_refs=q.source_refs,
        difficulty=q.difficulty,
        provenance=q.provenance,
        created_at=q.created_at,
        rubric=q.rubric if answered else None,
    ).model_dump(mode="json")


def _course_concepts(
    db: Session, user_id: uuid.UUID, course_id: uuid.UUID, concept_ids: list[uuid.UUID]
) -> list[Concept]:
    owned(db, Course, course_id, user_id)
    concepts = list(
        db.scalars(
            select(Concept).where(
                Concept.id.in_(concept_ids),
                Concept.user_id == user_id,
                Concept.course_id == course_id,
                Concept.deleted_at.is_(None),
            )
        )
    )
    if len(concepts) != len(set(concept_ids)):
        raise ApiError(404, "not_found", "One or more concepts were not found in this course.")
    return concepts


def _add_question(
    db: Session,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    concept_ids: list[uuid.UUID],
    bloom_level: int,
    prompt: str,
    expected_points: list[str],
    source_refs: list[str],
    difficulty: int | None,
    provenance: dict[str, Any],
) -> Question:
    q = Question(
        user_id=user_id,
        course_id=course_id,
        bloom_level=bloom_level,
        prompt=prompt,
        rubric={"expected_points": expected_points},
        source_refs=source_refs,
        difficulty=difficulty,
        provenance=provenance,
        created_at=clock.now(),
    )
    db.add(q)
    db.flush()
    for cid in dict.fromkeys(concept_ids):
        db.add(QuestionConcept(question_id=q.id, concept_id=cid))
    db.flush()
    return q


@router.post("/questions", status_code=201, response_model=QuestionOut)
def create_question(
    payload: QuestionIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """A question written by the learner (or later by the connector) with a hidden rubric."""
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    _course_concepts(db, ctx.user.id, payload.course_id, payload.concept_ids)
    q = _add_question(
        db,
        user_id=ctx.user.id,
        course_id=payload.course_id,
        concept_ids=payload.concept_ids,
        bloom_level=payload.bloom_level,
        prompt=payload.prompt,
        expected_points=payload.expected_points,
        source_refs=payload.source_refs,
        difficulty=payload.difficulty,
        provenance={"origin": "learner"},
    )
    return commit_with_response(db, ctx, payload, 201, question_view(db, q, ctx.user.id))


@router.post("/questions/generate", status_code=201, response_model=QuestionListOut)
async def generate_questions(payload: QuestionGenerateIn, ctx: WriteCtx = Depends(write_ctx)) -> JSONResponse:
    """User-initiated, provider-backed question generation (Mode B). Never runs in the background."""

    def prepare() -> tuple[JSONResponse | None, list[dict[str, Any]]]:
        with new_session() as db:
            if replay := replay_if_seen(db, ctx, payload):
                return replay, []
            concepts = _course_concepts(db, ctx.user.id, payload.course_id, payload.concept_ids)
            return None, [{"id": str(c.id), "term": c.term, "definition": c.definition_draft} for c in concepts]

    replay, concepts = await run_in_threadpool(prepare)
    if replay is not None:
        return replay
    levels = sorted(payload.bloom_levels) if payload.order == "progressive" else list(payload.bloom_levels)
    try:
        provider, model = provider_for("question_generation")
        request = build_question_request(model=model, concepts=concepts, bloom_levels=levels, allowed_refs=[])
        result = await asyncio.wait_for(provider.generate_structured(request), get_settings().ai_timeout_seconds)
        items = validate_questions(result.data, {c["id"] for c in concepts}, set(levels), allowed_refs=[])
    except TimeoutError as exc:
        raise ApiError(
            503,
            "generation_unavailable",
            "Questions could not be generated right now.",
            {"reason": "ai_timeout", "retryable": True},
        ) from exc
    except ProviderError as exc:
        raise ApiError(
            503,
            "generation_unavailable",
            "Questions could not be generated right now.",
            {"reason": exc.code, "retryable": exc.retryable},
        ) from exc

    def persist() -> JSONResponse:
        with new_session() as db:
            provenance = {
                "origin": "ai",
                "provider": result.provider,
                "model": result.model,
                "simulated": result.simulated,
                "prompt_version": QUESTION_PROMPT_VERSION,
            }
            created = [
                _add_question(
                    db,
                    user_id=ctx.user.id,
                    course_id=payload.course_id,
                    concept_ids=[uuid.UUID(c) for c in item["concept_ids"]],
                    bloom_level=item["bloom_level"],
                    prompt=item["prompt"],
                    expected_points=item["expected_points"],
                    source_refs=item["source_refs"],
                    difficulty=None,
                    provenance=provenance,
                )
                for item in items
            ]
            for q in created:
                learning_event(
                    db,
                    user_id=ctx.user.id,
                    entity_type="question",
                    entity_id=q.id,
                    event_type="question.generated",
                    payload=provenance,
                    request_id=ctx.request_id,
                )
            body = {"questions": [question_view(db, q, ctx.user.id) for q in created]}
            return commit_with_response(db, ctx, payload, 201, body)

    return await run_in_threadpool(persist)


@router.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(
    question_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return question_view(db, owned(db, Question, question_id, ctx.user.id), ctx.user.id)
