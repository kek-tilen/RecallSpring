import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CoursePage } from "./pages/Course";
import { CoursesPage } from "./pages/Courses";

// Courses and a course as drawn (UI direction, 2026-11-27).

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const PROGRESS = { concepts: 8, study: { not_studied: 2, studied: 4, known: 2 }, bands: { not_started: 2, emerging: 2, developing: 2, reliable: 2 } };
const TARGET = { id: "t1", name: "Midterm 1", kind: "midterm", due_date: "2026-12-07", days_left: 10, status: "active", concepts_in_scope: 8, scope_description: "" };
const COURSE = { id: "k1", title: "Cell Biology", kind: "course", group_id: "s1", status: "active", description: null, color: "blue", focus_until: null };

function serve() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/overview/courses")
      return json([{ ...COURSE, group_path: [], active_target: TARGET, last_target: null, progress: PROGRESS, sources: 3, notes: 2, simulations: 1, due_reviews: 6 }]);
    if (path === "/groups") return json([{ id: "s1", parent_id: null, kind: "semester", name: "Winter semester 2026/27", position: 0, status: "active", starts_on: null, ends_on: null, archived_at: null, courses: 1 }]);
    if (path === "/courses/k1/overview")
      return json({ course: COURSE, active_target_id: "t1", targets: [TARGET], progress: PROGRESS, concepts: [], sources: [], notes: 0, quizzes: [], note: "" });
    if (path === "/reviews/due")
      return json({ items: [{ concept_id: "c1", course_id: "k1", term: "Osmosis", due_at: "2026-11-25T08:00:00Z", is_due: true, step: 1, evidence_count: 1, lapse_count: 0, last_review_at: null, due_reason: {} }], note: "" });
    if (path === "/library/archived") return json({ groups: [], courses: [], folders: [], sources: [] });
    if (path === "/settings/assistants") return json({ items: [], in_use: null, chosen: null });
    if (["/sources", "/notes", "/notes/deleted", "/courses/deleted", "/quizzes", "/attempts", "/courses", "/folders"].includes(path)) return json([]);
    return json({});
  });
}

function show(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/courses" element={<CoursesPage />} />
          <Route path="/courses/:courseId" element={<CoursePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Courses as drawn (2026-11-27)", () => {
  it("lists each course as one row: its exam, study bar, due count and Study in…", async () => {
    serve();
    show("/courses");
    const rows = await screen.findByRole("list", { name: "Courses in Winter semester 2026/27" });
    const row = within(rows).getByRole("listitem");
    expect(within(row).getByRole("link", { name: "Cell Biology" }).getAttribute("href")).toBe("/courses/k1");
    expect(row.textContent).toContain("Midterm 1 · in 10 days");
    expect(row.textContent).toContain("8 concepts");
    expect(row.textContent).toContain("6 due");
    expect(within(row).getByRole("img", { name: /Study progress/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ New course" })).toBeTruthy();
  });

  it("opens a course with four tabs; old links land on the tab that holds them now", async () => {
    serve();
    show("/courses/k1?tab=notes");
    const tabs = await screen.findByRole("navigation", { name: "Course sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["Concepts", "Material & notes", "Results", "Exams"]);
    expect(within(tabs).getByRole("link", { name: "Material & notes" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("heading", { name: "Material" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Notes" })).toBeTruthy();
    expect(await screen.findByText("Midterm 1 in 10 days · 0 concepts · 1 due")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Courses · Winter semester 2026\/27/ })).toBeTruthy();

    expect(screen.queryByRole("region", { name: "Course settings" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Course settings" }));
    expect(within(screen.getByRole("region", { name: "Course settings" })).getByRole("button", { name: "Edit course" })).toBeTruthy();
  });
});
