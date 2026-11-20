from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Ctx, WriteCtx, commit_with_response, current_ctx, replay_if_seen, write_ctx
from ..errors import not_found
from ..models import Concept, ConceptSource, Course, SourceSection, SyllabusItem
from ..schemas import ConceptIn, ConceptOut, CourseIn, CourseOut, SyllabusItemIn, SyllabusItemOut
from ..services.courses import ensure_new_title
from ..services.events import learning_event
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
