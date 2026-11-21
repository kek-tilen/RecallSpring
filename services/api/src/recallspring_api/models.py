"""Relational model (logical contract: docs/03-DATA-CONTRACT.md).

Learning evidence (attempts, assessments, learning events, deferrals) is append-only. Mutable records carry
``revision``, ``updated_at`` and ``deleted_at``. Every row is owned by a user and every query filters by owner.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _owner() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)


# --------------------------------------------------------------------------- identity


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/Ljubljana")
    connector_limit_percent: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="100", default=100
    )
    # Study time per weekday, Monday first (owner decision 2026-11-19: 60 min weekdays, 90 min weekends).
    weekly_minutes: Mapped[list[int]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[60,60,60,60,60,90,90]'::jsonb"),
        default=lambda: [60, 60, 60, 60, 60, 90, 90],
    )
    maintenance_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="15", default=15)
    style_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="75", default=75)
    # Share of each day kept for personal interests. 0 = university first: interests only get the time left after
    # today's course work, and only while every exam is on track.
    interest_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        CheckConstraint("connector_limit_percent BETWEEN 1 AND 100", name="connector_limit_percent"),
        CheckConstraint("maintenance_percent BETWEEN 0 AND 50", name="maintenance_percent"),
        CheckConstraint("style_percent BETWEEN 0 AND 100", name="style_percent"),
        CheckConstraint("interest_percent BETWEEN 0 AND 50", name="interest_percent"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- courses


# Course colours are identity markers from a fixed, validated palette (apps/web/src/styles.css); never free CSS.
COURSE_COLORS = ("blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red")
MATERIAL_CATEGORIES = ("material", "notes", "exercises", "past_paper", "other")


class CourseGroup(Base):
    """Organisation tree above courses: university → faculty → semester (any level may be skipped).

    Archiving a semester archives its courses; nothing is deleted and archiving can be undone."""

    __tablename__ = "course_groups"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("course_groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", default="active")
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('university','faculty','semester','other')", name="kind"),
        CheckConstraint("status IN ('active','archived')", name="status"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )


class Course(Base):
    """A university course (``kind`` 'course', planned by its exams) or a personal interest ('interest': learning
    without a deadline, e.g. data analysis in free time, planned after university work)."""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="course", default="course")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    long_term_retention: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("course_groups.id"), index=True)
    color: Mapped[str | None] = mapped_column(String(20))
    # The learner chose to concentrate on this course or interest until this day (inclusive); at most one at a time.
    focus_until: Mapped[date | None] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('course','interest')", name="kind"),
        CheckConstraint("status IN ('active','completed','archived')", name="status"),
        CheckConstraint(
            "color IS NULL OR color IN ('blue','orange','aqua','yellow','magenta','green','violet','red')", name="color"
        ),
    )


class SyllabusItem(Base):
    """A course topic/objective. API and notes call this a *topic*."""

    __tablename__ = "syllabus_items"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("syllabus_items.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_syllabus_items_course_parent", "course_id", "parent_id"),)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    syllabus_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("syllabus_items.id"))
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    definition_draft: Mapped[str | None] = mapped_column(Text)
    source_confidence: Mapped[str | None] = mapped_column(String(20))
    difficulty_estimate: Mapped[int | None] = mapped_column(SmallInteger)
    difficulty_source: Mapped[str | None] = mapped_column(String(20))
    # Learning-first (ADR-006): practice and simulations need the concept to be studied or known first.
    study_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="not_studied", default="not_studied"
    )
    study_source: Mapped[str | None] = mapped_column(String(20))
    studied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "source_confidence IS NULL OR source_confidence IN ('high','medium','low','inferred')",
            name="source_confidence",
        ),
        CheckConstraint(
            "difficulty_estimate IS NULL OR difficulty_estimate BETWEEN 1 AND 5", name="difficulty_estimate"
        ),
        CheckConstraint(
            "difficulty_source IS NULL OR difficulty_source IN ('claude','learner')", name="difficulty_source"
        ),
        CheckConstraint("study_status IN ('not_studied','studied','known')", name="study_status"),
        CheckConstraint(
            "study_source IS NULL OR study_source IN ('session','self_report','diagnostic')", name="study_source"
        ),
    )


# --------------------------------------------------------------------------- study


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id"))
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, server_default="app", default="app")
    started_at: Mapped[datetime] = _created()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("mode IN ('new_learning','review')", name="mode"),
        CheckConstraint("origin IN ('app','connector')", name="origin"),
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    bloom_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    source_refs: Mapped[list[Any]] = _json_list()
    question_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open", default="open")
    options: Mapped[list[Any] | None] = mapped_column(JSONB)  # [{"key": "A", "text": "..."}] for mcq
    difficulty: Mapped[int | None] = mapped_column(SmallInteger)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("bloom_level BETWEEN 1 AND 6", name="bloom_level"),
        CheckConstraint("difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name="difficulty"),
        CheckConstraint("question_type IN ('open','mcq')", name="question_type"),
    )


class QuestionConcept(Base):
    __tablename__ = "question_concepts"

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), primary_key=True, index=True)


class Attempt(Base):
    """The learner's exact answer. Committed before any model call (FR-09)."""

    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_sessions.id"))
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quizzes.id"), index=True)
    selected_option: Mapped[str | None] = mapped_column(String(10))
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    captured_via: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_evaluation_error: Mapped[str | None] = mapped_column(String(80))
    submitted_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id", name="uq_attempts_user_client_request"),
        Index("ix_attempts_user_created", "user_id", "submitted_at"),
        CheckConstraint("kind IN ('answer','dont_know','skip')", name="kind"),
        CheckConstraint("answer_mode IN ('closed_notes','open_notes')", name="answer_mode"),
        CheckConstraint("captured_via IN ('app_ui','answer_form','assistant_transcription')", name="captured_via"),
        CheckConstraint(
            "status IN ('saved_awaiting_evaluation','evaluating','evaluated','not_applicable')", name="status"
        ),
    )


class Assessment(Base):
    """One evaluation of an attempt. Never updated; corrections append a new human assessment."""

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id"), nullable=False, index=True)
    evaluator_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    model_reported_by: Mapped[str | None] = mapped_column(String(40))
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    rubric_version: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[Any]] = _json_list()
    strengths: Mapped[list[Any]] = _json_list()
    gaps: Mapped[list[Any]] = _json_list()
    remediation: Mapped[str | None] = mapped_column(Text)
    rubric_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    factuality_flags: Mapped[list[Any]] = _json_list()
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assessments.id"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("evaluator_kind IN ('ai','human','deterministic')", name="evaluator_kind"),
        CheckConstraint("status IN ('final','provisional','ungraded')", name="status"),
        CheckConstraint("confidence IN ('low','medium','high')", name="confidence"),
        CheckConstraint("grade IS NULL OR grade BETWEEN 0 AND 4", name="grade_range"),
        CheckConstraint("(status = 'ungraded') = (grade IS NULL)", name="grade_status"),
    )


# --------------------------------------------------------------------------- scheduling


class ReviewState(Base):
    """Derived cache: always recomputable by replaying evidence and deferrals (scheduler.replay)."""

    __tablename__ = "review_state"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), primary_key=True)
    step: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consecutive_successes: Mapped[int] = mapped_column(Integer, nullable=False)
    lapse_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    due_reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recomputed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_review_state_user_due", "user_id", "due_at"),)


class ReviewDeferral(Base):
    __tablename__ = "review_deferrals"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), nullable=False, index=True)
    deferred_at: Mapped[datetime] = _created()
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))


# --------------------------------------------------------------------------- audit and idempotency


class LearningEvent(Base):
    __tablename__ = "learning_events"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_learning_events_entity", "entity_type", "entity_id"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = _created()


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)


# --------------------------------------------------------------------------- sources


class SourceFolder(Base):
    """The learner's own folder inside a course (nestable). Optional: material without a folder sits at the
    course's top level. Archiving hides the folder and everything in it from the library; nothing is deleted."""

    __tablename__ = "source_folders"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_folders.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),)


class Source(Base):
    """An uploaded or pasted document. The original bytes are kept unchanged in private storage."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, server_default="material", default="material")
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_folders.id"), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    parse_state: Mapped[str] = mapped_column(String(20), nullable=False)
    parse_error: Mapped[str | None] = mapped_column(String(60))
    parse_notes: Mapped[list[Any]] = _json_list()
    parser_version: Mapped[str | None] = mapped_column(String(60))
    page_count: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    uploaded_at: Mapped[datetime] = _created()
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_sources_user_sha256", "user_id", "sha256"),
        CheckConstraint(
            "kind IN ('pdf','markdown','text','image','docx','pptx','xlsx',"
            "'odt','odp','ods','csv','subtitles','notebook','code','latex')",
            name="kind",
        ),
        CheckConstraint("origin IN ('upload','paste')", name="origin"),
        CheckConstraint("category IN ('material','notes','exercises','past_paper','other')", name="category"),
        CheckConstraint(
            "parse_state IN ('pending','processing','ready','needs_attention','failed')", name="parse_state"
        ),
    )


class SourceSection(Base):
    """A citable unit of extracted text (a PDF page or a Markdown/plain-text section)."""

    __tablename__ = "source_sections"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(300))
    citation_label: Mapped[str] = mapped_column(String(160), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(60), nullable=False)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('simple'::regconfig, text)", persisted=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("source_id", "source_version", "position", name="uq_source_sections_position"),
        Index("ix_source_sections_tsv", "tsv", postgresql_using="gin"),
    )


class ConceptSource(Base):
    """Evidence link from a concept to a source section; ``inferred`` marks links without a direct quote."""

    __tablename__ = "concept_sources"

    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_sections.id"), primary_key=True, index=True)
    excerpt: Mapped[str | None] = mapped_column(String(1000))
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- notes


class Note(Base):
    """Learner-owned text. Never rewritten by the tutor; every acknowledged save bumps ``revision``."""

    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    syllabus_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("syllabus_items.id"))
    client_note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "client_note_id", name="uq_notes_user_client_note"),)


class NoteRevision(Base):
    """History snapshots (``autosave`` coalesced per editing burst) and preserved conflicting drafts."""

    __tablename__ = "note_revisions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    note_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notes.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("kind IN ('autosave','conflict')", name="kind"),)


# --------------------------------------------------------------------------- jobs


class Job(Base):
    """Deterministic background work (no model calls). Claimed with SELECT … FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        Index("ix_jobs_claim", "state", "run_after"),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="state"),
    )


# --------------------------------------------------------------------------- Claude connector (Mode A)


class ConnectorToken(Base):
    """Bearer token for the local Claude connector. Only accepted on /api/v1/connector/* (read + append)."""

    __tablename__ = "connector_tokens"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="connector", default="connector")
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("scope IN ('connector')", name="scope"),)


class ConnectorUsage(Base):
    """Requests per learner-local day, for the owner's daily connector limit (1–100 % of the default)."""

    __tablename__ = "connector_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)


# --------------------------------------------------------------------------- study targets (exams) and planning


class StudyTarget(Base):
    """What the learner prepares for: a kolokvij, an exam or another assessment, with its exact scope."""

    __tablename__ = "study_targets"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="upcoming", default="upcoming")
    result: Mapped[str | None] = mapped_column(String(120))
    scope_description: Mapped[str] = mapped_column(Text, nullable=False)  # the learner's own words, verbatim
    notes: Mapped[str | None] = mapped_column(Text)  # specifics: allowed aids, question types, emphasis …
    goal: Mapped[str] = mapped_column(String(20), nullable=False, server_default="long_term", default="long_term")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('kolokvij','izpit','other')", name="kind"),
        CheckConstraint("status IN ('upcoming','passed','failed','cancelled')", name="status"),
        CheckConstraint("goal IN ('exam_only','long_term')", name="goal"),
    )


class StudyTargetScope(Base):
    """Resolved scope of a target. No rows means the whole course."""

    __tablename__ = "study_target_scope"

    id: Mapped[uuid.UUID] = _pk()
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("study_targets.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    syllabus_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("syllabus_items.id"))
    concept_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("concepts.id"))

    __table_args__ = (CheckConstraint("kind IN ('source','pages','topic','concept')", name="kind"),)


class TargetProfile(Base):
    """Exam profile derived from past papers: item types, Bloom mix and topic weights (AI-derived, labelled)."""

    __tablename__ = "target_profiles"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("study_targets.id"), nullable=False, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    item_types: Mapped[list[Any]] = _json_list()
    bloom_mix: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    topic_weights: Mapped[list[Any]] = _json_list()
    example_items: Mapped[list[Any]] = _json_list()
    notes: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()


class AvailabilityOverride(Base):
    __tablename__ = "availability_overrides"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (CheckConstraint("minutes BETWEEN 0 AND 720", name="minutes"),)


# --------------------------------------------------------------------------- exam simulations (quizzes)


class Quiz(Base):
    """A kolokvij simulation: several questions answered in one form and submitted together."""

    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_targets.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_sessions.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    time_limit_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open", default="open")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="practice", default="practice")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    draft_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("status IN ('open','submitted')", name="status"),
        CheckConstraint("mode IN ('practice','diagnostic')", name="mode"),
    )


class QuizItem(Base):
    __tablename__ = "quiz_items"

    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), nullable=False)
    points: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1", default=1)
