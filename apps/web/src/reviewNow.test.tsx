import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { gradeMessage } from "./components/StudyIn";
import { ReviewPage } from "./pages/Review";
import { ReviewRunPage } from "./pages/ReviewRun";
import type { WaitingAnswers } from "./types";

// Review now and Grade my answers in… (UI direction, 2026-11-27): due concepts are answered here from memory, then
// the saved answers go to an assistant in one go.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const WAITING: WaitingAnswers = {
  total: 2,
  items: [
    { attempt_id: "a1", question_id: "q1", course_id: "k1", course_title: "Security", quiz_id: null, prompt: "Why?", unsure: true, submitted_at: "2026-11-27T08:00:00Z", self_grade: null },
    { attempt_id: "a2", question_id: "q2", course_id: "k1", course_title: "Security", quiz_id: null, prompt: "How?", unsure: false, submitted_at: "2026-11-27T08:01:00Z", self_grade: null },
  ],
};

function serve(waiting: WaitingAnswers = { items: [], total: 0 }) {
  const posted: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/attempts" && init?.method === "POST") {
      posted.push(JSON.parse(String(init.body)));
      return json({ attempt_id: `a${posted.length}`, saved_at: "2026-11-27T08:00:00Z" }, 201);
    }
    if (path === "/reviews/questions")
      return json({
        course_id: "k1",
        items: [
          { concept_id: "c1", term: "Phishing", question_id: "q1", bloom_level: 2 },
          { concept_id: "c2", term: "OSINT", question_id: "q2", bloom_level: 3 },
        ],
        without_question: [{ concept_id: "c3", term: "Pretexting" }],
      });
    if (path.startsWith("/questions/")) {
      const id = path.split("/")[2];
      return json({ id, course_id: "k1", bloom_level: 2, prompt: `Question ${id}`, rubric: { expected_points: ["x"] } });
    }
    if (path === "/answers/waiting") return json(waiting);
    if (path === "/reviews/due")
      return json({ items: [{ concept_id: "c1", course_id: "k1", term: "Phishing", due_at: "2026-11-25T08:00:00Z", is_due: true, step: 1, evidence_count: 1, lapse_count: 0, last_review_at: "2026-11-22T08:00:00Z", due_reason: {} }], note: "" });
    if (path === "/courses") return json([{ id: "k1", title: "Security" }]);
    if (path === "/settings/assistants") return json({ items: [{ key: "codex", connected: true, tokens: 0, last_used_at: null }], in_use: null, chosen: null });
    if (path === "/auth/session") return json({ user: { assistant: null } });
    return json({ items: [] });
  });
  return posted;
}

function show(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/review/now/:courseId" element={<ReviewRunPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Review now (2026-11-27)", () => {
  it("offers Review now beside Review in… per course, and the answers waiting for a grade", async () => {
    serve(WAITING);
    show("/review");
    const now = await screen.findByRole("link", { name: "Review now" });
    expect(now.getAttribute("href")).toBe("/review/now/k1");
    expect(screen.getByRole("button", { name: "Review Security in" }).className).not.toContain("primary");
    const waiting = await screen.findByRole("region", { name: "2 answers waiting for a grade" });
    expect(within(waiting).getByRole("button", { name: "Grade my answers in" }).textContent).toBe("Grade my answers in…");
  });

  it("asks each due concept from memory, then sums up and offers grading in one go", async () => {
    const posted = serve();
    show("/review/now/k1");
    expect(await screen.findByText("1 of 2")).toBeTruthy();
    expect(screen.getByText(/Phishing · from memory/)).toBeTruthy();
    fireEvent.change(await screen.findByLabelText(/Your answer/), { target: { value: "Fake mail that asks for a password." } });
    fireEvent.click(screen.getByRole("button", { name: "Unsure" }));
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));

    expect(await screen.findByText("2 of 2")).toBeTruthy();
    expect(await screen.findByText("Question q2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I don't know" }));

    expect(await screen.findByRole("heading", { name: "Review done" })).toBeTruthy();
    expect(screen.getByText(/1 answer saved\. Each is waiting for a grade/)).toBeTruthy();
    expect(screen.getByText("Saved · unsure")).toBeTruthy();
    expect(screen.getByText("I don't know")).toBeTruthy();
    // a concept without a saved question goes to the assistant instead
    expect(screen.getByText(/Pretexting has no saved question/)).toBeTruthy();
    expect(posted.map((p) => (p as { kind: string; unsure: boolean }).kind)).toEqual(["answer", "dont_know"]);
    expect((posted[0] as { unsure: boolean }).unsure).toBe(true);
  });

  it("writes one grading message with the waiting answers", () => {
    const text = gradeMessage(WAITING);
    expect(text).toMatch(/^Please grade my answers in RecallSpring: 2 saved answers wait for a grade\./);
    expect(text).toContain("- Security: question_id q1, attempt_id a1 (marked unsure)");
    expect(text).toContain("- Security: question_id q2, attempt_id a2");
    expect(gradeMessage({ ...WAITING, total: 30 })).toContain("…and 28 more (get_answers_to_grade lists them all).");
  });
});
