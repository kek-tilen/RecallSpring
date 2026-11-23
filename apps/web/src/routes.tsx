import { Navigate, Outlet, createBrowserRouter, useLocation } from "react-router";
import { ExplainPage } from "./components/Clarity";
import { Layout } from "./components/Layout";
import { AnswerPage, SummaryPage } from "./pages/Answer";
import { Loading } from "./components/ui";
import { setTimezone } from "./format";
import { ChatPage } from "./pages/Chat";
import { ConceptPage } from "./pages/Concept";
import { CoursePage } from "./pages/Course";
import { CoursesPage } from "./pages/Courses";
import { ExamsPage } from "./pages/Exams";
import { FocusPage } from "./pages/Focus";
import { GuidePage } from "./pages/Guide";
import { HistoryPage } from "./pages/History";
import { HomePage } from "./pages/Home";
import { ArchivedPage } from "./pages/Archived";
import { ImportPage } from "./pages/Import";
import { CourseLibraryPage, LibraryPage, SourcePage } from "./pages/Library";
import { LoginPage } from "./pages/Login";
import { NotePage, NotesPage } from "./pages/Notes";
import { ReadinessPage } from "./pages/Readiness";
import { ReviewPage } from "./pages/Review";
import { SettingsPage } from "./pages/Settings";
import { SimulationPage, SimulationsPage } from "./pages/Simulations";
import { WeekPage } from "./pages/Week";
import { WelcomePage } from "./pages/Welcome";
import { useSession } from "./queries";

function RequireSession() {
  const session = useSession();
  const location = useLocation();
  if (session.isPending) {
    return (
      <div className="login">
        <Loading />
      </div>
    );
  }
  if (session.error || !session.data) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  setTimezone(session.data.user.timezone);
  return <Outlet />;
}

function NotFound() {
  return (
    <div className="page">
      <h1>Page not found</h1>
      <p className="muted">This page does not exist. Use the menu to continue.</p>
    </div>
  );
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireSession />,
    children: [
      {
        element: <Layout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "courses", element: <CoursesPage /> },
          { path: "courses/:courseId", element: <CoursePage /> },
          { path: "exams", element: <ExamsPage /> },
          { path: "exams/:targetId", element: <ReadinessPage /> },
          { path: "week", element: <WeekPage /> },
          { path: "concepts/:conceptId", element: <ConceptPage /> },
          { path: "review", element: <ReviewPage /> },
          { path: "simulations", element: <SimulationsPage /> },
          { path: "simulations/:quizId", element: <SimulationPage /> },
          { path: "library", element: <LibraryPage /> },
          { path: "library/archived", element: <ArchivedPage /> },
          { path: "library/import", element: <ImportPage /> },
          { path: "library/course/:courseId", element: <CourseLibraryPage /> },
          { path: "library/:sourceId", element: <SourcePage /> },
          { path: "notes", element: <NotesPage /> },
          { path: "notes/:noteId", element: <NotePage /> },
          { path: "chat", element: <ChatPage /> },
          { path: "chat/:conversationId", element: <ChatPage /> },
          { path: "focus", element: <FocusPage /> },
          { path: "answer/:questionId", element: <AnswerPage /> },
          { path: "summary", element: <SummaryPage /> },
          { path: "explain", element: <ExplainPage /> },
          { path: "history", element: <HistoryPage /> },
          { path: "guide", element: <GuidePage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "welcome", element: <WelcomePage /> },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);
