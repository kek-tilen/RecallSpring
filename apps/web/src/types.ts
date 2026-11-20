// Shapes returned by the RecallSpring API (services/api). Kept narrow: only what the web app reads.

export type StudyStatus = "not_studied" | "studied" | "known";
export type Band = "not_started" | "emerging" | "developing" | "reliable";

export interface User {
  id: string;
  username: string;
  timezone: string;
}

export interface SessionInfo {
  user: User;
  expires_at: string;
}

export interface Progress {
  study: Record<StudyStatus, number>;
  bands: Record<Band, number>;
  concepts: number;
}

export type CourseColor = "blue" | "orange" | "aqua" | "yellow" | "magenta" | "green" | "violet" | "red";
export type MaterialCategory = "material" | "notes" | "exercises" | "past_paper" | "other";

export type CourseKind = "course" | "interest";

export interface CourseInfo {
  id: string;
  title: string;
  description: string | null;
  status: string;
  /** "interest": personal learning without exams or a deadline; its description is the learner's goal. */
  kind: CourseKind;
  /** The learner chose to concentrate on it until this day (inclusive). */
  focus_until: string | null;
  color: CourseColor | null;
  group_id: string | null;
  long_term_retention: boolean;
  created_at: string;
}

export interface Group {
  id: string;
  parent_id: string | null;
  kind: "university" | "faculty" | "semester" | "other";
  name: string;
  position: number;
  status: "active" | "archived";
  starts_on: string | null;
  ends_on: string | null;
  archived_at: string | null;
  courses: number;
}

export interface CourseSummary extends CourseInfo {
  group_path: string[];
  active_target: { id: string; kind: string; name: string; due_date: string; days_left: number; status: string } | null;
  progress: Progress;
  sources: number;
  notes: number;
  simulations: number;
  due_reviews: number;
}

export interface ReviewInfo {
  due_at: string;
  is_due: boolean;
  step: number;
  reason: string | null;
  evidence_count: number;
  lapse_count: number;
  last_review_at: string;
}

export interface SectionRef {
  section_id: string;
  label: string;
  filename: string;
}

export interface ConceptRow {
  id: string;
  term: string;
  definition_draft: string | null;
  study_status: StudyStatus;
  band: Band;
  difficulty: number;
  difficulty_source: string;
  review: ReviewInfo | null;
  sections: SectionRef[];
}

export interface TargetProfile {
  id: string;
  item_types: { type: string; share: number }[];
  bloom_mix: Record<string, number>;
  topic_weights: { label: string; weight: number; concept_id?: string | null }[];
  example_items: string[];
  notes: string | null;
  derived_by: string;
  created_at: string;
}

export interface ScopeItem {
  kind: string;
  source_id?: string;
  filename?: string | null;
  pages?: [number, number];
  topic_id?: string;
  concept_id?: string;
}

export interface Target {
  id: string;
  kind: string;
  name: string;
  due_date: string;
  days_left: number;
  status: string;
  result: string | null;
  goal: string | null;
  scope_description: string;
  scope: ScopeItem[];
  notes: string | null;
  concepts_in_scope: number;
  profile: TargetProfile | null;
  duplicates?: string[];
}

export interface Source {
  id: string;
  course_id: string;
  filename: string;
  kind: string;
  mime_type: string;
  byte_size: number;
  origin: string;
  category: MaterialCategory;
  duplicate_of_id: string | null;
  parse_state: "pending" | "processing" | "ready" | "needs_attention" | "failed";
  parse_message: string | null;
  parse_notes: string[];
  page_count: number | null;
  version: number;
  section_count: number;
  uploaded_at: string;
  parsed_at: string | null;
}

export interface QuizSummary {
  id: string;
  course_id: string;
  title: string;
  mode: "practice" | "diagnostic";
  status: "open" | "submitted";
  items: number;
  created_at: string;
  submitted_at: string | null;
  earned_points: number | null;
  max_points: number | null;
  pending_items: number | null;
}

export interface CourseOverview {
  course: CourseInfo;
  active_target_id: string | null;
  targets: Target[];
  progress: Progress;
  concepts: ConceptRow[];
  sources: Source[];
  notes: number;
  quizzes: QuizSummary[];
  note: string;
}

export interface AttemptHistory {
  attempt_id: string;
  question: string | null;
  bloom_level: number | null;
  answer: string;
  kind: string;
  captured_via: string;
  submitted_at: string;
  status: string;
  quiz: { id: string; title: string; mode: string } | null;
  grade: number | null;
  assessment_status: string | null;
  graded_by: string | null;
  feedback: string | null;
}

export interface ConceptDetail {
  id: string;
  course_id: string;
  term: string;
  definition_draft: string | null;
  study_status: StudyStatus;
  study_source: string | null;
  studied_at: string | null;
  band: Band;
  difficulty: number;
  difficulty_source: string;
  review: ReviewInfo | null;
  sections: SectionRef[];
  attempts: AttemptHistory[];
  note: string;
}

export interface AttemptRow {
  attempt_id: string;
  course_id: string;
  question: string;
  question_type: "open" | "mcq";
  bloom_level: number;
  kind: string;
  captured_via: string;
  status: string;
  submitted_at: string;
  quiz_id: string | null;
  grade: number | null;
  assessment_status: string | null;
  graded_by: string | null;
}

export interface QuizOption {
  key: string;
  text: string;
}

export interface QuizItemView {
  position: number;
  question_id: string;
  type: "mcq" | "open";
  prompt: string;
  options: QuizOption[] | null;
  points: number;
  bloom_level?: number;
  earned?: number | null;
  answer?: string | null;
  kind?: string | null;
  grade?: number | null;
  assessment_status?: string | null;
  feedback?: string | null;
  graded_by?: string | null;
  correct_option?: string | null;
  expected_points?: string[];
  source_refs?: string[];
}

export interface TimelineTarget extends Target {
  course_id: string;
  course_title: string;
  course_color: CourseColor | null;
  course_status: string;
  revision: number;
  created_at: string;
  simulations: number;
  duplicates: string[];
}

export interface UploadLimits {
  document_bytes: number;
  text_bytes: number;
  image_bytes: number;
  library_bytes: number;
  library_used_bytes: number;
  page_renderer_available: boolean;
  extensions: { document: string[]; text: string[]; image: string[] };
}

export interface DeletedTarget {
  id: string;
  name: string;
  kind: string;
  due_date: string;
  course_id: string;
  course_title: string;
  course_color: CourseColor | null;
  deleted_at: string | null;
}

export interface QuizView {
  quiz_id: string;
  opened_at?: string | null;
  deadline?: string | null;
  draft?: Record<string, { option?: string | null; text?: string | null; dont_know?: boolean }>;
  draft_saved_at?: string | null;
  course_id: string;
  title: string;
  status: "open" | "submitted";
  mode: "practice" | "diagnostic";
  created_at: string;
  submitted_at?: string | null;
  time_limit_minutes?: number | null;
  earned_points?: number;
  max_points?: number;
  pending_items?: number;
  complete?: boolean;
  items: QuizItemView[];
  note?: string;
}

export interface HistoryRow {
  at: string;
  kind: "learning" | "audit";
  type: string;
  text: string;
  detail: string | null;
  entity_type: string | null;
  entity_id: string | null;
  label: string | null;
}

export interface PlanItem {
  category: "Review due" | "Strengthen" | "Learn next" | "Practice" | "Maintain";
  concept_id: string;
  term: string;
  course_id: string;
  course_title: string;
  course_kind: CourseKind;
  focus: boolean;
  why_selected: string;
  estimated_minutes: number;
  target: string | null;
  band: Band;
  study_status: StudyStatus;
  difficulty: number;
  difficulty_source: string;
  sections: { section_id: string; citation_label: string; filename: string }[];
}

export interface TargetCapacity {
  course_id: string;
  course_title: string;
  target_id: string;
  target: string;
  due_date: string;
  days_left: number;
  concepts_in_scope: number;
  remaining_minutes: number;
  available_minutes: number;
  status: "ok" | "tight" | "at_risk";
  message: string;
}

export interface Plan {
  available_minutes: number;
  planned_minutes: number;
  maintenance_percent: number;
  items: PlanItem[];
  targets: TargetCapacity[];
  message: string | null;
  note: string;
  interests: {
    policy: "university_first" | "share";
    percent: number;
    reserved_minutes: number;
    planned_minutes: number;
    message: string;
  } | null;
  focus: { course_id: string; course_title: string; kind: CourseKind; until: string; message: string } | null;
}

export interface AttentionItem {
  kind: "source" | "quiz" | "answers" | "duplicates";
  id: string | null;
  course_id: string | null;
  title: string;
  text: string | null;
}

export interface Dashboard {
  plan: Plan;
  attention: AttentionItem[];
  counts: Record<"courses" | "sources" | "concepts" | "notes" | "answers" | "grades" | "simulations", number>;
  recent: HistoryRow[];
}

export interface Course {
  id: string;
  title: string;
  description: string | null;
  status: string;
  kind: CourseKind;
  color: CourseColor | null;
  group_id: string | null;
}

export interface Note {
  id: string;
  course_id: string;
  title: string;
  body: string;
  revision: number;
  saved_at: string;
  created_at: string;
}

export interface NoteRevision {
  id: string;
  kind: "autosave" | "conflict";
  revision: number;
  base_revision: number | null;
  title: string;
  body: string;
  saved_at: string;
}

export interface ReviewItem {
  concept_id: string;
  course_id: string;
  term: string;
  due_at: string;
  is_due: boolean;
  step: number;
  evidence_count: number;
  lapse_count: number;
  last_review_at: string;
  due_reason: { message?: string };
}

export interface Section {
  id: string;
  position: number;
  page: number | null;
  heading: string | null;
  citation_label: string;
  text: string;
}

export interface SearchHit {
  section_id: string;
  source_id: string;
  filename: string;
  citation_label: string;
  snippet: string;
}

export interface ConnectorToken {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ConnectorSettings {
  limit_percent: number;
  daily_default: number;
  daily_limit: number;
  used_today: number;
  tokens: ConnectorToken[];
}

export interface StudySettings {
  weekly_minutes: number[];
  maintenance_percent: number;
  style_percent: number;
  /** Share of each day kept for interests; 0 = university first. */
  interest_percent: number;
  focus: { course_id: string; course_title: string; kind: CourseKind; until: string } | null;
}
