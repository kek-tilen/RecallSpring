import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SimulationPage, similarMessage } from "./pages/Simulations";
import type { QuizView } from "./types";

// 2026-11-26: retakes are new versions with the same questions, compared per question; the
// first version stays the benchmark and a same-day retake is practice only.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const item = (n: number, earned: number | null) => ({
  position: n,
  question_id: `q${n}`,
  type: "mcq" as const,
  prompt: `Question ${n}?`,
  options: [
    { key: "A", text: "a" },
    { key: "B", text: "b" },
  ],
  points: 1,
  earned,
  answer: "A) a",
  kind: "answer",
  grade: earned === null ? null : earned ? 3 : 0,
});
const V2: QuizView = {
  quiz_id: "v2",
  course_id: "k1",
  title: "Midterm sim · version 2",
  status: "submitted",
  mode: "practice",
  created_at: "2026-11-26T10:00:00Z",
  submitted_at: "2026-11-26T11:00:00Z",
  earned_points: 1,
  max_points: 2,
  pending_items: 0,
  items: [item(1, 1), item(2, 0)],
  note: "",
  version: 2,
  retake_of: "v1",
  seen_questions: true,
  same_day_practice: true,
  comparison: {
    benchmark_quiz_id: "v1",
    versions: [
      { version: 1, quiz_id: "v1", status: "submitted", scope: "first", submitted_at: "2026-11-26T09:00:00Z", earned_points: 1, max_points: 3, pending_items: 0, same_day_practice: false },
      { version: 2, quiz_id: "v2", status: "submitted", scope: "not_full", submitted_at: "2026-11-26T11:00:00Z", earned_points: 1, max_points: 2, pending_items: 0, same_day_practice: true },
    ],
    questions: [
      { position: 1, question_id: "q0", prompt: "Question 0?", points: 1, versions: [{ version: 1, quiz_id: "v1", earned: 1, grade: 3, kind: "answer" }, null] },
      { position: 2, question_id: "q1", prompt: "Question 1?", points: 1, versions: [{ version: 1, quiz_id: "v1", earned: 0, grade: 0, kind: "answer" }, { version: 2, quiz_id: "v2", earned: 1, grade: 3, kind: "answer" }] },
    ],
  },
};

function serve(quiz: QuizView) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === `/quizzes/${quiz.quiz_id}` && (init?.method ?? "GET") === "GET") return json(quiz);
    if (path === `/quizzes/${quiz.quiz_id}/retake`) return json({ quiz_id: "v3", version: 3 }, 201);
    if (path === "/courses") return json([{ id: "k1", title: "Biology", description: null, status: "active", kind: "course", color: null, group_id: null }]);
    if (path === "/settings/assistants") return json({ items: [{ key: "codex", connected: true, tokens: 0, last_used_at: null }], in_use: null, chosen: null });
    if (path === "/auth/session") return json({ user: { assistant: null } });
    return json({});
  });
}

function Where() {
  const at = useLocation();
  return <p>at {at.pathname}</p>;
}

function show(id: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/simulations/${id}`]}>
        <Routes>
          <Route path="/simulations/:quizId" element={<SimulationPage />} />
          <Route path="/simulations/v3" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Simulation retakes (2026-11-26)", () => {
  it("labels a same-day retake and compares every version per question", async () => {
    serve(V2);
    show("v2");
    expect(await screen.findByText("Version 2 · seen questions")).toBeTruthy();
    expect(screen.getByText("Practice only")).toBeTruthy();
    const table = (await screen.findByRole("heading", { name: "All versions" })).closest("section")!;
    expect(within(table).getByText("Benchmark")).toBeTruthy();
    expect(within(table).getByText("Missed only · practice only")).toBeTruthy();
    expect(within(table).getByRole("link", { name: "Version 1" }).getAttribute("href")).toBe("/simulations/v1");
    const rows = within(table).getAllByRole("row").map((r) => r.textContent);
    expect(rows[1]).toContain("1 / 1—");
    expect(rows[2]).toContain("0 / 11 / 1");
  });

  it("retakes only the questions without full points and opens the new version", async () => {
    const fetch = serve(V2);
    show("v2");
    const button = await screen.findByRole("button", { name: "Retake questions without full points (1)" });
    expect(screen.getByRole("button", { name: "Similar, new questions in" })).toBeTruthy();
    fireEvent.click(button);
    expect(await screen.findByText("at /simulations/v3")).toBeTruthy();
    const call = fetch.mock.calls.find(([input]) => String(input).includes("/retake"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ scope: "not_full" });
  });

  it("waits for every grade before retaking only the missed questions", async () => {
    serve({ ...V2, version: 1, retake_of: null, same_day_practice: false, comparison: null, pending_items: 1, items: [item(1, null), item(2, 0)] });
    show("v2");
    const missed = (await screen.findByRole("button", { name: /Retake questions without full points/ })) as HTMLButtonElement;
    expect(missed.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Retake all questions" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/waits until every answer is graded/)).toBeTruthy();
    expect(screen.queryByText(/seen questions/)).toBeNull();
  });

  it("asks for similar, new questions, never the same ones", () => {
    expect(similarMessage({ quiz_id: "v1", title: "Midterm sim", course_id: "k1" })).toContain("never the same questions");
  });
});
