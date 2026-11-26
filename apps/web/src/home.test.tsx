import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PomodoroProvider } from "./components/Pomodoro";
import { HomePage, greeting, todaySentence } from "./pages/Home";
import type { Dashboard, PlanItem, TargetCapacity } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try {
    localStorage.clear();
  } catch {
    /* none */
  }
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

const ITEM: PlanItem = {
  category: "Learn next",
  concept_id: "c1",
  term: "IEEE 754",
  course_id: "k1",
  course_title: "Computer Architecture",
  course_kind: "course",
  focus: false,
  why_selected: "Next in your material.",
  estimated_minutes: 25,
  target: "1st midterm",
  band: "emerging",
  study_status: "not_studied",
  difficulty: 3,
  difficulty_source: "default",
  sections: [],
};

const TARGET: TargetCapacity = {
  course_id: "k1",
  course_title: "Computer Architecture",
  target_id: "t1",
  target: "1st midterm",
  due_date: "2026-11-27",
  days_left: 4,
  concepts_in_scope: 12,
  remaining_minutes: 200,
  available_minutes: 400,
  status: "ok",
  message: "On track.",
};

function dashboard(over: Partial<Dashboard["plan"]> = {}, courses = 1): Dashboard {
  return {
    plan: {
      available_minutes: 60,
      planned_minutes: 45,
      maintenance_percent: 10,
      items: [ITEM, { ...ITEM, category: "Review due", concept_id: "c2", term: "Two's complement" }],
      targets: [TARGET],
      message: null,
      note: "",
      interests: null,
      focus: null,
      ...over,
    },
    attention: [{ kind: "backup", id: null, course_id: null, title: "Make a backup", text: null }],
    counts: { courses, sources: 1, concepts: 12, notes: 0, answers: 0, grades: 0, simulations: 0 },
    recent: [],
  };
}

function renderHome(d: Dashboard) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes("/dashboard")) return json(d);
    if (url.includes("/focus/summary"))
      return json({ today: { date: "2026-11-23", minutes: 0, sessions: 0 }, days: [], week_minutes: 50, by_course: [], recent: [], removed: [], restore_days: 30 });
    if (url.includes("/auth/session")) return json({ user: { id: "u", username: "u", timezone: "UTC", assistant: "chatgpt", greeting_name: "Tina" }, expires_at: "x" });
    if (/\/(courses|sources|course-groups)(\?|$)/.test(url)) return json([]);
    if (url.includes("/overview/week")) return json({ summary: ["2 answers this week."] });
    return json({});
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PomodoroProvider>
          <HomePage />
        </PomodoroProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("calm home (ADR-012, variant A)", () => {
  it("greets by time of day", () => {
    expect(greeting(8)).toBe("Good morning");
    expect(greeting(14)).toBe("Good afternoon");
    expect(greeting(21)).toBe("Good evening");
    expect(greeting(2)).toBe("Good evening");
    expect(greeting(9, " Tina ")).toBe("Good morning, Tina");
    expect(greeting(9, "  ")).toBe("Good morning");
  });

  it("says one sentence about the nearest date and today's work", () => {
    expect(todaySentence(dashboard())).toBe("1st midterm in Computer Architecture is in 4 days. Today's plan is about 45 minutes.");
    expect(todaySentence(dashboard({ targets: [{ ...TARGET, days_left: 1 }] }))).toContain("is tomorrow.");
    expect(todaySentence(dashboard({ targets: [], items: [] }))).toBe("Nothing is planned for today, so you're free to explore.");
  });

  it("shows one next step, the rest of today, the week and today in detail", async () => {
    renderHome(dashboard());
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toMatch(/^Good (morning|afternoon|evening), Tina$/);
    const next = screen.getByRole("region", { name: "Next step" });
    expect(next.textContent).toContain("Next: learn IEEE 754 · Computer Architecture");
    expect(next.querySelectorAll("a.btn")).toHaveLength(1);
    // today's plan across all courses can be taken to an assistant (2026-11-26)
    expect(screen.getByRole("button", { name: "Go through today's plan in…" }).getAttribute("aria-haspopup")).toBe("menu");
    expect(screen.getByRole("region", { name: "Then today" }).textContent).toContain("Two's complement");

    const week = screen.getByRole("region", { name: "This week" });
    expect(week.textContent).toContain("1st midterm · Computer Architecture");
    expect(week.textContent).toContain("Fri 27 Nov"); // short date, no year
    expect(week.textContent).toContain("Reviews today1");
    expect(week.querySelectorAll(".home-strip li")).toHaveLength(7);
    expect(await screen.findByText("50 min")).toBeTruthy();
    expect(screen.queryByText(/streak/i)).toBeNull();

    // today in detail is open by default; hiding it is remembered
    expect(screen.getByText("Today's plan")).toBeTruthy();
    expect(screen.getByText("Exams and midterms")).toBeTruthy();
    expect(screen.getByText("Make a backup")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText("Today's plan")).toBeNull();
    expect(localStorage.getItem("rs.home.detail")).toBe("hidden");
    expect(screen.getByRole("button", { name: "Show" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("links quietly to Why this plan for the exams today's plan works towards (ADR-013 §4)", async () => {
    const other = { ...TARGET, course_id: "k2", course_title: "Statistics", target_id: "t2", target: "Exam" };
    const items = [ITEM, { ...ITEM, concept_id: "c3", course_id: "k2", course_title: "Statistics", target: "Exam" }];
    renderHome(dashboard({ items: [...items, { ...ITEM, concept_id: "c4", target: null }], targets: [TARGET, other] }));
    const why = await screen.findByRole("link", { name: "Why this plan for 1st midterm in Computer Architecture" });
    expect(why.getAttribute("href")).toBe("/exams/t1#why");
    expect(screen.getByRole("link", { name: "1st midterm, Computer Architecture" }).getAttribute("href")).toBe("/exams/t1#why");
    expect(screen.getByRole("link", { name: "Exam, Statistics" }).getAttribute("href")).toBe("/exams/t2#why");
  });

  it("keeps the first-course hint visible before any course exists", async () => {
    renderHome(dashboard({ items: [], targets: [] }, 0));
    expect(await screen.findByText("Add your first course")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Next step" })).toBeNull();
  });

  it("counts a weak concept's next try before its exam as a review and marks quick checks (ADR-014)", async () => {
    const relearn: PlanItem = { ...ITEM, category: "Relearn", concept_id: "c4", term: "Bias", depth: "relearn", estimated_minutes: 10 };
    const quick: PlanItem = { ...ITEM, category: "Review due", concept_id: "c5", term: "Mantissa", depth: "quick", estimated_minutes: 3 };
    renderHome(dashboard({ items: [relearn, quick] }));
    const next = await screen.findByRole("region", { name: "Next step" });
    expect(next.textContent).toContain("Next: try again Bias");
    expect(next.querySelector("a.btn")?.textContent).toBe("Start reviews");
    expect(screen.getByRole("region", { name: "This week" }).textContent).toContain("Reviews today2");
    expect(screen.getByText("3 min · quick check")).toBeTruthy();
  });
});

describe("Today (UI direction, 2026-11-27)", () => {
  it("lists the exams ahead in the week panel, each opening its exam with its status", async () => {
    renderHome(dashboard());
    const week = await screen.findByRole("region", { name: "This week" });
    const exam = week.querySelector('.home-exams a[href="/exams/t1"]');
    expect(exam?.textContent).toBe("1st midterm · Computer Architecture");
    expect(week.querySelector(".home-exams")?.textContent).toContain("On track");
  });
});
