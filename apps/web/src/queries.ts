import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import type { ArchivedView, AssistantsStatus, BackupStatus, ChatImport, ChatImportSummary, ConceptDetail, ConnectorSettings, Course, CourseOverview, CourseSummary, Dashboard, DeletedTarget, ExamReadiness, FocusSummary, Folder, Group, HistoryRow, Note, QuizSummary, QuizView, SessionInfo, Source, StudyPreferences, StudySettings, TimelineTarget, UploadLimits, WeekReview } from "./types";

export const keys = {
  session: ["session"] as const,
  dashboard: ["dashboard"] as const,
  courses: ["courses"] as const,
  courseSummary: ["courses", "summary"] as const,
  course: (id: string) => ["courses", id, "overview"] as const,
  concept: (id: string) => ["concepts", id] as const,
  quizzes: (courseId?: string) => ["quizzes", courseId ?? "all"] as const,
  quiz: (id: string) => ["quiz", id] as const,
  sources: (courseId?: string, withArchived = false) => ["sources", courseId ?? "all", withArchived ? "with-archived" : "current"] as const,
  folders: (courseId?: string) => ["folders", courseId ?? "all"] as const,
  archived: ["library", "archived"] as const,
  notes: (courseId?: string) => ["notes", courseId ?? "all"] as const,
  history: ["history"] as const,
  groups: ["groups"] as const,
  targets: ["targets"] as const,
  reviews: ["reviews"] as const,
  studySettings: ["settings", "study"] as const,
  connector: ["settings", "connector"] as const,
  // Under connector, so creating or revoking a token refreshes it too.
  assistants: ["settings", "connector", "assistants"] as const,
  backup: ["settings", "backup"] as const,
  readiness: (id: string) => ["targets", id, "readiness"] as const,
  week: (weeksAgo: number) => ["week", weeksAgo] as const,
  chatImports: ["imports", "chatgpt"] as const,
  chatImport: (id: string) => ["imports", "chatgpt", id] as const,
  preferences: ["settings", "preferences"] as const,
  focusSummary: ["focus", "summary"] as const,
};

export const useChatImports = () =>
  useQuery({ queryKey: keys.chatImports, queryFn: () => get<ChatImportSummary[]>("/imports/chatgpt") });
export const useChatImport = (id: string) =>
  useQuery({ queryKey: keys.chatImport(id), queryFn: () => get<ChatImport>(`/imports/chatgpt/${id}`) });
export const usePreferences = () =>
  useQuery({ queryKey: keys.preferences, queryFn: () => get<StudyPreferences>("/settings/preferences") });

export const useFocusSummary = () =>
  useQuery({ queryKey: keys.focusSummary, queryFn: () => get<FocusSummary>("/focus/summary") });

export const useSession = () =>
  useQuery({ queryKey: keys.session, queryFn: () => get<SessionInfo>("/auth/session"), retry: false, staleTime: 60_000 });
export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: () => get<Dashboard>("/dashboard") });
export const useCourses = () => useQuery({ queryKey: keys.courses, queryFn: () => get<Course[]>("/courses"), staleTime: 60_000 });
export const useCourseSummary = () =>
  useQuery({ queryKey: keys.courseSummary, queryFn: () => get<CourseSummary[]>("/overview/courses") });
export const useCourseOverview = (id: string) =>
  useQuery({ queryKey: keys.course(id), queryFn: () => get<CourseOverview>(`/courses/${id}/overview`) });
export const useConcept = (id: string) =>
  useQuery({ queryKey: keys.concept(id), queryFn: () => get<ConceptDetail>(`/concepts/${id}/detail`) });
export const useQuizzes = (courseId?: string) =>
  useQuery({ queryKey: keys.quizzes(courseId), queryFn: () => get<QuizSummary[]>("/quizzes", { course_id: courseId }) });
export const useQuiz = (id: string) => useQuery({ queryKey: keys.quiz(id), queryFn: () => get<QuizView>(`/quizzes/${id}`) });
export const useSources = (courseId?: string, withArchived = false) =>
  useQuery({
    queryKey: keys.sources(courseId, withArchived),
    queryFn: () => get<Source[]>("/sources", { course_id: courseId, archived: withArchived ? "true" : undefined }),
    // Keep polling while a file is still being extracted.
    refetchInterval: (q) => (q.state.data?.some((s) => s.parse_state === "pending" || s.parse_state === "processing") ? 2500 : false),
  });
export const useNotes = (courseId?: string) =>
  useQuery({ queryKey: keys.notes(courseId), queryFn: () => get<Note[]>("/notes", { course_id: courseId }) });
export const useHistory = () => useQuery({ queryKey: keys.history, queryFn: () => get<HistoryRow[]>("/history", { limit: 300 }) });
export const useStudySettings = () =>
  useQuery({ queryKey: keys.studySettings, queryFn: () => get<StudySettings>("/settings/study") });
export const useReadiness = (id: string) =>
  useQuery({ queryKey: keys.readiness(id), queryFn: () => get<ExamReadiness>(`/targets/${id}/readiness`) });
export const useWeek = (weeksAgo: number) =>
  useQuery({ queryKey: keys.week(weeksAgo), queryFn: () => get<WeekReview>("/overview/week", { weeks_ago: weeksAgo }) });
export const useBackup = () => useQuery({ queryKey: keys.backup, queryFn: () => get<BackupStatus>("/settings/backup") });
export const useConnector = () => useQuery({ queryKey: keys.connector, queryFn: () => get<ConnectorSettings>("/settings/connector") });
export const useAssistants = () =>
  useQuery({ queryKey: keys.assistants, queryFn: () => get<AssistantsStatus>("/settings/assistants"), staleTime: 60_000 });

export const useFolders = (courseId?: string) =>
  useQuery({ queryKey: keys.folders(courseId), queryFn: () => get<Folder[]>("/folders", { course_id: courseId }) });
export const useArchived = () => useQuery({ queryKey: keys.archived, queryFn: () => get<ArchivedView>("/library/archived") });
export const useGroups = () => useQuery({ queryKey: keys.groups, queryFn: () => get<Group[]>("/groups") });
export const useDeletedTargets = () =>
  useQuery({ queryKey: ["targets", "deleted"], queryFn: () => get<DeletedTarget[]>("/targets/deleted") });
export const useUploadLimits = () =>
  useQuery({ queryKey: ["upload-limits"], queryFn: () => get<UploadLimits>("/sources/limits"), staleTime: 60_000 });
export const useTargets = () => useQuery({ queryKey: keys.targets, queryFn: () => get<TimelineTarget[]>("/targets") });

/** Everything that shows courses, groups or exams; call after any organisation change. */
export const ORGANISATION_KEYS = [["courses"], ["groups"], ["targets"], ["dashboard"], ["history"], ["library"]] as const;

/** Everything that shows material, folders or the archive; call after a library change. */
export const LIBRARY_KEYS = [["sources"], ["source"], ["folders"], ["library"], ["courses"], ["dashboard"], ["history"]] as const;

export function courseTitles(courses: Course[] | undefined): Record<string, string> {
  return Object.fromEntries((courses ?? []).map((c) => [c.id, c.title]));
}
