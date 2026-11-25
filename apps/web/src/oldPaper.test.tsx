import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OldPaper, ProfileConfirmation } from "./pages/Course";
import type { TargetProfile } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

const PROFILE: TargetProfile = {
  id: "p1",
  source_id: null,
  source: null,
  item_types: [{ type: "mcq", share: 1 }],
  bloom_mix: {},
  topic_weights: [],
  example_items: [],
  notes: null,
  derived_by: "assistant",
  created_at: "2026-11-19T22:30:00Z",
};

const source = (id: string, filename: string, category: string) => ({ id, filename, category, hidden: false });

function renderPaper(profile: TargetProfile, sent: { url: string; body: unknown }[] = []) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes("/sources")) return json([source("s1", "kolokvij-2025.pdf", "past_paper"), source("s2", "Lecture.pdf", "material")]);
    if (url.includes("/profile/source")) {
      sent.push({ url, body: JSON.parse(String(init?.body)) });
      return json({});
    }
    return json({});
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <OldPaper targetId="t1" courseId="k1" profile={profile} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("the old paper behind an exam-style analysis", () => {
  it("says when RecallSpring has no copy, offers to add it and links a past paper", async () => {
    const sent: { url: string; body: unknown }[] = [];
    renderPaper(PROFILE, sent);
    expect(screen.getByText(/only shared in a chat, so RecallSpring has no copy/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add old paper" }).getAttribute("href")).toBe("/courses/k1?tab=materials&add=past_paper");

    const select = (await screen.findByRole("combobox")) as HTMLSelectElement;
    expect(screen.getByRole("group", { name: "Past papers" }).textContent).toContain("kolokvij-2025.pdf");
    fireEvent.change(select, { target: { value: "s1" } });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]!.url).toContain("/targets/t1/profile/source");
    expect(sent[0]!.body).toEqual({ source_id: "s1" });
  });

  it("opens the linked paper", () => {
    renderPaper({ ...PROFILE, source_id: "s1", source: { id: "s1", filename: "kolokvij-2025.pdf", removed: false } });
    expect(screen.getByRole("link", { name: "kolokvij-2025.pdf" }).getAttribute("href")).toBe("/library/s1");
    expect(screen.getByRole("button", { name: "Unlink" })).toBeTruthy();
  });
});

describe("Exam profile v2 (ADR-013)", () => {
  it("says whether the learner confirmed the analysis", () => {
    const v2 = { ...PROFILE, version: 2 };
    render(<ProfileConfirmation profile={{ ...v2, confirmation: "unconfirmed" }} />);
    expect(screen.getByText(/Not confirmed yet/)).toBeTruthy();
    cleanup();
    render(<ProfileConfirmation profile={{ ...v2, confirmation: "confirmed", confirmed_at: "2026-11-25T10:00:00Z" }} />);
    expect(screen.getByText(/Confirmed by you on/)).toBeTruthy();
    cleanup();
    render(<ProfileConfirmation profile={{ ...PROFILE, confirmation: "before_confirmation" }} />);
    expect(screen.getByText(/analyse the paper again/)).toBeTruthy();
  });
});
