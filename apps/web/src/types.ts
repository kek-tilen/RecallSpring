// Shapes returned by the RecallSpring API (services/api). Kept narrow: only what the web app reads.

export type StudyStatus = "not_studied" | "studied" | "known";
export type Band = "not_started" | "emerging" | "developing" | "reliable";

export type AssistantKey = "claude" | "codex" | "chatgpt" | "antigravity";
/** The welcome page's choice: one assistant, or a mix of two or three (listed in `assistant_mix`). */
export type AssistantChoice = AssistantKey | "mix";

/** Settings → Assistants: what RecallSpring's own records say is connected (GET /settings/assistants). */
export interface AssistantsStatus {
  /** `in_mix`: one of the learner's mix (listed first). */
  items: { key: AssistantKey; connected: boolean; tokens: number; last_used_at: string | null; in_mix?: boolean }[];
  /** The assistant the wording names: the only connected one, the welcome choice while none is, null when several are. */
  in_use: AssistantKey | null;
  chosen: AssistantChoice | null;
  mix?: AssistantKey[];
}

export interface User {
  id: string;
  username: string;
  timezone: string;
  assistant: AssistantChoice | null;
  assistant_mix?: AssistantKey[];
  greeting_name?: string | null;
  /** how assistants explain new material by default (2026-11-26) */
  explanation_pace?: ExplanationPace;
}

export type ExplanationPace = "step" | "balanced" | "chunks" | "auto";

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
export type MaterialCategory = "material" | "notes" | "exercises" | "past_paper" | "chat" | "other";

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
  /** With no exam coming up: the latest one behind the learner. */
  last_target?: { id: string; kind: string; name: string; due_date: string; days_left: number; status: string } | null;
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
  check?: CheckResult | null;
}

/** The latest Check first result of a concept (services/check_first.py). */
export interface CheckResult {
  result: "green" | "yellow" | "red" | "pending";
  label: string;
  why: string;
  greens: number;
  checked_at: string | null;
  quiz_id: string;
}

export interface Chapter {
  key: string;
  title: string;
  concept_ids: string[];
}

export interface PracticeLimit {
  level: number;
  label: string;
  set_by_learner: boolean;
  /** without a limit of the learner's own: why it is 5, or 6 when an exam paper asks for Create (2026-11-26) */
  automatic?: string | null;
  exam_profile_above: { target_id: string; target: string; share: number; confirmed: boolean } | null;
  warning: string | null;
  /** at 6 Create: use a more capable model */
  model_tip?: string | null;
}

export interface TargetProfile {
  id: string;
  source_id?: string | null;
  /** The old paper in RecallSpring the analysis came from; null when it was only shared in a chat. */
  source?: { id: string; filename: string; removed: boolean } | null;
  item_types: { type: string; share: number }[];
  bloom_mix: Record<string, number>;
  topic_weights: { label: string; weight: number; concept_id?: string | null }[];
  example_items: string[];
  notes: string | null;
  derived_by: string;
  created_at: string;
  /** ADR-013: 2 = topics mapped to concepts, points, papers and the learner's confirmation; 1 = before that. */
  version?: number;
  topics?: ProfileTopic[];
  papers?: ProfilePaper[];
  /** Past papers of the course left out on the learner's word (owner 2026-11-25). */
  skipped_papers?: { source_id: string; reason: string; source: { id: string; filename: string; removed: boolean } | null }[];
  /** Past papers of the course the analysis has not looked at. */
  not_looked_at?: { id: string; filename: string }[];
  /** Files of the papers without a stated reason they belong there. */
  evidence_missing?: { id: string; filename: string }[];
  unreadable?: string[];
  confirmation?: "confirmed" | "unconfirmed" | "before_confirmation";
  confirmed_at?: string | null;
  confirmed_via?: "assistant" | "web" | null;
}

/** One file of an analysed paper, with what shows it belongs there (owner 2026-11-25). */
export interface PaperFile {
  id: string;
  filename: string;
  removed: boolean;
  why?: string | null;
  /** strong: the file itself shows it (header, date); weak: only inferred (numbering, layout). */
  strength?: "strong" | "weak" | null;
}

export interface ProfilePaper {
  source_id: string | null;
  label: string | null;
  total_points: number | null;
  duration_minutes: number | null;
  source: { id: string; filename: string; removed: boolean } | null;
  /** The exam the paper was for, e.g. "2. kolokvij 2026". */
  exam?: string | null;
  /** "style": only its kind of questions counts; "style_and_topics": its topics weigh too. */
  use?: "style" | "style_and_topics";
  /** Further files of the same paper, e.g. its second photo. */
  extra_source_ids?: string[];
  /** Every file of the paper in RecallSpring, the first one first (owner 2026-11-25). */
  files?: PaperFile[];
}

export interface ProfileTopic {
  label: string;
  concept_ids: string[];
  not_in_material: boolean;
  points: number | null;
  share: number | null;
  where: string | null;
  papers: string[];
  weight: number;
  /** Only on papers used for their style: listed, but it does not weigh. */
  style_only?: boolean;
}

export interface ScopeItem {
  kind: string;
  source_id?: string;
  filename?: string | null;
  pages?: [number, number];
  topic_id?: string;
  concept_id?: string;
}

/** ADR-014 §4: how the reviews go in the days before an exam. */
export type BeforeExam = "regular" | "extra_review" | "intense";

export interface Target {
  id: string;
  kind: string;
  name: string;
  due_date: string;
  days_left: number;
  status: string;
  result: string | null;
  goal: string | null;
  /** The learner's choice (chosen) or the goal's default, in words; never a chance of remembering. */
  before_exam?: { choice: BeforeExam; label: string; goal_default: BeforeExam; chosen: boolean };
  scope_description: string;
  scope: ScopeItem[];
  notes: string | null;
  concepts_in_scope: number;
  profile: TargetProfile | null;
  duplicates?: string[];
}

// ADR-013 §5: a page an assistant read for something on an old paper that the material does not cover
export interface WebLink {
  url: string;
  title: string | null;
  read_on: string;
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
  folder_id: string | null;
  folder: string | null; // "Lectures / Week 3"
  archived: boolean; // archived itself
  hidden: boolean; // archived itself or inside an archived folder
  archived_at: string | null;
  duplicate_of_id: string | null;
  parse_state: "pending" | "processing" | "ready" | "needs_attention" | "failed";
  parse_message: string | null;
  parse_notes: string[];
  page_count: number | null;
  version: number;
  section_count: number;
  uploaded_at: string;
  parsed_at: string | null;
  web_links?: WebLink[]; // origin "web" only
}

export interface Folder {
  id: string;
  course_id: string;
  parent_id: string | null;
  name: string;
  path: string;
  archived: boolean;
  hidden: boolean; // archived itself or inside an archived folder
  archived_at: string | null;
  files: number;
  revision: number;
  created_at: string;
}

export interface CourseRef {
  id: string;
  title: string;
  color: CourseColor | null;
}

export interface ArchivedView {
  groups: (Group & { path: string })[];
  courses: (Course & { group_path: string; long_term_retention: boolean })[];
  folders: (Folder & { course: CourseRef })[];
  sources: (Source & { course: CourseRef })[];
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
  /** retakes (2026-11-26): 1 = the first version (the benchmark); later ones answer seen questions */
  version?: number;
  retake_of?: string | null;
  same_day_practice?: boolean;
}

/** Every version of a simulation side by side (2026-11-26); null without retakes. */
export interface QuizComparison {
  benchmark_quiz_id: string;
  versions: {
    version: number;
    quiz_id: string;
    status: "open" | "submitted";
    scope: "first" | "all" | "not_full";
    submitted_at: string | null;
    earned_points: number | null;
    max_points: number | null;
    pending_items: number | null;
    same_day_practice: boolean;
  }[];
  questions: {
    position: number;
    question_id: string;
    prompt: string;
    points: number;
    versions: ({ version: number; quiz_id: string; earned: number | null; grade: number | null; kind: string | null } | null)[];
  }[];
}

export interface CourseOverview {
  course: CourseInfo;
  active_target_id: string | null;
  targets: Target[];
  progress: Progress;
  concepts: ConceptRow[];
  chapters?: Chapter[];
  practice_limit?: PracticeLimit;
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
  unsure?: boolean;
  captured_via: string;
  submitted_at: string;
  status: string;
  quiz: { id: string; title: string; mode: string } | null;
  grade: number | null;
  assessment_status: string | null;
  graded_by: string | null;
  grader?: Grader | null;
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

/** One grade of an answer (GET /attempts/{id}); the newest one that counts is `effective_assessment_id`. */
export interface AssessmentDetail {
  id: string;
  evaluator_kind: string;
  provider: string | null;
  model: string | null;
  status: string; // final | provisional | ungraded | superseded ...
  grade: number | null;
  confidence: string;
  feedback: string;
  evidence_refs: unknown[];
  strengths: unknown[];
  gaps: unknown[];
  remediation: string | null;
  factuality_flags: unknown[];
  created_at: string;
}

export interface AttemptDetail {
  id: string;
  question_id: string;
  kind: string;
  answer_text: string;
  answer_mode: string;
  captured_via: string;
  status: string;
  submitted_at: string;
  assessments: AssessmentDetail[];
  effective_assessment_id: string | null;
  photos?: { id: string; filename: string | null; available: boolean }[];
  /** the learner marked it as unsure (an open answer) or a guess (a closed one); graded normally when open */
  unsure?: boolean;
}

export interface AttemptRow {
  attempt_id: string;
  course_id: string;
  /** Results → Answers (2026-11-27) */
  question_id?: string;
  concepts?: { id: string; term: string }[];
  feedback?: string | null;
  question: string;
  question_type: "open" | "mcq";
  bloom_level: number;
  kind: string;
  unsure?: boolean;
  captured_via: string;
  status: string;
  submitted_at: string;
  quiz_id: string | null;
  grade: number | null;
  assessment_status: string | null;
  graded_by: string | null;
  grader?: Grader | null;
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
  guessing?: boolean; // a closed answer marked as a guess
  unsure?: boolean; // an open answer marked as unsure (graded normally)
  grade?: number | null;
  assessment_status?: string | null;
  feedback?: string | null;
  graded_by?: string | null;
  grader?: Grader | null;
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
  draft?: Record<string, { option?: string | null; text?: string | null; dont_know?: boolean; guessing?: boolean; unsure?: boolean }>;
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
  version?: number;
  retake_of?: string | null;
  seen_questions?: boolean;
  same_day_practice?: boolean;
  comparison?: QuizComparison | null;
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
  category: "Review due" | "Relearn" | "Strengthen" | "Learn next" | "Practice" | "Maintain";
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
  /** ADR-014: how deep a review goes (quick: one short question; relearn: feedback and another try). */
  depth?: "quick" | "standard" | "relearn" | null;
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
  /** ADR-014: work for the days before an exam that did not fit today; it stays due. */
  left_out?: { concept_id: string; term: string; course_id: string; target: string | null; category: string }[];
}

export interface AttentionItem {
  kind: "source" | "quiz" | "answers" | "duplicates" | "backup" | "cloud";
  id: string | null;
  course_id: string | null;
  title: string;
  text: string | null;
}

export type ReadinessState = "not_studied" | "weak" | "not_practised" | "developing" | "solid";
export type ReadinessCounts = Record<ReadinessState, number>;

export interface ReadinessConcept {
  id: string;
  term: string;
  state: ReadinessState;
  band: Band;
  last_grade: number | null;
  lapses: number;
  due: boolean;
  next_review: string | null;
  difficulty: number;
  exam_weight: number | null;
  citations: string[];
  feedback: {
    attempt_id: string;
    answered_at: string;
    grade: number | null;
    status: string;
    question: string;
    gaps: string[];
    remediation: string | null;
  } | null;
}

// ADR-013 §2: Why this plan, computed by the server (rationale-v1)
export interface RationaleTopic {
  label: string;
  points: number | null;
  share: number | null;
  where: string | null;
  papers: string[];
  weight: number;
  not_in_material: boolean;
  unmapped: boolean;
  from_web: boolean;
  style_only: boolean;
  status: "not_studied" | "in_progress" | "weak" | "solid" | "not_in_material" | "unmapped";
  concepts: { id: string; term: string; state: ReadinessState; due: boolean; in_scope: boolean }[];
  counts: ReadinessCounts;
}

export interface PlanRationale {
  policy_version: string;
  generated_at: string;
  target: ExamReadiness["target"];
  profile: TargetProfile | null;
  topics: RationaleTopic[];
  coverage: { basis: "points" | "share" | "topics"; studied_percent: number; ready_percent: number; solid_percent: number; not_in_material_percent: number } | null;
  bloom: { paper: Record<string, number>; practised: Record<string, number>; practice_limit: number; paper_above_limit: number };
  today: {
    items: { concept_id: string; term: string; category: string; minutes: number; topics: { label: string; points: number | null; share: number | null }[]; why: string }[];
    minutes: number;
    other_courses_items: number;
    note: string | null;
  };
  order_rules: string[];
  fit: { days_left: number; summary: ExamReadiness["summary"]; capacity: ExamReadiness["capacity"] };
  not_on_paper: { count: number; terms: string[] };
  limits: { code: string; message: string }[];
  note: string;
}

export interface ExamReadiness {
  policy_version: string;
  generated_at: string;
  target: {
    id: string;
    name: string;
    kind: string;
    status: string;
    due_date: string;
    days_left: number;
    scope_description: string;
    course: { id: string; title: string; color: CourseColor | null };
  };
  summary: ReadinessCounts & { concepts: number; due: number; ready_percent: number; remaining_minutes: number };
  capacity: { status: "ok" | "tight" | "at_risk"; remaining_minutes: number; available_minutes: number; message: string } | null;
  groups: {
    kind: "topic" | "source" | "none";
    id: string | null;
    title: string;
    pages: string | null;
    counts: ReadinessCounts;
    concepts: ReadinessConcept[];
  }[];
  weakest: {
    id: string;
    term: string;
    group: string;
    last_grade: number | null;
    reason: string;
    gaps: string[];
    remediation: string | null;
    citations: string[];
  }[];
  simulations: QuizSummary[];
  next_steps: string[];
  note: string;
}

export interface WeekReview {
  policy_version: string;
  generated_at: string;
  week: { start: string; end: string; weeks_ago: number; is_current: boolean; days_counted: number };
  planned_minutes: number;
  session_minutes: number;
  sessions: { timed: number; untimed: number };
  activity: {
    answers: number;
    graded: number;
    concepts_studied: number;
    concepts_known: number;
    simulations: number;
    notes: number;
    materials: number;
    active_days: string[];
  };
  grades: { count: number; average: number | null; previous_average: number | null; distribution: number[] };
  courses: {
    id: string;
    title: string;
    color: CourseColor | null;
    kind: CourseKind;
    answers: number;
    graded: number;
    average_grade: number | null;
    concepts_studied: number;
  }[];
  reviews: { overdue: number; due_next_7_days: number } | null;
  exams: (ReadinessCounts & {
    id: string;
    name: string;
    course_id: string;
    course_title: string;
    course_color: CourseColor | null;
    due_date: string;
    days_left: number;
    concepts: number;
  })[];
  summary: string[];
  note: string;
}

export interface BackupStatus {
  enabled: boolean;
  location: string;
  /** Where the folder comes from: chosen in Settings, the server settings (RS_BACKUP_DIR), or the default. */
  location_source: "settings" | "server" | "default";
  server_location: string;
  /** False when the server keeps the folder to its settings. */
  folder_from_web: boolean;
  /** A sync app recognised from the folder's path, e.g. "Dropbox". A hint only. */
  sync: string | null;
  /** Only the first account may change backups (they hold the whole installation). */
  can_change: boolean;
  same_disk_as_storage: boolean;
  /** How often backups run (2026-11-27): chosen in Settings, else the server settings. */
  schedule: { every: "days" | "monthly"; days: number | null; day_of_month: number | null; at: string; source: "settings" | "server" };
  /** For example "Every 2 weeks at 03:00". */
  schedule_label: string;
  /** The first account's time zone, in which the time is meant. */
  timezone: string;
  keep_last: number;
  /** Daily backups keep daily and weekly ones; less frequent ones keep the last keep_last. */
  keeps: "daily_weekly" | "last";
  keep_daily: number;
  keep_weekly: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: { code: string; message: string; at: string | null } | null;
  last: {
    snapshot: string;
    reason: string;
    tables: number;
    rows: number;
    files: number;
    files_copied: number;
    files_missing: number;
    files_bytes: number;
    dump_bytes: number;
    check: "restored" | "listed" | "none";
    removed_snapshots: number;
    seconds: number;
    encrypted?: boolean;
  } | null;
  next_due: string | null;
  snapshots: string[];
  disk_bytes: number;
  tools: string | null;
  /** Encryption with a recovery key (2026-11-27): the server holds only the public half. */
  encryption: { on: boolean; key_id: string | null; key_created_at: string | null };
  /** Kept backups made before encryption was turned on. */
  unencrypted_snapshots: number;
  remove_unencrypted_pending: boolean;
  /** Cloud copy of the encrypted backups (2026-11-27). */
  cloud?: CloudView;
}

/** A code to type at Google; the device code itself never reaches the browser. */
export interface CloudDevice {
  user_code: string;
  verification_url: string;
  expires_at: string;
  interval: number;
}

export interface CloudView {
  /** Providers this server has an app ID for. */
  available: { google: boolean };
  provider: "google" | null;
  connected_at: string | null;
  state: "off" | "waiting" | "copying" | "ok" | "failing" | "revoked";
  last_success_at: string | null;
  backups: number | null;
  bytes: number | null;
  free_bytes: number | null;
  error: { code: string; message: string; at: string } | null;
  next_try_at: string | null;
  progress: { done_files: number; total_files: number; done_bytes: number; total_bytes: number } | null;
  pending: CloudDevice | null;
}

/** A new recovery key, returned once and never stored by the server. */
export interface BackupKey {
  identity: string;
  recipient: string;
  key_id: string;
}

export interface BackupFolderCheck {
  path: string | null;
  ok: boolean;
  checks: { id: string; level: "ok" | "warn" | "bad"; text: string }[];
  sync?: string | null;
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
  /** null = the learner's default explanation pace */
  explanation_pace?: ExplanationPace | null;
  /** The assistant Today and the tips name for this course (2026-11-27); null = any. */
  usually_studied_in?: AssistantKey | null;
}

/** A Library file a note links with [name](source:<id>) or shows with ![name](source:<id>). */
export interface NoteRef {
  id: string;
  filename: string | null;
  kind: string | null;
  course_id: string | null;
  missing: boolean; // deleted, or not one of the learner's files
}

export interface Note {
  id: string;
  course_id: string;
  title: string;
  body: string;
  revision: number;
  saved_at: string;
  created_at: string;
  references?: NoteRef[];
  deleted_at?: string | null;
  /** assistant_transcription: an assistant copied it from a chat or transcribed a photo (ADR-011) */
  captured_via?: "app_ui" | "summary_form" | "assistant_transcription";
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

/** Review now (2026-11-27): one saved open question per due concept of a course. */
export interface ReviewQuestions {
  course_id: string;
  items: { concept_id: string; term: string; question_id: string; bloom_level: number }[];
  without_question: { concept_id: string; term: string }[];
}

export interface WaitingAnswer {
  attempt_id: string;
  question_id: string;
  course_id: string;
  course_title: string;
  quiz_id: string | null;
  prompt: string;
  unsure: boolean;
  submitted_at: string;
  self_grade: number | null;
}

/** Saved answers that still wait for a grade, oldest first (at most 50 listed; total counts all). */
export interface WaitingAnswers {
  items: WaitingAnswer[];
  total: number;
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

/** Who graded: "Claude", "Codex", "Antigravity", "RecallSpring (answer key)" or "You", and the model the assistant reported. */
export interface Grader {
  name: string;
  model: string | null;
}

export type AssistantClient = "claude" | "codex" | "antigravity";

export interface ConnectorToken {
  id: string;
  label: string;
  client: AssistantClient;
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
  /** The remote connector's address (…/mcp) when other computers can reach this RecallSpring, else null. */
  remote_url?: string | null;
  /** That address is reachable from the internet (HTTPS, port 443): Claude needs it. */
  remote_from_internet?: boolean;
}

export interface StudySettings {
  weekly_minutes: number[];
  maintenance_percent: number;
  style_percent: number;
  /** Share of each day kept for interests; 0 = university first. */
  interest_percent: number;
  focus: { course_id: string; course_title: string; kind: CourseKind; until: string } | null;
}

/** Files brought in at once (a ZIP, a folder, chats from ChatGPT): what went in and what was left out, and why. */
export interface ImportResult {
  imported: Source[];
  skipped: { name: string; reason: string }[];
  conversations?: number;
}

export interface ChatImportSummary {
  id: string;
  filename: string;
  created_at: string;
  expires_at: string;
  conversations: number;
  saved: number;
}

export interface ChatConversation {
  key: string;
  title: string;
  created: string | null;
  updated: string | null;
  messages: number;
  bytes: number;
  too_large: boolean;
  project: string | null;
  files: number;
  files_missing: number;
  saved: { course_id: string; source_id: string } | null;
}

/** A ChatGPT data export staged privately until the learner picks what to keep. */
export interface ChatImport {
  id: string;
  filename: string;
  bytes: number;
  created_at: string;
  expires_at: string;
  skipped: number;
  instructions: { about_you: string; how_to_respond: string } | null;
  memories: string[];
  projects: { id: string; chats: number }[];
  conversations: ChatConversation[];
}

export interface StudyPreferences {
  text: string;
  max_chars: number;
}

// ---------------------------------------------------------------- Pomodoro focus time

export interface FocusBlock {
  id: string;
  client_session_id: string;
  course_id: string | null;
  course_title: string | null;
  started_at: string;
  ended_at: string;
  planned_minutes: number;
  minutes: number;
  completed: boolean;
  deleted_at: string | null;
}

export interface FocusSummary {
  today: { date: string; minutes: number; sessions: number };
  days: { date: string; minutes: number; sessions: number }[];
  week_minutes: number;
  by_course: { course_id: string | null; course_title: string | null; minutes: number; sessions: number }[];
  recent: FocusBlock[];
  removed: FocusBlock[]; // removed in the last `restore_days` days, newest first
  restore_days: number;
}

/** One item in Settings › Data & backups › Recently deleted (GET /deleted, 2026-11-27). */
export interface DeletedItem {
  type: "course" | "exam" | "note" | "focus" | "chat";
  id: string;
  title: string;
  course_title: string | null;
  deleted_at: string;
  restorable_until: string;
  /** A course: what comes back with it. */
  brings?: { notes: number; exams: number; materials: number };
  color?: string;
  due_date?: string;
  started_at?: string;
  ended_at?: string;
}

export interface DeletedList {
  restorable_days: number;
  items: DeletedItem[];
}

/** Settings › Account & system › Sign-in (GET /auth/passkeys; docs/08 -> Passkeys). */
export interface PasskeyItem {
  id: string;
  name: string;
  address: string;
  synced: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface SignInView {
  remote_host: string | null;
  password_changed_at: string;
  password_changed: boolean;
  passkeys: PasskeyItem[];
  confirmed_until: string | null;
}
