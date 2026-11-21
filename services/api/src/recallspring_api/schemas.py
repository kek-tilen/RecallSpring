"""Request/response models of the public API (published as OpenAPI at /api/v1/openapi.json)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Grade = int


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class UserOut(_Out):
    id: uuid.UUID
    username: str
    timezone: str


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


class ChatGptConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatGptMaterialIn(BaseModel):
    """The files a conversation may use; an empty list sends no material."""

    source_ids: list[uuid.UUID] = Field(max_length=20)


class PreferencesIn(BaseModel):
    text: str = Field(max_length=8000)


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
    category: Literal["Review due", "Strengthen", "Learn next", "Practice", "Maintain"]
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


# ---------------------------------------------------------------- connector settings (owner session)


class ConnectorTokenIn(BaseModel):
    label: str = Field(default="Claude Desktop", min_length=1, max_length=100)


class ConnectorTokenOut(BaseModel):
    id: uuid.UUID
    label: str
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
    expected_points: list[str] = Field(default_factory=list, max_length=12)
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


class TargetIn(BaseModel):
    course_id: uuid.UUID
    kind: Literal["kolokvij", "izpit", "other"]
    name: str = Field(min_length=1, max_length=120)
    due_date: date
    scope_description: str = Field(min_length=1, max_length=2000, description="The learner's own words")
    scope: list[TargetScopeItem] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    goal: Literal["exam_only", "long_term"] = "long_term"


class TargetUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["kolokvij", "izpit", "other"] | None = None
    goal: Literal["exam_only", "long_term"] | None = None
    due_date: date | None = None
    status: Literal["upcoming", "passed", "failed", "cancelled"] | None = None
    result: str | None = Field(default=None, max_length=120)
    scope_description: str | None = Field(default=None, min_length=1, max_length=2000)
    scope: list[TargetScopeItem] | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)


class TopicWeight(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    concept_id: uuid.UUID | None = None
    weight: float = Field(default=1.0, ge=0.5, le=2.0)


class ItemType(BaseModel):
    type: str = Field(min_length=1, max_length=60)
    share: float = Field(ge=0, le=1)


class TargetProfileIn(BaseModel):
    source_id: uuid.UUID | None = None
    item_types: list[ItemType] = Field(default_factory=list, max_length=12)
    bloom_mix: dict[str, float] = Field(default_factory=dict)
    topic_weights: list[TopicWeight] = Field(default_factory=list, max_length=60)
    example_items: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=4000)
    model_name: str | None = Field(default=None, max_length=120)


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


class KnownConceptsIn(BaseModel):
    concept_ids: list[uuid.UUID] = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=500, description="What the learner said, e.g. covered in lectures")


# ---------------------------------------------------------------- Pomodoro focus time


class FocusSessionIn(BaseModel):
    client_session_id: uuid.UUID
    course_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime
    planned_minutes: int = Field(ge=1, le=240)
    focused_seconds: int = Field(ge=60, le=14_400, description="Time in focus, pauses excluded")
    completed: bool = Field(description="False when the learner stopped the block early")
