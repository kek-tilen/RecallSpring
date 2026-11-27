import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { addDays, todayIso } from "./format";
import { ExamsPage } from "./pages/Exams";

// Exams as drawn (UI direction, 2026-11-27): the timeline, the list and the selected exam's readiness.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const today = todayIso();
const target = (id: string, name: string, days: number, status = "upcoming", course = ["k1", "Cell Biology", "blue"]) => ({
  id,
  kind: "kolokvij",
  name,
  due_date: addDays(today, days),
  days_left: days,
  status,
  result: null,
  goal: null,
  scope_description: "",
  scope: [],
  notes: null,
  concepts_in_scope: 4,
  profile: null,
  course_id: course[0],
  course_title: course[1],
  course_color: course[2],
  course_status: "active",
  revision: 1,
  created_at: "2026-11-01T08:00:00Z",
  simulations: 0,
  duplicates: [],
});
const COUNTS = { not_studied: 1, weak: 1, not_practised: 0, developing: 1, solid: 1 };
const readiness = (id: string) => ({
  policy_version: "x",
  generated_at: "",
  target: { id, name: "Midterm 1", kind: "kolokvij", status: "upcoming", due_date: addDays(today, 10), days_left: 10, scope_description: "", course: { id: "k1", title: "Cell Biology", color: "blue" } },
  summary: { ...COUNTS, concepts: 4, due: 0, ready_percent: 25, remaining_minutes: 60 },
  capacity: { status: "ok", remaining_minutes: 60, available_minutes: 300, message: "About 1 h of work left; enough time." },
  groups: [{ kind: "source", id: "s1", title: "Lecture 3", pages: null, counts: COUNTS, concepts: [{ id: "c3", term: "Light reactions", state: "not_studied", band: "not_started", last_grade: null, lapses: 0, due: false, next_review: null, difficulty: 3, exam_weight: null, citations: ["Lecture 3 §1"], feedback: null }] }],
  weakest: [{ id: "c1", term: "Active transport", group: "Lecture 1", last_grade: 1, reason: "Last answer Fragile", gaps: ["Missing the 3 Na+ / 2 K+ ratio"], remediation: null, citations: ["Lecture 1 §3"] }],
  simulations: [],
  next_steps: [],
  note: "",
});

function serve() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/targets") return json([target("t1", "Midterm 1", 10), target("t2", "Exam", 24, "upcoming", ["k2", "Linear Algebra", "orange"]), target("t0", "Lab quiz", -8, "passed")]);
    if (path.startsWith("/targets/") && path.endsWith("/readiness")) return json(readiness(path.split("/")[2]!));
    if (path === "/courses") return json([{ id: "k1", title: "Cell Biology", status: "active" }, { id: "k2", title: "Linear Algebra", status: "active" }]);
    if (path === "/groups") return json([]);
    if (path === "/settings/assistants") return json({ items: [], in_use: null, chosen: null });
    if (path === "/targets/deleted") return json([]);
    return json({});
  });
}

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/exams"]}>
        <ExamsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Exams as drawn (2026-11-27)", () => {
  it("draws the timeline, lists what is coming and shows the first exam's weakest topics with Study in…", async () => {
    serve();
    show();
    const line = await screen.findByRole("img", { name: /^Timeline from/ });
    expect(line.getAttribute("aria-label")).toContain("Lab quiz, Cell Biology, passed on");
    expect(line.getAttribute("aria-label")).toContain("Midterm 1, Cell Biology, on");
    const coming = screen.getByRole("list", { name: "Coming up" });
    const rows = within(coming).getAllByRole("button");
    expect(rows.map((b) => b.getAttribute("aria-pressed"))).toEqual(["true", "false"]);
    expect(rows[0]!.textContent).toContain("Cell Biology");
    expect(rows[0]!.textContent).toContain("10 days");
    expect(await within(rows[0]!).findByText("On track")).toBeTruthy();

    const detail = screen.getByRole("region", { name: "Midterm 1" });
    const weak = await within(detail).findByRole("list", { name: "Weakest first" });
    const items = within(weak).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      expect.stringContaining("Missing the 3 Na+ / 2 K+ ratio · Lecture 1 §3"),
      expect.stringContaining("Not studied yet · Lecture 3 §1"),
    ]);
    expect(within(items[0]!).getByRole("button", { name: "Study in" })).toBeTruthy();
    expect(detail.textContent).toContain("1 not studied · 1 weak · 1 getting there · 1 solid");
    expect(within(detail).getByRole("link", { name: "Why this plan" }).getAttribute("href")).toBe("/exams/t1#why");
  });

  it("keeps passed exams folded under Behind you", async () => {
    serve();
    show();
    const behind = await screen.findByRole("button", { name: /Behind you/, expanded: false });
    expect(behind.textContent).toContain("1 passed");
    expect(screen.queryByRole("list", { name: "Behind you" })).toBeNull();
    fireEvent.click(behind);
    expect(within(screen.getByRole("list", { name: "Behind you" })).getByRole("button").textContent).toContain("passed");
  });
});
