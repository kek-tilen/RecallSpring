"""Request/response models of the public API (published as OpenAPI at /api/v1/openapi.json)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Grade = int


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


AssistantKey = Literal["claude", "codex", "chatgpt", "antigravity"]
AssistantChoice = Literal["claude", "codex", "chatgpt", "antigravity", "mix"]


class UserOut(_Out):
    id: uuid.UUID
    username: str
    timezone: str
    assistant: AssistantChoice | None = None
    assistant_mix: list[AssistantKey] = []
    greeting_name: str | None = None


class FirstRunIn(BaseModel):
    """The first account on a new install (first-run page; only on this computer, only while no account exists)."""

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=12, max_length=256)
    timezone: str = Field(min_length=1, max_length=64)


class ProfileIn(BaseModel):
    """Only the fields sent change; ``assistant: null`` means "decide later". ``assistant: "mix"`` needs
    ``assistant_mix``: two or three different assistants."""

    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    assistant: AssistantChoice | None = None
    assistant_mix: list[AssistantKey] | None = Field(default=None, max_length=4)
    # What Home calls the learner; null or blank = no name ("Good evening").
    greeting_name: str | None = Field(default=None, max_length=40)


class SessionOut(BaseModel):
    user: UserOut
    expires_at: datetime


# ---------------------------------------------------------------- courses


CourseKind = Literal["course", "interest"]


class CourseIn(BaseModel):
    """``kind`` 'interest' is personal learning without a deadline (planned after university work); its
    ``description`` is the learner's goal."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    long_term_retention: bool = True
    kind: CourseKind = "course"


class CourseOut(_Out):
    id: uuid.UUID
    title: str
    description: str | None
    long_term_retention: bool
    status: str
    kind: CourseKind = "course"
    focus_until: date | None = None
    color: str | None = None
    group_id: uuid.UUID | None = None
    revision: int
    created_at: datetime
    updated_at: datetime


CourseColor = Literal["blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red"]
MaterialCategory = Literal["material", "notes", "exercises", "past_paper", "chat", "other"]


class CoursePatch(BaseModel):
    """Only the fields sent are changed; send ``null`` for ``color`` or ``group_id`` to clear them."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    color: CourseColor | None = None
    group_id: uuid.UUID | None = None
    long_term_retention: bool | None = None
    archived: bool | None = None
    kind: CourseKind | None = None


class FocusIn(BaseModel):
    """Concentrate on one course or interest until ``until`` (inclusive; default today). ``course_id`` null ends
    the focus."""

    course_id: uuid.UUID | None = None
    until: date | None = None


class InterestGoalIn(BaseModel):
    goal: str = Field(min_length=1, max_length=5000)


class OrganiseCoursesIn(BaseModel):
    """Names of the levels to file courses under, e.g. university "UM", faculty "FERI", semester "5. semester"."""

    course_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    semester: str = Field(min_length=1, max_length=200)
    faculty: str | None = Field(default=None, min_length=1, max_length=200)
    university: str | None = Field(default=None, min_length=1, max_length=200)


class GroupIn(BaseModel):
    kind: Literal["university", "faculty", "semester", "other"]
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class GroupPatch(BaseModel):
    """Only the fields sent are changed; send ``null`` for ``parent_id`` to move a group to the top level."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Literal["university", "faculty", "semester", "other"] | None = None
    parent_id: uuid.UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)


class MergeIn(BaseModel):
    into_id: uuid.UUID


class ArchiveIn(BaseModel):
    archived: bool


class SourcePatch(BaseModel):
    category: MaterialCategory


class FolderIn(BaseModel):
    course_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)


class FolderPatch(BaseModel):
    """Rename and/or move; send ``parent_id: null`` to move the folder to the course's top level."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class ChatImportSaveIn(BaseModel):
    """Save conversations of a staged ChatGPT export into a course; ``folder`` (e.g. "Chats from ChatGPT") is
    created below ``folder_id`` when missing."""

    course_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    folder: str | None = Field(default=None, max_length=600)
    keys: list[str] = Field(min_length=1, max_length=200)
    include_files: bool = True


class ChatGptMessageIn(BaseModel):
    """A message to ChatGPT; without ``conversation_id`` a new conversation starts. Earlier turns are kept by
    RecallSpring and sent again in full."""

    conversation_id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=4000)
    # Tell ChatGPT it may add visual explanations as allowlisted JSON (services/visual_blocks.py); the learner
    # can switch this off.
    visuals: bool = True
    # Only for a new conversation: the files whose matching excerpts may be sent (services/chat_material.py).
    source_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    # Images pasted or dropped into this message, saved first in the course Library; sent to ChatGPT to look at.
    photo_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    # "Use RecallSpring": ChatGPT may read and add study records through RecallSpring's tools
    # (services/chat_tools.py) while answering this message.
    recallspring: bool = False
    # Only for a new conversation: study mode for this course (ChatGPT starts from its study context and plan).
    course_id: uuid.UUID | None = None
    # Only for a new conversation: a plain chat (ADR-012 §5), no course and never RecallSpring's tools.
    plain: bool = False


class ChatGptConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatFolderIn(BaseModel):
    """A Chat folder (ADR-012 §4); ``parent_id`` makes it a subfolder of a top-level folder."""

    name: str = Field(min_length=1, max_length=60)
    parent_id: uuid.UUID | None = None
    icon: str = Field(default="folder", max_length=20)
    color: str | None = Field(default=None, max_length=7, description="#rrggbb; null: the default colour")
    course_id: uuid.UUID | None = None
    pinned: bool = False


class ChatFolderPatch(BaseModel):
    """Only the fields sent are changed; ``parent_id``, ``color`` and ``course_id`` may be set to null."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=7)
    course_id: uuid.UUID | None = None
    pinned: bool | None = None


class ChatFolderMoveIn(BaseModel):
    """ "Move to…": a folder, or null for "No folder"."""

    folder_id: uuid.UUID | None


class GhostTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=40_000)
    model: str | None = Field(default=None, max_length=120)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty turn")
        return value


def _ghost_turns(turns: list[GhostTurn]) -> list[GhostTurn]:
    for t in turns:
        if t.role == "user" and len(t.text) > 4000:
            raise ValueError("a message is at most 4000 characters")
    if not any(t.role == "user" for t in turns):
        raise ValueError("a ghost chat starts with the learner's message")
    return turns


class GhostMessageIn(BaseModel):
    """A ghost chat turn (ADR-012 §5): the page holds the whole conversation and sends it with every message; the
    server keeps none of it. The last turn is the learner's new message."""

    model: str = Field(min_length=1, max_length=120)
    turns: list[GhostTurn] = Field(min_length=1, max_length=120)
    course_id: uuid.UUID | None = None
    plain: bool = False
    recallspring: bool = True
    visuals: bool = True

    @field_validator("turns")
    @classmethod
    def _turns(cls, turns: list[GhostTurn]) -> list[GhostTurn]:
        if turns[-1].role != "user":
            raise ValueError("the last turn is the learner's new message")
        return _ghost_turns(turns)


class GhostKeepIn(BaseModel):
    """ "Keep this chat": save the ghost chat the page holds as a normal conversation."""

    turns: list[GhostTurn] = Field(min_length=1, max_length=120)
    course_id: uuid.UUID | None = None
    plain: bool = False

    @field_validator("turns")
    @classmethod
    def _turns(cls, turns: list[GhostTurn]) -> list[GhostTurn]:
        return _ghost_turns(turns)


class ChatGptMaterialIn(BaseModel):
    """The files a conversation may use; an empty list sends no material."""

    source_ids: list[uuid.UUID] = Field(max_length=20)


class PreferencesIn(BaseModel):
    text: str = Field(max_length=8000)


class ProfileSourceIn(BaseModel):
    """Which file of the course the exam-style analysis came from; null unlinks it."""

    source_id: uuid.UUID | None


class SourcesMoveIn(BaseModel):
    """``folder_id`` null files the material at its course's top level."""

    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    folder_id: uuid.UUID | None = None


class SourcesArchiveIn(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    archived: bool


class SyllabusItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    position: int = Field(default=0, ge=0, le=10_000)


class SyllabusItemOut(_Out):
    id: uuid.UUID
    course_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    position: int
    revision: int


class ConceptIn(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    definition_draft: str | None = Field(default=None, max_length=5000)
    syllabus_item_id: uuid.UUID | None = None
    source_confidence: Literal["high", "medium", "low", "inferred"] | None = None
    source_section_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class ConceptOut(_Out):
    id: uuid.UUID
    course_id: uuid.UUID
    syllabus_item_id: uuid.UUID | None
    term: str
    definition_draft: str | None
    source_confidence: str | None
    revision: int
    source_section_ids: list[uuid.UUID] = Field(default_factory=list)


# ---------------------------------------------------------------- study sessions


class StudySessionIn(BaseModel):
    course_id: uuid.UUID | None = None
    mode: Literal["new_learning", "review"]


class StudySessionOut(_Out):
    id: uuid.UUID
    course_id: uuid.UUID | None
    mode: str
    started_at: datetime
    ended_at: datetime | None


# ---------------------------------------------------------------- questions


class QuestionIn(BaseModel):
    course_id: uuid.UUID
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    bloom_level: int = Field(ge=1, le=6)
    prompt: str = Field(min_length=1, max_length=4000)
    expected_points: list[str] = Field(default_factory=list, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    difficulty: int | None = Field(default=None, ge=1, le=5)


class QuestionGenerateIn(BaseModel):
    course_id: uuid.UUID
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    bloom_levels: list[int] = Field(default_factory=lambda: [3, 4, 5], min_length=1, max_length=10)
    order: Literal["progressive", "mixed"] = "progressive"


class QuestionOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    concept_ids: list[uuid.UUID]
    bloom_level: int
    prompt: str
    source_refs: list[str]
    difficulty: int | None
    provenance: dict[str, Any]
    created_at: datetime
    rubric: dict[str, Any] | None = Field(
        default=None, description="Only present once the learner has submitted an attempt for this question."
    )
    latest_attempt_id: uuid.UUID | None = Field(
        default=None, description="The learner's newest answer to this question (Chat shows it under its form)."
    )


class QuestionListOut(BaseModel):
    questions: list[QuestionOut]


# ---------------------------------------------------------------- attempts and assessments


class AttemptIn(BaseModel):
    question_id: uuid.UUID
    session_id: uuid.UUID | None = None
    client_request_id: uuid.UUID
    kind: Literal["answer", "dont_know", "skip"] = "answer"
    answer_text: str = Field(default="", max_length=20_000)
    answer_mode: Literal["closed_notes", "open_notes"] = "closed_notes"
    # Photos of work solved on paper: image sources in the question's course (saved first, e.g. "Answer photos").
    photo_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)


class AttemptCreatedOut(BaseModel):
    attempt_id: uuid.UUID
    status: str
    saved_at: datetime


class AssessmentOut(_Out):
    id: uuid.UUID
    evaluator_kind: str
    provider: str | None
    model: str | None
    model_reported_by: str | None
    simulated: bool
    rubric_version: str
    status: str
    grade: Grade | None
    confidence: str
    feedback: str
    evidence_refs: list[Any]
    strengths: list[Any]
    gaps: list[Any]
    remediation: str | None
    factuality_flags: list[Any]
    supersedes_id: uuid.UUID | None
    created_at: datetime


class AttemptOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    session_id: uuid.UUID | None
    kind: str
    answer_text: str
    answer_mode: str
    captured_via: str
    status: str
    submitted_at: datetime
    last_evaluation_error: str | None
    assessments: list[AssessmentOut]
    effective_assessment_id: uuid.UUID | None
    photos: list[dict[str, Any]] = Field(default_factory=list)  # [{id, filename, available}]


class SelfAssessmentIn(BaseModel):
    """The learner's own check of a saved answer: one state per expected point, in order, and the grade they chose
    (RecallSpring suggests one from the states; 4 needs a reason)."""

    points: list[Literal["met", "partial", "missing"]] = Field(min_length=1, max_length=12)
    grade: int = Field(ge=0, le=4)
    reason: str | None = Field(default=None, max_length=2000)


class ChallengeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    corrected_grade: int | None = Field(default=None, ge=0, le=4)


# ---------------------------------------------------------------- reviews


class ReviewItemOut(BaseModel):
    concept_id: uuid.UUID
    course_id: uuid.UUID
    term: str
    due_at: datetime
    is_due: bool
    step: int
    evidence_count: int
    lapse_count: int
    last_review_at: datetime
    due_reason: dict[str, Any]
    policy_version: str


class ReviewQueueOut(BaseModel):
    items: list[ReviewItemOut]
    generated_at: datetime
    note: str = "Estimated from practice, not a guarantee of recall."


class DeferIn(BaseModel):
    days: int = Field(ge=1, le=30)
    reason: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------- sources


class SourceTextIn(BaseModel):
    """Pasted content (e.g. when a PDF has no extractable text)."""

    course_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)
    format: Literal["markdown", "plain"] = "markdown"
    folder_id: uuid.UUID | None = None


class ConnectorSourceTextIn(SourceTextIn):
    """Claude names a folder by its path ("Lectures / Week 3"); missing folders are created."""

    folder: str | None = Field(default=None, max_length=600)


class WebLinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000, pattern=r"^https?://[^\s]+$")
    title: str | None = Field(default=None, max_length=200)


class WebSourceIn(BaseModel):
    """Content an assistant read on the web for something on an old paper the material does not cover (ADR-013 §5).
    Only after the learner agreed; saved apart from the course material, with the pages it came from."""

    model_config = ConfigDict(extra="forbid")

    course_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=100_000)
    links: list[WebLinkIn] = Field(min_length=1, max_length=10)
    learner_agreed: bool
    folder: str | None = Field(default=None, max_length=600)


class SourceOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    filename: str
    kind: str
    mime_type: str
    byte_size: int
    sha256: str
    origin: str
    category: str = "material"
    folder_id: uuid.UUID | None = None
    folder: str | None = None
    archived: bool = False
    hidden: bool = False
    archived_at: datetime | None = None
    duplicate_of_id: uuid.UUID | None
    duplicate_of_course_id: uuid.UUID | None
    parse_state: Literal["pending", "processing", "ready", "needs_attention", "failed"]
    parse_error: str | None
    parse_message: str | None
    parse_notes: list[str]
    page_count: int | None
    version: int
    section_count: int
    uploaded_at: datetime
    parsed_at: datetime | None
    web_links: list[dict[str, Any]] = Field(default_factory=list)


class SectionOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_version: int
    position: int
    page: int | None
    heading: str | None
    citation_label: str
    text: str
    char_start: int
    char_end: int


class SectionPageOut(BaseModel):
    sections: list[SectionOut]
    total: int
    offset: int
    limit: int


class SearchHitOut(BaseModel):
    section_id: uuid.UUID
    source_id: uuid.UUID
    filename: str
    citation_label: str
    snippet: str
    rank: float


class SearchOut(BaseModel):
    hits: list[SearchHitOut]
    note: str = "Snippets are excerpts of your uploaded material."


# ---------------------------------------------------------------- notes


class NoteIn(BaseModel):
    course_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    client_note_id: uuid.UUID
    title: str = Field(default="Untitled note", min_length=1, max_length=200)
    body: str = Field(default="", max_length=200_000)


class NotePatch(BaseModel):
    base_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=200_000)


class NoteRefOut(BaseModel):
    """A Library file the note links with ``[name](source:<id>)``; ``missing`` when it is deleted or not found."""

    id: uuid.UUID
    filename: str | None
    kind: str | None
    course_id: uuid.UUID | None
    missing: bool


class NoteOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    topic_id: uuid.UUID | None
    client_note_id: uuid.UUID
    title: str
    body: str
    revision: int
    saved_at: datetime
    created_at: datetime
    references: list[NoteRefOut] = []
    deleted_at: datetime | None = None
    captured_via: Literal["app_ui", "summary_form", "assistant_transcription"] = "app_ui"


class NoteRevisionOut(BaseModel):
    id: uuid.UUID
    kind: Literal["autosave", "conflict"]
    revision: int
    base_revision: int | None
    title: str
    body: str
    saved_at: datetime


# ---------------------------------------------------------------- planner


class PlanSectionRef(BaseModel):
    section_id: uuid.UUID
    citation_label: str
    filename: str


class PlanItemOut(BaseModel):
    category: Literal["Review due", "Relearn", "Strengthen", "Learn next", "Practice", "Maintain"]
    concept_id: uuid.UUID
    term: str
    course_id: uuid.UUID
    course_title: str
    why_selected: str
    estimated_minutes: int
    target: str | None = None
    course_kind: CourseKind = "course"
    focus: bool = False
    band: Literal["not_started", "emerging", "developing", "reliable"]
    study_status: Literal["not_studied", "studied", "known"]
    difficulty: int
    difficulty_source: str
    sections: list[PlanSectionRef] = Field(default_factory=list)
    # How deep a review goes (ADR-014): quick (one short question), standard, relearn (feedback and another try).
    depth: Literal["quick", "standard", "relearn"] | None = None


class PlanLeftOutOut(BaseModel):
    concept_id: uuid.UUID
    term: str
    course_id: uuid.UUID
    target: str | None = None
    category: str


class TargetCapacityOut(BaseModel):
    course_id: uuid.UUID
    course_title: str
    target_id: uuid.UUID
    target: str
    due_date: str
    days_left: int
    concepts_in_scope: int
    bands: dict[str, int]
    remaining_minutes: int
    available_minutes: int
    status: Literal["ok", "tight", "at_risk"]
    message: str


class InterestPlanOut(BaseModel):
    policy: Literal["university_first", "share"]
    percent: int
    reserved_minutes: int
    planned_minutes: int
    message: str


class FocusOut(BaseModel):
    course_id: uuid.UUID
    course_title: str
    kind: CourseKind
    until: str
    message: str


class PlanOut(BaseModel):
    policy_version: str
    generated_at: datetime
    available_minutes: int
    planned_minutes: int
    maintenance_percent: int
    items: list[PlanItemOut]
    targets: list[TargetCapacityOut]
    message: str | None
    note: str
    interests: InterestPlanOut | None = None
    focus: FocusOut | None = None
    left_out: list[PlanLeftOutOut] = Field(default_factory=list)


# ---------------------------------------------------------------- connector settings (owner session)


class ConnectorTokenIn(BaseModel):
    client: Literal["claude", "codex", "antigravity"] = "claude"
    # default: "Claude Desktop" / "Codex" / "Antigravity"
    label: str | None = Field(default=None, min_length=1, max_length=100)


class ConnectorTokenOut(BaseModel):
    id: uuid.UUID
    label: str
    client: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ConnectorTokenCreatedOut(ConnectorTokenOut):
    token: str | None = Field(description="Shown once. Replays of the same request return null.")


class ConnectorSettingsIn(BaseModel):
    limit_percent: int = Field(ge=1, le=100)


class ConnectorSettingsOut(BaseModel):
    limit_percent: int
    daily_default: int
    daily_limit: int
    used_today: int
    tokens: list[ConnectorTokenOut]


# ---------------------------------------------------------------- connector (Mode A) requests


class ConnectorQuestionItem(BaseModel):
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    bloom_level: int = Field(ge=1, le=6)
    prompt: str = Field(min_length=1, max_length=4000)
    # Required (2026-11-22): the learner checks their answer against them when no assistant is available.
    expected_points: list[str] = Field(min_length=1, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    difficulty: int | None = Field(default=None, ge=1, le=5)


class ConnectorQuestionsIn(BaseModel):
    course_id: uuid.UUID
    questions: list[ConnectorQuestionItem] = Field(min_length=1, max_length=10)
    model_name: str | None = Field(default=None, max_length=120)


class ConnectorAttemptIn(AttemptIn):
    captured_via: Literal["answer_form", "assistant_transcription"]


class ConnectorAssessmentIn(BaseModel):
    status: Literal["final", "provisional", "ungraded"]
    grade: int | None = Field(default=None, ge=0, le=4)
    confidence: Literal["low", "medium", "high"]
    feedback: str = Field(min_length=1, max_length=3000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    remediation: str | None = Field(default=None, max_length=700)
    rubric_scores: dict[str, int] | None = None
    rubric_version: str = Field(default="claude-connector-v1", min_length=1, max_length=60)
    model_name: str | None = Field(default=None, max_length=120)


class ConnectorSessionIn(BaseModel):
    course_id: uuid.UUID | None = None
    mode: Literal["new_learning", "review"] = "review"


class ConnectorSummaryIn(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)


class ConnectorConceptItem(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    definition_draft: str | None = Field(default=None, max_length=5000)
    source_section_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    topic_id: uuid.UUID | None = None


class ConnectorConceptsIn(BaseModel):
    concepts: list[ConnectorConceptItem] = Field(min_length=1, max_length=30)


# ---------------------------------------------------------------- study targets, profiles, availability


class TargetScopeItem(BaseModel):
    kind: Literal["source", "pages", "topic", "concept"]
    source_id: uuid.UUID | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None


# ADR-014 §4: how the reviews go in the days before the exam, per target (stored as exam_retention).
BeforeExamChoice = Literal["default", "regular", "extra_review", "intense"]
BEFORE_EXAM_HELP = (
    "Before this exam, the learner's choice: regular = regular reviews only; extra_review = an extra review "
    "before the exam when the last one would be long before it; intense = reviews closer together before the "
    "exam (needs noticeably more reviews); default = the goal's default (extra_review for exam_only, regular for "
    "long_term). Change it only on the learner's clear request."
)


class TargetIn(BaseModel):
    course_id: uuid.UUID
    kind: Literal["kolokvij", "izpit", "other"]
    name: str = Field(min_length=1, max_length=120)
    due_date: date
    scope_description: str = Field(min_length=1, max_length=2000, description="The learner's own words")
    scope: list[TargetScopeItem] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    goal: Literal["exam_only", "long_term"] = "long_term"
    before_exam: BeforeExamChoice = Field(default="default", description=BEFORE_EXAM_HELP)


class TargetUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["kolokvij", "izpit", "other"] | None = None
    goal: Literal["exam_only", "long_term"] | None = None
    before_exam: BeforeExamChoice | None = Field(default=None, description=BEFORE_EXAM_HELP)
    due_date: date | None = None
    status: Literal["upcoming", "passed", "failed", "cancelled"] | None = None
    result: str | None = Field(default=None, max_length=120)
    scope_description: str | None = Field(default=None, min_length=1, max_length=2000)
    scope: list[TargetScopeItem] | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)


class ItemType(BaseModel):
    type: str = Field(min_length=1, max_length=60)
    share: float = Field(ge=0, le=1)


class FileEvidenceIn(BaseModel):
    """Why one file belongs to its paper (owner 2026-11-25: five photos were put on one kolokvij without a reason)."""

    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    # What on the file shows it, e.g. "header: 2. kolokvij, 16. 01. 2026" or "numbering goes on from 26".
    why: str = Field(min_length=1, max_length=300)
    # strong: the file itself shows it (header, date); weak: only inferred (numbering, layout); ask the learner.
    strength: Literal["strong", "weak"]


class ProfilePaperIn(BaseModel):
    """One old paper the analysis read (ADR-013 §1)."""

    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID | None = None
    label: str | None = Field(default=None, min_length=1, max_length=60)
    total_points: float | None = Field(default=None, gt=0, le=1000)
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    # Which exam the paper was for, e.g. "2. kolokvij 2026" (it may be another exam than the one prepared for), and
    # how it is used: "style" = only the kind of questions (types, Bloom mix, length), its topics do not weigh;
    # "style_and_topics" = its topics weigh too. ADR-013 §1, added 2026-11-25.
    exam: str | None = Field(default=None, min_length=1, max_length=80)
    use: Literal["style", "style_and_topics"] = "style_and_topics"
    # Further files of the same paper, e.g. a second photo or page (owner 2026-11-25).
    extra_source_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    # For every file of the paper: what shows that it belongs to this paper and exam.
    evidence: list[FileEvidenceIn] = Field(default_factory=list, max_length=21)


class SkippedPaperIn(BaseModel):
    """A past paper of the course the analysis leaves out, with the learner's reason (owner 2026-11-25)."""

    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=200)


class ProfileTopicIn(BaseModel):
    """A topic on the paper. It names the course concepts that cover it, or says it is not in the material."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    concept_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    not_in_material: bool = False
    points: float | None = Field(default=None, gt=0, le=1000)
    share: float | None = Field(default=None, gt=0, le=1)
    where: str | None = Field(default=None, min_length=1, max_length=200)
    papers: list[str] = Field(default_factory=list, max_length=10)


class TargetProfileIn(BaseModel):
    """Exam profile v2 (ADR-013). The v1 field ``topic_weights`` is refused: every topic must be mapped."""

    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID | None = None
    papers: list[ProfilePaperIn] = Field(default_factory=list, max_length=10)
    # Past papers of the course left out on the learner's word; every other past paper must be in papers.
    skipped_papers: list[SkippedPaperIn] = Field(default_factory=list, max_length=40)
    item_types: list[ItemType] = Field(default_factory=list, max_length=12)
    bloom_mix: dict[str, float] = Field(default_factory=dict)
    topics: list[ProfileTopicIn] = Field(default_factory=list, max_length=60)
    example_items: list[str] = Field(default_factory=list, max_length=10)
    unreadable: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)
    model_name: str | None = Field(default=None, max_length=120)

    @field_validator("unreadable", "example_items")
    @classmethod
    def _short_lines(cls, value: list[str]) -> list[str]:
        if any(len(v) > 500 for v in value):
            raise ValueError("each line may have at most 500 characters")
        return value


class ProfileConfirmIn(BaseModel):
    """The learner confirmed this analysis (the latest one) matches the paper."""

    profile_id: uuid.UUID


class DifficultyItem(BaseModel):
    concept_id: uuid.UUID
    difficulty: int = Field(ge=1, le=5)


class DifficultyIn(BaseModel):
    rated_by: Literal["claude", "learner"]
    items: list[DifficultyItem] = Field(min_length=1, max_length=60)


class AvailabilityIn(BaseModel):
    weekly_minutes: list[int] | None = Field(default=None, min_length=7, max_length=7)
    day: date | None = None
    minutes: int | None = Field(default=None, ge=0, le=720)
    note: str | None = Field(default=None, max_length=200)
    interest_percent: int | None = Field(default=None, ge=0, le=50)


class StudySettingsIn(BaseModel):
    weekly_minutes: list[int] | None = Field(default=None, min_length=7, max_length=7)
    maintenance_percent: int | None = Field(default=None, ge=0, le=50)
    style_percent: int | None = Field(default=None, ge=0, le=100)
    interest_percent: int | None = Field(default=None, ge=0, le=50)


# ---------------------------------------------------------------- exam simulations (quizzes)


class QuizOption(BaseModel):
    key: str = Field(pattern=r"^[A-H]$")
    text: str = Field(min_length=1, max_length=500)


class QuizItemIn(BaseModel):
    type: Literal["mcq", "open"]
    prompt: str = Field(min_length=1, max_length=4000)
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    bloom_level: int = Field(default=3, ge=1, le=6)
    points: int = Field(default=1, ge=1, le=20)
    options: list[QuizOption] = Field(default_factory=list, max_length=8)
    correct_option: str | None = Field(default=None, pattern=r"^[A-H]$")
    expected_points: list[str] = Field(default_factory=list, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    style: Literal["past_paper", "deeper"] = "past_paper"


class QuizIn(BaseModel):
    course_id: uuid.UUID
    target_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=300)
    items: list[QuizItemIn] = Field(min_length=1, max_length=30)
    model_name: str | None = Field(default=None, max_length=120)
    mode: Literal["practice", "diagnostic"] = Field(
        default="practice",
        description="practice needs studied concepts; diagnostic is a pre-test that does not affect reviews",
    )


class QuizAnswer(BaseModel):
    question_id: uuid.UUID
    option: str | None = Field(default=None, pattern=r"^[A-H]$")
    text: str | None = Field(default=None, max_length=20_000)
    dont_know: bool = False
    guessing: bool = Field(default=False, description="the learner marked a closed answer as a guess")


class QuizDraftIn(BaseModel):
    answers: list[QuizAnswer] = Field(default_factory=list, max_length=30)


class QuizSubmitIn(BaseModel):
    client_request_id: uuid.UUID
    answers: list[QuizAnswer] = Field(default_factory=list, max_length=30)


class AssessmentBatchItem(ConnectorAssessmentIn):
    attempt_id: uuid.UUID


class AssessmentBatchIn(BaseModel):
    items: list[AssessmentBatchItem] = Field(min_length=1, max_length=30)


# ---------------------------------------------------------------- learning first


class LearningSummaryIn(BaseModel):
    course_id: uuid.UUID
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(default="", max_length=200_000, description="The learner's own summary, exactly as typed")
    client_request_id: uuid.UUID


class ChatNoteIn(BaseModel):
    """A note or summary from an assistant chat, saved only after the learner confirmed it (ADR-011)."""

    course_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(
        min_length=1,
        max_length=200_000,
        description="Exactly as the learner wrote it in the chat, or a word-for-word transcription of their photo "
        "(unreadable words as [?]), with the learner's corrections",
    )
    concept_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=20,
        description="Only for the summary of a learning chunk: these become studied",
    )
    transcribed_from_photo: bool = False
    client_request_id: uuid.UUID


class ExplanationVersionIn(BaseModel):
    """A new Concept-to-Clarity version (ADR-010): the learner's own text, saved exactly. With ``from_attempt_id`` the
    exact text of that exam answer is used instead (``text`` is ignored)."""

    text: str = Field(default="", max_length=20_000, description="The learner's own explanation, exactly as typed")
    source: Literal["learner", "discuss"] = "learner"
    from_attempt_id: uuid.UUID | None = None
    client_request_id: uuid.UUID


class ExplanationFeedbackIn(BaseModel):
    """An assistant's feedback on one C2C version: never a grade, never a rewrite of the learner's text."""

    correct: list[str] = Field(default_factory=list, max_length=10, description="What the explanation gets right")
    missing: list[str] = Field(default_factory=list, max_length=10, description="Important points it leaves out")
    wrong: list[str] = Field(default_factory=list, max_length=10, description="What it gets wrong")
    evidence_refs: list[str] = Field(default_factory=list, max_length=20, description="Section IDs you read")
    feedback: str = Field(min_length=1, max_length=3000, description="Short feedback in the learner's language")
    model_name: str | None = Field(default=None, max_length=120)

    @field_validator("correct", "missing", "wrong")
    @classmethod
    def _short_items(cls, items: list[str]) -> list[str]:
        cleaned = [i.strip() for i in items if i.strip()]
        if any(len(i) > 500 for i in cleaned):
            raise ValueError("each point can be up to 500 characters")
        return cleaned


class KnownConceptsIn(BaseModel):
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=500, description="What the learner said, e.g. covered in lectures")


# ---------------------------------------------------------------- Pomodoro focus time


class FocusSessionPatch(BaseModel):
    """The course a focus block counted for, set afterwards (null = no course)."""

    course_id: uuid.UUID | None


class FocusSessionIn(BaseModel):
    client_session_id: uuid.UUID
    course_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime
    planned_minutes: int = Field(ge=1, le=240)
    focused_seconds: int = Field(ge=60, le=14_400, description="Time in focus, pauses excluded")
    completed: bool = Field(description="False when the learner stopped the block early")
