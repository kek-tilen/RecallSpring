import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { launcher, reviewMessage } from "./components/StudyIn";
import { ConceptPage } from "./pages/Concept";
import { ReviewPage } from "./pages/Review";
import type { ConceptDetail, ReviewItem } from "./types";

// Owner notes 2026-11-26: a due concept leads to a review from memory with the learner's assistant, not only to
// Concept-to-Clarity (an explanation is not a review).

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const COURSES = [
  { id: "k1", title: "Security" },
  { id: "k2", title: "Digital Services" },
];
const due = (id: string, course: string, isDue = true): ReviewItem => ({
  concept_id: id,
  course_id: course,
  term: `Concept ${id}`,
  due_at: "2026-11-25T08:00:00Z",
  is_due: isDue,
  step: 1,
  evidence_count: 1,
  lapse_count: 0,
  last_review_at: "2026-11-22T08:00:00Z",
  due_reason: { message: "First practice recorded; first review is the next day." },
});
const CONCEPT: ConceptDetail = {
  id: "c9",
  course_id: "k2",
  term: "Digital convergence",
  definition_draft: "Joining devices, networks and services.",
  study_status: "studied",
  study_source: "learning_session",
  studied_at: "2026-11-22T08:00:00Z",
  band: "developing",
  difficulty: 3,
  difficulty_source: "default",
  review: {
    due_at: "2026-11-23T08:00:00Z",
    is_due: true,
    reason: "First practice recorded; first review is the next day.",
    evidence_count: 1,
    lapse_count: 0,
    last_review_at: "2026-11-22T08:00:00Z",
  } as ConceptDetail["review"],
  sections: [],
  attempts: [],
  note: "",
};

function serve(concept: ConceptDetail = CONCEPT) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/reviews/due") return json({ items: [due("a", "k1"), due("b", "k1"), due("c", "k2"), due("d", "k2", false)], note: "" });
    if (path === "/courses") return json(COURSES);
    if (path === `/concepts/${concept.id}/detail`) return json(concept);
    if (path === `/concepts/${concept.id}/explanation`)
      return json({ concept: { id: concept.id, term: concept.term, course_id: concept.course_id }, versions: [], deleted: [] });
    if (path === "/settings/assistants") return json({ items: [{ key: "codex", connected: true, tokens: 0, last_used_at: null }], in_use: null, chosen: null });
    if (path === "/auth/session") return json({ user: { assistant: null } });
    return json({ items: [], versions: [] });
  });
}

function Where() {
  const at = useLocation();
  return <p>at {at.pathname + at.search}</p>;
}

function show(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/concepts/:conceptId" element={<ConceptPage />} />
          <Route path="/chat/:id" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Review in… (owner 2026-11-26)", () => {
  it("writes a review message from memory for a course or one concept", () => {
    const course = { id: "k1", title: "Security" };
    expect(reviewMessage(course, {})).toBe(
      "Let's review what is due in Security (course_id k1): one question from memory per concept, then grade each.",
    );
    const one = reviewMessage(course, { concept: { id: "c1", term: "OSINT" }, due: true });
    expect(one).toContain("Let's review OSINT from Security (concept_id c1, course_id k1)");
    expect(reviewMessage(course, { concept: { id: "c1", term: "OSINT" }, due: false })).toMatch(/^Let's practise OSINT/);
  });

  it("starts a review per course on the Review page, only for what is due", async () => {
    serve();
    const open = vi.spyOn(launcher, "open").mockImplementation(() => {});
    show("/review");
    const card = (await screen.findByRole("heading", { name: "Review now" })).closest("section")!;
    expect(within(card).getByText("3 concepts due")).toBeTruthy();
    expect(within(card).getByText("Security")).toBeTruthy();
    expect(within(card).getAllByText(/due$/).map((n) => n.textContent)).toEqual(["3 concepts due", " · 2 concepts due", " · 1 concept due"]);
    fireEvent.click(await within(card).findByRole("button", { name: "Review Security in" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Codex/ }));
    await screen.findByRole("status");
    expect(decodeURIComponent(open.mock.calls[0]![0])).toContain("review what is due in Security (course_id k1)");
  });

  it("puts the review first on a due concept and folds Concept-to-Clarity as optional", async () => {
    serve();
    show("/concepts/c9");
    const card = (await screen.findByRole("heading", { name: "Review now" })).closest("section")!;
    expect(within(card).getByText(/one new question from memory/)).toBeTruthy();
    fireEvent.click(await within(card).findByRole("button", { name: "Review Digital convergence in" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy the start message only" }));
    expect((await screen.findByRole("status")).textContent).toMatch(/Start message copied|concept_id c9, course_id k2/);
    expect(screen.getByText("Optional · not a review")).toBeTruthy();
    const fold = screen.getByText("Explain it in your own words").closest("details")!;
    expect(fold.open).toBe(false);
    expect(within(fold).getByText(/does not change the review date/)).toBeTruthy();
  });

  it("offers practice before the date, and study first when not studied", async () => {
    serve({ ...CONCEPT, review: { ...CONCEPT.review!, is_due: false, due_at: "2026-12-30T08:00:00Z" } });
    show("/concepts/c9");
    expect(await screen.findByRole("heading", { name: "Practise" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Practise Digital convergence in" })).toBeTruthy();
    cleanup();
    serve({ ...CONCEPT, study_status: "not_studied", review: null });
    show("/concepts/c9");
    expect(await screen.findByRole("heading", { name: "Study first" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Study in…" })).toBeTruthy();
  });
});
