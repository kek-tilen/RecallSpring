import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import type {
  ConceptDetail,
  ConnectorSettings,
  Course,
  CourseOverview,
  CourseSummary,
  Dashboard,
  DeletedTarget,
  Group,
  HistoryRow,
  Note,
  QuizSummary,
  QuizView,
  SessionInfo,
  Source,
  StudySettings,
  TimelineTarget,
} from "./types";

export const keys = {
  session: ["session"] as const,
  dashboard: ["dashboard"] as const,
  courses: ["courses"] as const,
  courseSummary: ["courses", "summary"] as const,
  course: (id: string) => ["courses", id, "overview"] as const,
  concept: (id: string) => ["concepts", id] as const,
  quizzes: (courseId?: string) => ["quizzes", courseId ?? "all"] as const,
  quiz: (id: string) => ["quiz", id] as const,
  sources: (courseId?: string) => ["sources", courseId ?? "all"] as const,
  notes: (courseId?: string) => ["notes", courseId ?? "all"] as const,
  history: ["history"] as const,
  groups: ["groups"] as const,
  targets: ["targets"] as const,
  reviews: ["reviews"] as const,
  studySettings: ["settings", "study"] as const,
  connector: ["settings", "connector"] as const,
};

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
export const useSources = (courseId?: string) =>
  useQuery({
    queryKey: keys.sources(courseId),
    queryFn: () => get<Source[]>("/sources", { course_id: courseId }),
    // Keep polling while a file is still being extracted.
    refetchInterval: (q) => (q.state.data?.some((s) => s.parse_state === "pending" || s.parse_state === "processing") ? 2500 : false),
  });
export const useNotes = (courseId?: string) =>
  useQuery({ queryKey: keys.notes(courseId), queryFn: () => get<Note[]>("/notes", { course_id: courseId }) });
export const useHistory = () => useQuery({ queryKey: keys.history, queryFn: () => get<HistoryRow[]>("/history", { limit: 300 }) });
export const useStudySettings = () =>
  useQuery({ queryKey: keys.studySettings, queryFn: () => get<StudySettings>("/settings/study") });
export const useConnector = () => useQuery({ queryKey: keys.connector, queryFn: () => get<ConnectorSettings>("/settings/connector") });

export const useGroups = () => useQuery({ queryKey: keys.groups, queryFn: () => get<Group[]>("/groups") });
export const useDeletedTargets = () =>
  useQuery({ queryKey: ["targets", "deleted"], queryFn: () => get<DeletedTarget[]>("/targets/deleted") });
export const useTargets = () => useQuery({ queryKey: keys.targets, queryFn: () => get<TimelineTarget[]>("/targets") });

/** Everything that shows courses, groups or exams; call after any organisation change. */
export const ORGANISATION_KEYS = [["courses"], ["groups"], ["targets"], ["dashboard"], ["history"]] as const;

export function courseTitles(courses: Course[] | undefined): Record<string, string> {
  return Object.fromEntries((courses ?? []).map((c) => [c.id, c.title]));
}
