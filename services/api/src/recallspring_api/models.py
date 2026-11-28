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
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
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
    # Set by Change password and `recallspring reset-password` (migration 0038); NULL = unchanged since set-up.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # The learner's own words on how they like to study (e.g. brought over from ChatGPT's custom instructions);
    # Claude reads them as preferences, never as rules that override RecallSpring's.
    study_preferences: Mapped[str | None] = mapped_column(Text)
    # Which assistant the learner studies with (migration 0018): "claude", "codex", "chatgpt", "antigravity" (0021),
    # "mix" (0020) or
    # None = not chosen. With "mix", assistant_mix lists which (two or three). Only the web app's wording and setup
    # steps depend on it; every assistant keeps working.
    assistant: Mapped[str | None] = mapped_column(String(20))
    assistant_mix: Mapped[list[Any]] = _json_list()
    # What Home calls the learner ("Good evening, <name>"; migration 0026, ADR-012); None = no name (the default).
    greeting_name: Mapped[str | None] = mapped_column(String(40))
    # Which kinds of practice suggestion the learner wants (ADR-010), e.g. {"exam_answer": false}; missing = on.
    practice_suggestions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    # How assistants explain new material by default (migration 0035, 2026-11-26): "step", "balanced",
    # "chunks" (larger chunks) or "auto" (the assistant adapts). A course may choose its own (courses.explanation_pace).
    explanation_pace: Mapped[str] = mapped_column(String(16), nullable=False, server_default="auto", default="auto")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        CheckConstraint(
            "assistant IS NULL OR assistant IN ('claude','codex','chatgpt','antigravity','mix')", name="assistant"
        ),
        CheckConstraint("connector_limit_percent BETWEEN 1 AND 100", name="connector_limit_percent"),
        CheckConstraint("maintenance_percent BETWEEN 0 AND 50", name="maintenance_percent"),
        CheckConstraint("style_percent BETWEEN 0 AND 100", name="style_percent"),
        CheckConstraint("interest_percent BETWEEN 0 AND 50", name="interest_percent"),
        CheckConstraint("explanation_pace IN ('step','balanced','chunks','auto')", name="explanation_pace"),
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
    # "Confirm it is you" (password or passkey) for adding and removing passkeys; valid 5 minutes (0038).
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Passkey(Base):
    """A WebAuthn credential (migration 0038, 2026-11-27). Only the public half: the private key never leaves the
    learner's device or password manager. ``rp_id`` is the address it works at (localhost or the remote host)."""

    __tablename__ = "passkeys"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", default=0)
    transports: Mapped[list[Any]] = _json_list()
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    aaguid: Mapped[str | None] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    rp_id: Mapped[str] = mapped_column(String(253), nullable=False)
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    # Practice limit (migrations 0023, 0034): the highest Bloom level (2-6) the learner wants; NULL means automatic:
    # 5, or 6 while an upcoming exam's profile has Bloom 6 questions. Confirmed when the learner kept it although an
    # exam profile of the course asks for higher levels.
    bloom_ceiling: Mapped[int | None] = mapped_column(SmallInteger)
    bloom_ceiling_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Explanation pace for this course (migration 0035); NULL = the learner's default (users.explanation_pace).
    explanation_pace: Mapped[str | None] = mapped_column(String(16))
    # Usually studied in (migration 0037): the assistant Today and the tips name for this course; NULL = any. Wording
    # only: every connected assistant works with every course.
    usually_studied_in: Mapped[str | None] = mapped_column(String(16))
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
        CheckConstraint("bloom_ceiling IS NULL OR bloom_ceiling BETWEEN 2 AND 6", name="bloom_ceiling"),
        CheckConstraint(
            "explanation_pace IS NULL OR explanation_pace IN ('step','balanced','chunks','auto')",
            name="explanation_pace",
        ),
        CheckConstraint(
            "usually_studied_in IS NULL OR usually_studied_in IN ('claude','codex','antigravity','chatgpt')",
            name="usually_studied_in",
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

    # ADR-010: an exam answer has a word limit; the assistant recommends it, the learner may change it per question.
    practice_kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="quiz", default="quiz")
    length_recommended_words: Mapped[int | None] = mapped_column(SmallInteger)
    length_words: Mapped[int | None] = mapped_column(SmallInteger)
    length_set_by: Mapped[str | None] = mapped_column(String(20))
    length_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("bloom_level BETWEEN 1 AND 6", name="bloom_level"),
        CheckConstraint("difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name="difficulty"),
        CheckConstraint("question_type IN ('open','mcq')", name="question_type"),
        CheckConstraint("practice_kind IN ('quiz','exam_answer')", name="practice_kind"),
        CheckConstraint(
            "(length_words IS NULL OR length_words BETWEEN 10 AND 1000) AND "
            "(length_recommended_words IS NULL OR length_recommended_words BETWEEN 10 AND 1000)",
            name="length_words",
        ),
        CheckConstraint(
            "length_set_by IS NULL OR length_set_by IN ('assistant','default','learner')", name="length_set_by"
        ),
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
    # The learner marked a closed answer as a guess (migration 0023): it never counts as known. On an open answer
    # it is "Unsure" (2026-11-26): graded normally, only shown, so the assistant can offer more explanation.
    guessing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    captured_via: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    # Photos of the learner's work (migration 0019): ids of image sources in the course Library, saved first.
    photo_ids: Mapped[list[Any]] = _json_list()
    # ADR-014 §3 (migration 0032): seconds the question was open and visible in a RecallSpring answer form, without
    # pauses over 5 minutes. None for chat answers. Time spent, never learning or mastery.
    answer_seconds: Mapped[int | None] = mapped_column(SmallInteger)
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
        CheckConstraint("answer_seconds IS NULL OR answer_seconds BETWEEN 1 AND 7200", name="answer_seconds"),
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
    # ADR-010: how an exam answer used its space (coverage, repetition, words); never part of the grade.
    answer_technique: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("evaluator_kind IN ('ai','human','deterministic','self')", name="evaluator_kind"),
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


class ReviewShadow(Base):
    """FSRS-6 computed in shadow (ADR-014 §5, migration 0033): derived, rebuilt by every replay of a concept's review
    state and never edited. One row per variant and review (a concept's first certain answer of a local day, or a
    Check first result). Never shown in the web app or the connector and never used for dates; read only by
    ``recallspring shadow-report``. R is a model estimate, not a measure of mastery."""

    __tablename__ = "review_shadow"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(20), nullable=False)  # rs-fsrs6-v1 | rs-fsrs6-v1a
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # the concept's review number, from 1
    source: Mapped[str] = mapped_column(String(12), nullable=False)  # answer | check_first
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attempts.id"), index=True)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)  # None for Check first
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1 Again, 2 Hard, 3 Good, 4 Easy
    bloom_level: Mapped[int | None] = mapped_column(SmallInteger)
    evaluator_kind: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[str | None] = mapped_column(String(10))
    elapsed_days: Mapped[int | None] = mapped_column(Integer)  # None for the first review
    r_before: Mapped[float | None] = mapped_column(Float)
    s_before: Mapped[float | None] = mapped_column(Float)
    d_before: Mapped[float | None] = mapped_column(Float)
    s_after: Mapped[float] = mapped_column(Float, nullable=False)
    d_after: Mapped[float] = mapped_column(Float, nullable=False)
    fsrs_due: Mapped[date] = mapped_column(Date, nullable=False)  # FSRS's own date
    capped_due: Mapped[date] = mapped_column(Date, nullable=False)  # with the Check first overlay and the exam cap
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_targets.id"))  # the concept's next exam
    exam_date: Mapped[date | None] = mapped_column(Date)
    exam_target: Mapped[float | None] = mapped_column(Float)  # T
    exam_r: Mapped[float | None] = mapped_column(Float)  # R on the exam morning after this review
    library_version: Mapped[str] = mapped_column(String(20), nullable=False)
    params_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_review_shadow_review", "user_id", "concept_id", "variant", "local_date", unique=True),
        CheckConstraint("variant IN ('rs-fsrs6-v1','rs-fsrs6-v1a')", name="variant"),
        CheckConstraint("source IN ('answer','check_first')", name="source"),
        CheckConstraint("rating BETWEEN 1 AND 4", name="rating"),
        CheckConstraint("grade IS NULL OR grade BETWEEN 0 AND 4", name="grade"),
    )


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
    # origin "web" (ADR-013 §5): the pages the content was read from, [{url, title, read_on}]
    web_links: Mapped[list[Any]] = _json_list()

    __table_args__ = (
        Index("ix_sources_user_sha256", "user_id", "sha256"),
        CheckConstraint(
            "kind IN ('pdf','markdown','text','image','docx','pptx','xlsx',"
            "'odt','odp','ods','csv','subtitles','notebook','code','latex')",
            name="kind",
        ),
        CheckConstraint("origin IN ('upload','paste','import','web')", name="origin"),
        CheckConstraint("category IN ('material','notes','exercises','past_paper','chat','other')", name="category"),
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
    # app_ui: typed in RecallSpring; summary_form: the summary form; assistant_transcription: an assistant copied it
    # from the chat or a photo (ADR-011), shown with a label so the learner checks it
    captured_via: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'app_ui'"))

    __table_args__ = (
        UniqueConstraint("user_id", "client_note_id", name="uq_notes_user_client_note"),
        CheckConstraint("captured_via IN ('app_ui','summary_form','assistant_transcription')", name="captured_via"),
    )


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


# --------------------------------------------------------------------------- Concept-to-Clarity (ADR-010)


class Explanation(Base):
    """The learner's explanation of one concept (Concept-to-Clarity), kept as numbered versions."""

    __tablename__ = "explanations"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (UniqueConstraint("user_id", "concept_id", name="uq_explanations_user_concept"),)


class ExplanationVersion(Base):
    """One version, saved exactly as the learner wrote it before any assistant reads it. Never rewritten."""

    __tablename__ = "explanation_versions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    explanation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("explanations.id"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # learner | discuss | exam_answer
    source_attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attempts.id"))
    word_limit: Mapped[int | None] = mapped_column(SmallInteger)  # the exam answer's limit, when from one
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source IN ('learner','discuss','exam_answer')", name="source"),
        CheckConstraint("(source = 'exam_answer') = (source_attempt_id IS NOT NULL)", name="exam_answer_attempt"),
        UniqueConstraint("explanation_id", "number", name="uq_explanation_versions_number"),
        UniqueConstraint("user_id", "client_request_id", name="uq_explanation_versions_user_client_request"),
    )


class ExplanationFeedback(Base):
    """An assistant's feedback on one version: what is correct, missing and wrong, with cited sections. No grade."""

    __tablename__ = "explanation_feedback"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("explanation_versions.id"), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    model_reported_by: Mapped[str | None] = mapped_column(String(40))
    correct: Mapped[list[Any]] = _json_list()
    missing: Mapped[list[Any]] = _json_list()
    wrong: Mapped[list[Any]] = _json_list()
    evidence_refs: Mapped[list[Any]] = _json_list()
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()


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


class Export(Base):
    """One learner's export of their own material, notes and answers as plain files (migration 0039, 2026-11-27).
    Built by the worker into a ZIP under storage_dir/exports/<user id>/ and deleted after ``expires_at``."""

    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued", default="queued")
    # {"course_ids": [...] | null, "material": bool, "notes": bool, "answers": bool}
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    destination: Mapped[str] = mapped_column(String(20), nullable=False, server_default="download", default="download")
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("state IN ('queued','running','ready','failed','cancelled','expired')", name="state"),
        CheckConstraint("destination IN ('download','drive')", name="destination"),
    )


class DriveConnection(Base):
    """A learner's own cloud folder (BYOS step 2, migration 0040, 2026-11-27; Dropbox migration 0041, 2026-11-28): a
    readable copy of their material in Google Drive or Dropbox. The refresh token is in secrets_dir
    (drive-<user id>.bin), never here."""

    __tablename__ = "drive_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, server_default="google", default="google")
    root_id: Mapped[str] = mapped_column(String(200), nullable=False)
    mirror: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    exports: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    # Material uploaded from this moment on is copied; NULL = everything (after "Copy what is already here").
    copy_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ok", default="ok")
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_try_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    connected_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("provider IN ('google','dropbox')", name="provider"),
        CheckConstraint("state IN ('ok','copying','failing','revoked')", name="state"),
    )


class DriveItem(Base):
    """What RecallSpring made in the learner's Drive and for what: the root, a course's folder, one of the learner's
    folders, the Exports folder, a copied source or an export (migration 0040). Copying is one way."""

    __tablename__ = "drive_items"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    local_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    local_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    drive_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("user_id", "local_kind", "local_id", name="uq_drive_items_local"),
        CheckConstraint("local_kind IN ('course','source_folder','exports','source','export')", name="local_kind"),
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
    # Which assistant uses this token; labels its grades ("Claude", "Codex"). Migration 0016.
    client: Mapped[str] = mapped_column(String(20), nullable=False, server_default="claude", default="claude")
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("scope IN ('connector')", name="scope"),
        CheckConstraint("client IN ('claude','codex','antigravity')", name="client"),
    )


class ConnectorUsage(Base):
    """Requests per learner-local day, for the owner's daily connector limit (1–100 % of the default)."""

    __tablename__ = "connector_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)


# --------------------------------------------------------------------------- conversations with an AI provider


class AiChatFolder(Base):
    """The learner's folder for Chat conversations (ADR-012 §4): top level or one level of subfolders, never deeper
    (refused by the server). Deleting is a soft delete; its conversations move to the parent or to "No folder"."""

    __tablename__ = "ai_chat_folders"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_chat_folders.id"), index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    icon: Mapped[str] = mapped_column(String(20), nullable=False, server_default="folder", default="folder")
    color: Mapped[str | None] = mapped_column(String(7))
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id"))
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),)


class AiGhostUsage(Base):
    """Token usage of one ghost chat reply (ADR-012 §5): the model and the counts only, never any text."""

    __tablename__ = "ai_ghost_usage"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    model: Mapped[str | None] = mapped_column(String(120))
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = _created()


class AiConversation(Base):
    """A conversation the learner had with an AI provider from RecallSpring (today: ChatGPT in Settings). Kept
    after signing out at the provider; deleting is a soft delete the learner confirms (restorable)."""

    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Study mode (migration 0017): the course this conversation studies; null for a general chat.
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id"))
    # Migration 0027 (ADR-012): the Chat folder it is filed in (null: "No folder"), and a plain chat (no course,
    # never RecallSpring's tools).
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_chat_folders.id"), index=True)
    plain: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("provider IN ('chatgpt')", name="provider"),)


class AiMessage(Base):
    """One turn. The learner's message is saved before the provider is called; a reply records which model and
    version answered, when, how long it took and the token usage the provider reported. A failed request keeps the
    learner's message with the error code (no reply row)."""

    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    model_requested: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    response_id: Mapped[str | None] = mapped_column(String(200))
    account: Mapped[str | None] = mapped_column(String(320))
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(60))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # On a learner's message: the excerpts of their chosen material sent with it ([{ref, section_id, source_id,
    # filename, label, chars}]); replies cite them by ref ("S1").
    context: Mapped[list[Any] | None] = mapped_column(JSONB)
    # On a learner's message (migration 0017): what ChatGPT read or saved in RecallSpring while answering it
    # ([{call_id, name, arguments, status, error_code, summary, ms, form?}]); the tools' outputs are not stored.
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSONB)
    # On a learner's message (migration 0019): images pasted or dropped into the message (image source ids).
    photo_ids: Mapped[list[Any]] = _json_list()
    created_at: Mapped[datetime] = _created()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="role"),
        UniqueConstraint("conversation_id", "position", name="uq_ai_messages_position"),
        UniqueConstraint("user_id", "client_request_id", name="uq_ai_messages_user_client_request"),
    )


class AiConversationSource(Base):
    """A file the learner chose for a conversation: excerpts of it that match each message are sent along."""

    __tablename__ = "ai_conversation_sources"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = _owner()
    added_at: Mapped[datetime] = _created()


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
    # ADR-014 §4 "Before this exam": the learner's target for the exam morning; NULL = the goal's default.
    exam_retention: Mapped[float | None] = mapped_column(Numeric(3, 2, asdecimal=False))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('kolokvij','izpit','other')", name="kind"),
        CheckConstraint("status IN ('upcoming','passed','failed','cancelled')", name="status"),
        CheckConstraint("goal IN ('exam_only','long_term')", name="goal"),
        CheckConstraint("exam_retention IS NULL OR exam_retention BETWEEN 0.85 AND 0.97", name="exam_retention"),
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
    """Exam profile derived from past papers: item types, Bloom mix and topics (AI-derived, labelled).

    Version 1 rows have ``topic_weights`` (label, optional concept, weight). Version 2 (ADR-013) has ``topics`` with
    points or share, the concepts that cover each topic (or ``not_in_material``), where it is on the paper and on
    which papers, the computed share and weight; ``papers``; what could not be read; and the learner's confirmation.
    """

    __tablename__ = "target_profiles"
    __table_args__ = (
        CheckConstraint("version IN (1, 2)", name="version"),
        CheckConstraint("confirmed_via IS NULL OR confirmed_via IN ('assistant','web')", name="confirmed_via"),
    )

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
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1", default=1)
    topics: Mapped[list[Any]] = _json_list()
    papers: Mapped[list[Any]] = _json_list()
    # Past papers of the course left out on the learner's word: source_id and reason (0030).
    skipped_papers: Mapped[list[Any]] = _json_list()
    unreadable: Mapped[list[Any]] = _json_list()
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_via: Mapped[str | None] = mapped_column(String(20))


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
    # Retakes (migration 0036, 2026-11-26): a retake reuses the questions of its first version (the
    # benchmark, ``retake_of``) as version 2, 3, ...; submitted the same local day as an earlier version it is
    # practice only (``same_day_practice``): graded and shown, but out of the review schedule and the Bloom ramp.
    retake_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quizzes.id"), index=True)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1", default=1)
    same_day_practice: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('open','submitted')", name="status"),
        CheckConstraint("mode IN ('practice','diagnostic')", name="mode"),
        CheckConstraint(
            "(retake_of IS NULL AND version = 1) OR (retake_of IS NOT NULL AND version >= 2)", name="retake_version"
        ),
    )


class QuizItem(Base):
    __tablename__ = "quiz_items"

    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), nullable=False)
    points: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1", default=1)


# --------------------------------------------------------------------------- Pomodoro focus time


class FocusSession(Base):
    """A Pomodoro focus block the learner timed in the web app, optionally for one course. Append-only: it records
    time spent, never learning or mastery. ``focused_seconds`` excludes pauses; ``completed`` is false when the
    learner stopped the block early (only blocks of at least a minute are kept). A wrongly timed block can be removed
    after the learner confirms it: a soft delete (``deleted_at``), restorable for 30 days and audited."""

    __tablename__ = "focus_sessions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _owner()
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id"))
    client_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    focused_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("user_id", "client_session_id", name="uq_focus_sessions_user_client_session"),
        Index("ix_focus_sessions_user_ended", "user_id", "ended_at"),
        CheckConstraint("planned_minutes BETWEEN 1 AND 240", name="planned_minutes"),
        CheckConstraint("focused_seconds BETWEEN 60 AND 14400", name="focused_seconds"),
        CheckConstraint("ended_at >= started_at", name="ended_after_start"),
    )
