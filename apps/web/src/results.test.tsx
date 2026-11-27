import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultsPage, families } from "./pages/Results";
import type { AttemptRow, QuizSummary } from "./types";

// Results (UI direction, 2026-11-27): simulations with their versions side by side, and every answer with its grade.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

const quiz = (id: string, extra: Partial<QuizSummary> = {}): QuizSummary => ({
  id,
  course_id: "k1",
  title: "Midterm 1 practice",
  mode: "practice",
  status: "submitted",
  items: 3,
  created_at: "2026-11-23T08:00:00Z",
  submitted_at: "2026-11-23T09:00:00Z",
  earned_points: 2,
  max_points: 4,
  pending_items: 0,
  version: 1,
  retake_of: null,
  ...extra,
});

const QUIZZES = [
  quiz("v2", { version: 2, retake_of: "v1", earned_points: 1, max_points: 2, created_at: "2026-11-23T10:00:00Z", same_day_practice: true }),
  quiz("v1"),
  quiz("lab", { title: "Lab quiz practice", created_at: "2026-11-16T08:00:00Z", earned_points: 3 }),
];

const row = (id: string, grade: number | null, extra: Partial<AttemptRow> = {}): AttemptRow => ({
  attempt_id: id,
  course_id: "k1",
  question_id: `q-${id}`,
  question: "Why does it stop speeding up?",
  question_type: "open",
  bloom_level: 3,
  kind: "answer",
  captured_via: "app_ui",
  status: grade === null ? "saved_awaiting_evaluation" : "evaluated",
  submitted_at: "2026-11-26T08:00:00Z",
  quiz_id: null,
  grade,
  assessment_status: grade === null ? null : "final",
  graded_by: grade === null ? null : "ai",
  concepts: [{ id: `c-${id}`, term: `Concept ${id}` }],
  feedback: grade === null ? null : "Saturation, correct. Name the carrier next time.",
  ...extra,
});

function serve() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/quizzes") return json(QUIZZES);
    if (path === "/quizzes/v1")
      return json({
        quiz_id: "v1",
        course_id: "k1",
        title: "Midterm 1 practice",
        status: "submitted",
        items: [],
        comparison: {
          benchmark_quiz_id: "v1",
          versions: [
            { version: 1, quiz_id: "v1", status: "submitted", scope: "first", submitted_at: null, earned_points: 2, max_points: 4, pending_items: 0, same_day_practice: false },
            { version: 2, quiz_id: "v2", status: "submitted", scope: "not_full", submitted_at: null, earned_points: 1, max_points: 2, pending_items: 0, same_day_practice: true },
          ],
          questions: [
            { position: 1, question_id: "qa", prompt: "Sodium-potassium pump", points: 2, versions: [{ version: 1, quiz_id: "v1", earned: 1, grade: 2, kind: "answer" }, { version: 2, quiz_id: "v2", earned: 2, grade: 3, kind: "answer" }] },
            { position: 2, question_id: "qb", prompt: "Membrane fluidity", points: 2, versions: [{ version: 1, quiz_id: "v1", earned: 2, grade: 3, kind: "answer" }, null] },
          ],
        },
      });
    if (path === "/attempts") return json([row("a", 3), row("b", 1, { course_id: "k2" }), row("c", null)]);
    if (path === "/courses") return json([{ id: "k1", title: "Cell Biology" }, { id: "k2", title: "Linear Algebra" }]);
    return json({});
  });
}

function show(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/simulations" element={<ResultsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Results (2026-11-27)", () => {
  it("groups a simulation with its retakes, newest first", () => {
    const list = families(QUIZZES);
    expect(list.map((f) => [f.first.id, f.versions.map((v) => v.id)])).toEqual([
      ["v1", ["v1", "v2"]],
      ["lab", ["lab"]],
    ]);
  });

  it("lists simulations with their benchmark score and compares the versions per question", async () => {
    serve();
    show("/simulations");
    const list = await screen.findByRole("list", { name: "Simulations" });
    const first = within(list).getAllByRole("button")[0]!;
    expect(first.getAttribute("aria-pressed")).toBe("true");
    expect(first.textContent).toContain("Midterm 1 practice");
    expect(first.textContent).toContain("2 versions");
    expect(first.textContent).toContain("2/4");
    const detail = screen.getByRole("region", { name: "Midterm 1 practice" });
    const rows = await within(detail).findAllByRole("row");
    expect(rows[1]!.textContent).toContain("Sodium-potassium pump");
    expect(rows[1]!.textContent).toContain("Partial (2/4)");
    expect(rows[1]!.textContent).toContain("Solid (3/4)");
    expect(rows[2]!.textContent).toContain("–");
    expect(within(detail).getByRole("link", { name: "Open answers" }).getAttribute("href")).toBe("/simulations/v2");
  });

  it("lists every answer with its concept, feedback and grade, filtered by course and grade", async () => {
    serve();
    show("/simulations?view=answers");
    const list = await screen.findByRole("list", { name: "Answers" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(list.textContent).toContain("Concept a");
    expect(list.textContent).toContain("Saturation, correct.");
    expect(list.textContent).not.toContain("Name the carrier");
    expect(list.textContent).toContain("Waiting for a grade");

    fireEvent.change(screen.getByLabelText("Course"), { target: { value: "k2" } });
    expect(within(screen.getByRole("list", { name: "Answers" })).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Course"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Grade"), { target: { value: "waiting" } });
    const waiting = within(screen.getByRole("list", { name: "Answers" })).getAllByRole("listitem");
    expect(waiting.map((li) => li.textContent)).toEqual([expect.stringContaining("Concept c")]);
    expect(screen.getByText("AI grades are study feedback, not a score.")).toBeTruthy();
  });
});
