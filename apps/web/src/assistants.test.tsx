import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswersTab } from "./pages/Course";
import { AssistantsPanel } from "./pages/Settings";
import type { AssistantsStatus } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const item = (key: "claude" | "codex" | "chatgpt", connected: boolean, last: string | null = null) => ({ key, connected, tokens: connected && key !== "chatgpt" ? 1 : 0, last_used_at: last });

describe("Settings → Assistants", () => {
  it("shows what is connected and says 'your assistant' when several are", () => {
    const s: AssistantsStatus = {
      items: [item("claude", true, "2026-11-21T20:00:00Z"), item("codex", true, "2026-11-22T09:18:00Z"), item("chatgpt", false)],
      in_use: null,
      chosen: "claude",
    };
    wrap(<AssistantsPanel s={s} />);
    expect(screen.getAllByText("Connected")).toHaveLength(2);
    expect(screen.getByText("Not connected")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Manage the Codex token" }).getAttribute("href")).toBe("#connector");
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("#chatgpt");
    expect(screen.getByText(/Claude and Codex are connected, so RecallSpring says “your assistant”/)).toBeTruthy();
  });

  it("names the only connected assistant", () => {
    const s: AssistantsStatus = { items: [item("claude", false), item("codex", true), item("chatgpt", false)], in_use: "codex", chosen: "claude" };
    wrap(<AssistantsPanel s={s} />);
    expect(screen.getByText(/RecallSpring names Codex in its tips/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Set up Claude" }).getAttribute("href")).toBe("/welcome");
  });
});

describe("Course → Answers", () => {
  it("opens the exact answer and the grade explanation", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
      const path = url.pathname.replace("/api/v1", "");
      if (path === "/attempts") {
        return json(200, [
          {
            attempt_id: "a1",
            course_id: "k1",
            question: "Explain attack surface vs attack vector.",
            question_type: "open",
            bloom_level: 2,
            kind: "answer",
            captured_via: "answer_form",
            status: "evaluated",
            submitted_at: "2026-11-22T09:18:00Z",
            quiz_id: null,
            grade: 4,
            assessment_status: "final",
            graded_by: "ai",
            grader: { name: "Codex", model: "GPT-6" },
          },
        ]);
      }
      if (path === "/attempts/a1") {
        return json(200, {
          id: "a1",
          question_id: "q1",
          kind: "answer",
          answer_text: "Login form = surface; SQL injection = vector.",
          answer_mode: "closed_notes",
          captured_via: "answer_form",
          status: "evaluated",
          submitted_at: "2026-11-22T09:18:00Z",
          effective_assessment_id: "s1",
          assessments: [
            {
              id: "s1",
              evaluator_kind: "ai",
              provider: "codex_app",
              model: "GPT-6",
              status: "final",
              grade: 4,
              confidence: "high",
              feedback: "You separated the two correctly.",
              evidence_refs: ["sec1"],
              strengths: ["Correct example for each"],
              gaps: [],
              remediation: null,
              factuality_flags: [],
              created_at: "2026-11-22T09:18:30Z",
            },
          ],
        });
      }
      return json(404, { code: "not_found", message: path });
    });
    wrap(<AnswersTab courseId="k1" />);
    const toggle = await screen.findByRole("button", { name: /Explain attack surface/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(await screen.findByText("Login form = surface; SQL injection = vector.")).toBeTruthy();
    expect(screen.getByText("You separated the two correctly.")).toBeTruthy();
    expect(screen.getByText("Correct example for each")).toBeTruthy();
    expect(screen.getByText(/Codex · GPT-6 · confidence high · based on 1 passage of your material/)).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });
});
