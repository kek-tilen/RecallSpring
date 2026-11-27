from __future__ import annotations

import uuid
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import not_found
from ..models import Concept, ConceptSource, Course, SourceSection, SyllabusItem
from ..schemas import (
    AssistantKey,
    ConceptIn,
    ConceptOut,
    CourseIn,
    CourseOut,
    ExplanationPace,
    SyllabusItemIn,
    SyllabusItemOut,
)
from ..services import check_first, course_delete, explanation_pace
from ..services.courses import ensure_new_title
from ..services.events import audit, learning_event
from ..services.ownership import owned
from ..services.sources import sections_in_course

router = APIRouter(tags=["courses"])


@router.get("/courses", response_model=list[CourseOut])
def list_courses(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[Course]:
    return list(
        db.scalars(
            select(Course).where(Course.user_id == ctx.user.id, Course.deleted_at.is_(None)).order_by(Course.created_at)
        )
    )


@router.post("/courses", status_code=201, response_model=CourseOut)
def create_course(payload: CourseIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)) -> JSONResponse:
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
        payload={},
        request_id=ctx.request_id,
    )
    db.flush()
    db.refresh(course)
    return commit_with_response(db, ctx, payload, 201, CourseOut.model_validate(course).model_dump(mode="json"))


class CourseDeleteIn(BaseModel):
    """The course name exactly as the learner typed it in the confirmation dialog."""

    confirm_title: str = Field(min_length=1, max_length=200)


def _deleted_view(c: Course) -> dict[str, Any]:
    return {
        **CourseOut.model_validate(c).model_dump(mode="json"),
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
    }


@router.get("/courses/deleted")
def deleted_courses(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Courses deleted in the last 30 days, newest first, so they can be restored."""
    return [_deleted_view(c) for c in course_delete.deleted_courses(db, ctx.user)]


@router.get("/courses/{course_id}/contents")
def course_contents(
    course_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """What deleting this course would hide (counts for the confirmation dialog)."""
    course = owned(db, Course, course_id, ctx.user.id)
    return {
        "title": course.title,
        "counts": course_delete.contents(db, course),
        "restorable_days": course_delete.RESTORE_DAYS,
    }


@router.delete("/courses/{course_id}")
def delete_course(
    course_id: uuid.UUID, payload: CourseDeleteIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """Soft delete of the course and everything in it, only with its exact name; restorable for 30 days."""
    key = {"delete": str(course_id), "confirm_title": payload.confirm_title}
    if replay := replay_if_seen(db, ctx, key):
        return replay
    course = course_delete.delete_course(db, ctx.user, course_id, payload.confirm_title, ctx.request_id)
    body = {"deleted": _deleted_view(course), "restorable_days": course_delete.RESTORE_DAYS}
    return commit_with_response(db, ctx, key, 200, body)


@router.post("/courses/{course_id}/restore", response_model=CourseOut)
def restore_course(
    course_id: uuid.UUID, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    key = {"restore": str(course_id)}
    if replay := replay_if_seen(db, ctx, key):
        return replay
    course = course_delete.restore_course(db, ctx.user, course_id, ctx.request_id)
    return commit_with_response(db, ctx, key, 200, CourseOut.model_validate(course).model_dump(mode="json"))


@router.get("/courses/{course_id}", response_model=CourseOut)
def get_course(course_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> Course:
    return owned(db, Course, course_id, ctx.user.id)


@router.get("/courses/{course_id}/syllabus", response_model=list[SyllabusItemOut])
def list_syllabus(
    course_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> list[SyllabusItem]:
    owned(db, Course, course_id, ctx.user.id)
    return list(
        db.scalars(
            select(SyllabusItem)
            .where(
                SyllabusItem.course_id == course_id,
                SyllabusItem.user_id == ctx.user.id,
                SyllabusItem.deleted_at.is_(None),
            )
            .order_by(SyllabusItem.position, SyllabusItem.created_at)
        )
    )


@router.post("/courses/{course_id}/syllabus", status_code=201, response_model=SyllabusItemOut)
def create_syllabus_item(
    course_id: uuid.UUID, payload: SyllabusItemIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, course_id, ctx.user.id)
    if payload.parent_id is not None:
        parent = db.get(SyllabusItem, payload.parent_id)
        if parent is None or parent.user_id != ctx.user.id or parent.course_id != course_id:
            raise not_found("Parent topic")
    item = SyllabusItem(user_id=ctx.user.id, course_id=course_id, **payload.model_dump())
    db.add(item)
    db.flush()
    db.refresh(item)
    return commit_with_response(db, ctx, payload, 201, SyllabusItemOut.model_validate(item).model_dump(mode="json"))


@router.get("/courses/{course_id}/concepts", response_model=list[ConceptOut])
def list_concepts(
    course_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    owned(db, Course, course_id, ctx.user.id)
    concepts = db.scalars(
        select(Concept)
        .where(Concept.course_id == course_id, Concept.user_id == ctx.user.id, Concept.deleted_at.is_(None))
        .order_by(Concept.term)
    )
    return [concept_view(db, c) for c in concepts]


def concept_view(db: Session, concept: Concept) -> dict[str, Any]:
    section_ids = list(
        db.scalars(
            select(ConceptSource.section_id)
            .join(SourceSection, SourceSection.id == ConceptSource.section_id)
            .where(ConceptSource.concept_id == concept.id)
            .order_by(SourceSection.source_id, SourceSection.source_version, SourceSection.position)
        )
    )
    out = ConceptOut.model_validate(concept)
    out.source_section_ids = section_ids
    return out.model_dump(mode="json")


@router.post("/courses/{course_id}/concepts", status_code=201, response_model=ConceptOut)
def create_concept(
    course_id: uuid.UUID, payload: ConceptIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    if replay := replay_if_seen(db, ctx, payload):
        return replay
    owned(db, Course, course_id, ctx.user.id)
    if payload.syllabus_item_id is not None:
        topic = db.get(SyllabusItem, payload.syllabus_item_id)
        if topic is None or topic.user_id != ctx.user.id or topic.course_id != course_id:
            raise not_found("Topic")
    sections = sections_in_course(db, ctx.user.id, course_id, payload.source_section_ids)
    concept = Concept(user_id=ctx.user.id, course_id=course_id, **payload.model_dump(exclude={"source_section_ids"}))
    db.add(concept)
    db.flush()
    for section in sections:
        db.add(ConceptSource(concept_id=concept.id, section_id=section.id))
    db.flush()
    db.refresh(concept)
    return commit_with_response(db, ctx, payload, 201, concept_view(db, concept))


class ExplanationPaceIn(BaseModel):
    pace: ExplanationPace | None = Field(default=None, description="null = follow the learner's default")


@router.put("/courses/{course_id}/explanation-pace")
def set_explanation_pace(
    course_id: uuid.UUID, payload: ExplanationPaceIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """How assistants explain new material in this course (2026-11-26); null = the learner's default.
    Audited."""
    key = {"explanation_pace": str(course_id), **payload.model_dump()}
    if replay := replay_if_seen(db, ctx, key):
        return replay
    course = owned(db, Course, course_id, ctx.user.id)
    explanation_pace.set_for_course(db, ctx.user.id, course, payload.pace, ctx.request_id, origin="web")
    db.flush()
    return commit_with_response(db, ctx, key, 200, explanation_pace.view(ctx.user, course))


class StudiedInIn(BaseModel):
    assistant: AssistantKey | None = Field(default=None, description="null = any assistant")


@router.put("/courses/{course_id}/studied-in", response_model=CourseOut)
def set_studied_in(
    course_id: uuid.UUID, payload: StudiedInIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The assistant the learner usually studies this course in (2026-11-27): Today's button and the tips name it.
    Wording only; every connected assistant still works with every course. Audited."""
    key = {"studied_in": str(course_id), **payload.model_dump()}
    if replay := replay_if_seen(db, ctx, key):
        return replay
    course = owned(db, Course, course_id, ctx.user.id)
    before = course.usually_studied_in
    if payload.assistant != before:
        course.usually_studied_in = payload.assistant
        audit(
            db,
            actor_id=ctx.user.id,
            action="course.studied_in_changed",
            target_type="course",
            target_id=course.id,
            details={"from": before, "to": payload.assistant},
            request_id=ctx.request_id,
        )
    db.flush()
    db.refresh(course)
    return commit_with_response(db, ctx, key, 200, CourseOut.model_validate(course).model_dump(mode="json"))


class PracticeLimitIn(BaseModel):
    level: int | None = Field(
        default=None,
        ge=2,
        le=6,
        description="highest Bloom level to practise; null = automatic (5, or 6 when an exam paper asks for it)",
    )
    keep_despite_exam: bool = Field(
        default=False, description="the learner keeps the limit although an exam profile asks for higher levels"
    )


@router.put("/courses/{course_id}/practice-limit")
def set_practice_limit(
    course_id: uuid.UUID, payload: PracticeLimitIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> JSONResponse:
    """The learner's practice limit (Bloom 2-6, or automatic) for one course; it caps practice, simulations and
    Check first."""
    key = {"practice_limit": str(course_id), **payload.model_dump()}
    if replay := replay_if_seen(db, ctx, key):
        return replay
    course = owned(db, Course, course_id, ctx.user.id)
    level = payload.level  # an explicit 5 stays 5: automatic would become 6 when an exam paper asks for Create
    before = course.bloom_ceiling
    course.bloom_ceiling = level
    if payload.keep_despite_exam:
        course.bloom_ceiling_confirmed_at = clock.now()
    elif level != before:
        course.bloom_ceiling_confirmed_at = None  # a new limit is checked against the exam profile again
    audit(
        db,
        actor_id=ctx.user.id,
        action="course.practice_limit",
        target_type="course",
        target_id=course.id,
        details={"from": before, "to": level, "kept_despite_exam": payload.keep_despite_exam},
        request_id=ctx.request_id,
    )
    db.flush()
    today = clock.now().astimezone(ZoneInfo(ctx.user.timezone)).date()
    return commit_with_response(db, ctx, key, 200, check_first.practice_limit(db, course, today))
