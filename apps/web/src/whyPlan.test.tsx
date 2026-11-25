import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WhyThisPlan } from "./pages/WhyPlan";
import type { PlanRationale, TargetProfile } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

const PROFILE: TargetProfile = {
  id: "p1",
  source_id: "s1",
  source: { id: "s1", filename: "kolokvij-2025.pdf", removed: false },
  item_types: [{ type: "scenario", share: 1 }],
  bloom_mix: { "3": 0.5, "4": 0.5 },
  topic_weights: [],
  example_items: [],
  notes: null,
  derived_by: "assistant",
  created_at: "2026-11-25T10:00:00Z",
  version: 2,
  topics: [],
  papers: [
    { source_id: "s1", label: "2025", total_points: 30, duration_minutes: 60, source: { id: "s1", filename: "kolokvij-2025.pdf", removed: false } },
    { source_id: null, label: "2024", total_points: 30, duration_minutes: null, source: null },
  ],
  unreadable: ["points of Q4"],
  confirmation: "unconfirmed",
  confirmed_at: null,
  confirmed_via: null,
};

const counts = { not_studied: 0, weak: 0, not_practised: 0, developing: 0, solid: 0 };

const RATIONALE: PlanRationale = {
  policy_version: "rationale-v1",
  generated_at: "2026-11-25T10:00:00Z",
  target: {
    id: "t1",
    name: "1. kolokvij",
    kind: "kolokvij",
    status: "active",
    due_date: "2026-12-20",
    days_left: 25,
    scope_description: "",
    course: { id: "k1", title: "Network security", color: null },
  },
  profile: PROFILE,
  topics: [
    {
      label: "Scanning",
      points: 24,
      share: 0.6,
      where: "Q2, p. 1",
      papers: ["2025", "2024"],
      weight: 2,
      not_in_material: false,
      unmapped: false,
      from_web: false,
      status: "in_progress",
      concepts: [
        { id: "c1", term: "Port scanning", state: "not_studied", due: false, in_scope: true },
        { id: "c2", term: "Ports", state: "not_practised", due: false, in_scope: true },
      ],
      counts: { ...counts, not_studied: 1, not_practised: 1 },
    },
    {
      label: "Scan options",
      points: 6,
      share: 0.15,
      where: "Q3",
      papers: ["2025"],
      weight: 0.5,
      not_in_material: false,
      unmapped: false,
      from_web: true,
      status: "not_studied",
      concepts: [{ id: "c3", term: "nmap -A", state: "not_studied", due: false, in_scope: false }],
      counts: { ...counts, not_studied: 1 },
    },
    {
      label: "Firewall rules",
      points: 4,
      share: 0.1,
      where: "Q6",
      papers: ["2025"],
      weight: 0.5,
      not_in_material: true,
      unmapped: false,
      from_web: false,
      status: "not_in_material",
      concepts: [],
      counts,
    },
  ],
  coverage: { basis: "points", studied_percent: 33, ready_percent: 0, solid_percent: 0, not_in_material_percent: 11 },
  bloom: { paper: { "3": 0.5, "4": 0.5 }, practised: {}, practice_limit: 5, paper_above_limit: 0 },
  today: {
    items: [
      {
        concept_id: "c1",
        term: "Port scanning",
        category: "Learn next",
        minutes: 29,
        topics: [{ label: "Scanning", points: 24, share: 0.6 }],
        why: "Next in your material; weighs more on your old papers.",
      },
    ],
    minutes: 29,
    other_courses_items: 2,
    note: null,
  },
  order_rules: ["New material keeps the order of the material whatever its weight."],
  fit: { days_left: 25, summary: { ...counts, concepts: 3, due: 0, ready_percent: 0, remaining_minutes: 90 }, capacity: null },
  not_on_paper: { count: 1, terms: ["Hashing"] },
  limits: [
    { code: "unconfirmed", message: "You have not confirmed the analysis yet: check it against the paper." },
    { code: "from_web", message: "Added from the web at your request, not from your course material: Scan options." },
  ],
  note: "Estimated from your answers, not a grade prediction.",
};

function renderWhy(r: PlanRationale, sent: { url: string; body: unknown }[] = []) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes("/profile/confirm")) {
      sent.push({ url, body: JSON.parse(String(init?.body)) });
      return json({});
    }
    if (url.includes("/rationale")) return json(r);
    return json({});
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/exams/t1#why"]}>
        <WhyThisPlan targetId="t1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Why this plan (ADR-013 §4)", () => {
  it("shows the papers, coverage by topic, today's work and the limits from the server", async () => {
    renderWhy(RATIONALE);
    await screen.findByRole("heading", { name: "Why this plan" });
    const section = document.getElementById("why")!;
    expect(section.textContent).toContain("Computed by RecallSpring");
    // the old papers: linked when RecallSpring has a copy
    expect((await screen.findByRole("link", { name: "2025" })).getAttribute("href")).toBe("/library/s1");
    expect(section.textContent).toContain("2024 · 30 points · no copy in RecallSpring");
    expect(section.textContent).toContain("33 % studied · 0 % getting there or solid · 0 % solid · 11 % not in your material");

    const table = within(screen.getByRole("table"));
    const rows = table.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.querySelector("td")?.textContent)).toEqual(["Scanning", "Scan optionsFrom the web", "Firewall rules"]);
    expect(rows[0]!.textContent).toContain("24 points");
    expect(rows[0]!.textContent).toContain("on 2 papers");
    expect(rows[1]!.textContent).toContain("outside this exam's scope");
    expect(rows[2]!.textContent).toContain("Not in your material");

    expect(section.textContent).toContain("On the paper: Scanning (24 points) — Next in your material; weighs more on your old papers.");
    expect(section.textContent).toContain("also has 2 items for other courses");
    expect(section.textContent).toContain("On the paper: Apply 50 % · Analyse 50 %");
    const limits = within(screen.getByRole("heading", { name: "What this cannot tell you" }).parentElement!);
    expect(limits.getAllByRole("listitem").map((li) => li.textContent)).toEqual(RATIONALE.limits.map((l) => l.message));
    expect(section.textContent).toContain("In this exam's scope but not on the old papers: Hashing.");
    expect(section.textContent).not.toContain("not a grade prediction"); // the page says it once, below
  });

  it("lets the learner confirm the latest analysis", async () => {
    const sent: { url: string; body: unknown }[] = [];
    renderWhy(RATIONALE, sent);
    expect(await screen.findByText(/Not confirmed yet/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "It matches the paper" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]!.url).toContain("/targets/t1/profile/confirm");
    expect(sent[0]!.body).toEqual({ profile_id: "p1" });
  });

  it("offers no confirmation once confirmed, and says when no paper was analysed", async () => {
    renderWhy({ ...RATIONALE, profile: { ...PROFILE, confirmation: "confirmed", confirmed_at: "2026-11-25T11:00:00Z", confirmed_via: "web" } });
    expect(await screen.findByText(/Confirmed by you on/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "It matches the paper" })).toBeNull();
    cleanup();
    vi.restoreAllMocks();
    renderWhy({ ...RATIONALE, profile: null, topics: [], coverage: null, bloom: { ...RATIONALE.bloom, paper: {} } });
    expect(await screen.findByText(/No old paper has been analysed/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
