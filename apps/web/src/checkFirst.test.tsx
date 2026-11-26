import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CheckChip, CheckFirstPanel, PracticeLimitControl } from "./components/CheckFirst";
import { QuizForm } from "./components/QuizForm";
import type { CourseOverview, QuizView } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockFetch(body: (url: string, init?: RequestInit) => object = () => ({})) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) =>
      new Response(JSON.stringify(body(String(input), init)), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const concept = (id: string, term: string, check: CourseOverview["concepts"][number]["check"] = null) => ({
  id,
  term,
  definition_draft: null,
  study_status: "not_studied" as const,
  band: "not_started" as const,
  difficulty: 3,
  difficulty_source: "default",
  review: null,
  sections: [],
  check,
});

const overview = {
  course: { id: "c1", title: "Digital forensics" },
  active_target_id: "t1",
  targets: [{ id: "t1", name: "1st midterm" }],
  concepts: [
    concept("a", "Hashing", { result: "green", label: "Already know it", why: "Shown in Check first.", greens: 1, checked_at: "2026-11-20T10:00:00Z", quiz_id: "q" }),
    concept("b", "Chain of custody", { result: "yellow", label: "Partly", why: "One correct closed answer counts as half.", greens: 0, checked_at: "2026-11-20T10:00:00Z", quiz_id: "q" }),
    concept("c", "Imaging"),
  ],
  chapters: [{ key: "topic:1", title: "Evidence", concept_ids: ["a", "b", "c"] }],
} as unknown as CourseOverview;

describe("Check first", () => {
  it("is folded away and shows the message for the assistant only when asked", () => {
    mockFetch();
    wrap(<CheckFirstPanel o={overview} />);
    expect(screen.getByText("Already know some of this? You can check first")).toBeTruthy();
    expect(document.body.textContent).toContain("1 known · 1 partly · 1 not checked");
    expect(document.body.textContent).not.toContain("with RecallSpring's Check first");
    fireEvent.click(screen.getByRole("button", { name: "Check what I know" }));
    expect(document.body.textContent).toContain("Check what I already know in “Evidence” of Digital forensics");
    fireEvent.click(screen.getByRole("button", { name: "Check a bit of everything" }));
    expect(document.body.textContent).toContain("Check a bit of everything for 1st midterm in Digital forensics");
  });

  it("labels each concept's last result", () => {
    wrap(
      <>
        <CheckChip check={overview.concepts[0]!.check} />
        <CheckChip check={overview.concepts[1]!.check} />
        <CheckChip check={null} />
      </>,
    );
    expect(screen.getByText("Know it").className).toContain("good");
    expect(screen.getByText("Partly").getAttribute("title")).toContain("counts as half");
  });

  it("keeps the practice limit on purpose when the exam paper asks for more", async () => {
    const fetch = mockFetch(() => ({ level: 4, label: "Analyze", set_by_learner: true, exam_profile_above: null, warning: null }));
    wrap(
      <PracticeLimitControl
        courseId="c1"
        limit={{ level: 4, label: "Analyze", set_by_learner: true, warning: "About 30 % of the questions are above 4 Analyze.", exam_profile_above: { target_id: "t1", target: "1st midterm", share: 0.3, confirmed: false } }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep my limit" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const [url, init] = fetch.mock.calls[0]!;
    expect(String(url)).toContain("/courses/c1/practice-limit");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ level: 4, keep_despite_exam: true });
  });
});

describe("I'm guessing", () => {
  it("marks a closed answer as a guess and sends it with the answer", async () => {
    const fetch = mockFetch(() => ({ saved_at: "2026-11-20T10:00:00Z" }));
    const quiz = {
      quiz_id: "qz",
      title: "Check first",
      status: "open",
      mode: "diagnostic",
      time_limit_minutes: null,
      opened_at: "2026-11-20T09:00:00Z",
      deadline: null,
      draft: {},
      draft_saved_at: null,
      items: [{ question_id: "q1", position: 1, type: "mcq", prompt: "Which hash?", options: [{ key: "A", text: "SHA-256" }, { key: "B", text: "CRC" }], points: 1, bloom_level: 2 }],
    } as unknown as QuizView;
    wrap(<QuizForm quiz={quiz} />);
    fireEvent.click(screen.getByLabelText(/SHA-256/));
    const guess = screen.getByRole("button", { name: "I'm guessing" });
    expect(guess.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(guess);
    expect(guess.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(fetch.mock.calls.some(([u]) => String(u).includes("/draft"))).toBe(true), { timeout: 3000 });
    const draft = fetch.mock.calls.find(([u]) => String(u).includes("/draft"))!;
    expect(JSON.parse(String(draft[1]?.body)).answers[0]).toMatchObject({ question_id: "q1", option: "A", guessing: true });
  });
});

describe("Unsure on an open answer (owner 2026-11-26)", () => {
  it("offers I don't know while the box is empty and Unsure once there is text, and sends the mark", async () => {
    const fetch = mockFetch(() => ({ saved_at: "2026-11-26T10:00:00Z" }));
    const quiz = {
      quiz_id: "qz",
      title: "Midterm practice",
      status: "open",
      mode: "practice",
      time_limit_minutes: null,
      opened_at: "2026-11-26T09:00:00Z",
      deadline: null,
      draft: {},
      draft_saved_at: null,
      items: [{ question_id: "q1", position: 1, type: "open", prompt: "Why hash evidence?", options: null, points: 2, bloom_level: 3 }],
    } as unknown as QuizView;
    wrap(<QuizForm quiz={quiz} />);
    expect(screen.getByLabelText("I don't know")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Unsure" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "To show it was not changed, I think." } });
    expect(screen.queryByLabelText("I don't know")).toBeNull();
    const unsure = screen.getByRole("button", { name: "Unsure" });
    expect(unsure.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(unsure);
    expect(unsure.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(fetch.mock.calls.some(([u]) => String(u).includes("/draft"))).toBe(true), { timeout: 3000 });
    const draft = fetch.mock.calls.filter(([u]) => String(u).includes("/draft")).at(-1)!;
    expect(JSON.parse(String(draft[1]?.body)).answers[0]).toMatchObject({ question_id: "q1", unsure: true });
    // an empty box brings I don't know back
    fireEvent.change(screen.getByRole("textbox"), { target: { value: " " } });
    expect(screen.getByLabelText("I don't know")).toBeTruthy();
  });
});

describe("grade help", () => {
  it("shows the meaning first, the number after it, and explains it behind a small ?", async () => {
    const { GradeChip } = await import("./components/ui");
    wrap(<GradeChip grade={3} status="final" />);
    expect(screen.getByText("Solid (3/4)")).toBeTruthy();
    const help = screen.getByRole("button", { name: "What does this grade mean?" });
    const tip = document.getElementById(help.getAttribute("aria-describedby")!)!;
    expect(tip.getAttribute("role")).toBe("tooltip");
    expect(tip.textContent).toContain("correct: you know it");
    expect(tip.textContent).toContain("it is not your points");
  });

  it("places the tip in the viewport on hover or focus, so a table's scroll box cannot cut it off", async () => {
    const { GradeChip } = await import("./components/ui");
    wrap(<GradeChip grade={3} status="final" />);
    const help = screen.getByRole("button", { name: "What does this grade mean?" });
    const tip = document.getElementById(help.getAttribute("aria-describedby")!)!;
    expect(tip.classList.contains("open")).toBe(false);
    const rect = (top: number) => () => ({ top, bottom: top + 18, left: 600, right: 618, width: 18, height: 18, x: 600, y: top, toJSON: () => ({}) });
    help.getBoundingClientRect = rect(400);
    fireEvent.mouseEnter(help.parentElement!);
    expect(tip.classList.contains("open")).toBe(true);
    expect(tip.classList.contains("below")).toBe(false);
    expect(tip.style.top).toBe("392px"); // above the "?"
    fireEvent.mouseLeave(help.parentElement!);
    expect(tip.classList.contains("open")).toBe(false);
    // near the top of the window it opens below; Escape closes it
    help.getBoundingClientRect = rect(40);
    fireEvent.focus(help);
    expect(tip.classList.contains("below")).toBe(true);
    expect(tip.style.top).toBe("66px");
    fireEvent.keyDown(help, { key: "Escape" });
    expect(tip.classList.contains("open")).toBe(false);
  });
});
