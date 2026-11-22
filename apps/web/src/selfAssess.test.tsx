import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SelfAssess, SelfCheckNote, suggestedGrade } from "./components/SelfAssess";
import { gradedBy } from "./format";
import type { AttemptDetail } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const VIEW = {
  attempt_id: "a1",
  available: true,
  reason: null,
  message: null,
  question: { id: "q1", prompt: "Convert -0.375 to IEEE 754.", bloom_level: 3 },
  expected_points: ["sign bit 1", "normalised 1.1 × 2^-2", "exponent 01111101"],
  sources: ["Številski sistemi in kodi, p. 47"],
  self_assessment: null,
};

function show(view: object = VIEW) {
  const sent: { path: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    if ((init?.method ?? "GET") !== "GET") {
      sent.push({ path, body: JSON.parse(String(init!.body)) });
      return json(200, { id: "a1", assessments: [] });
    }
    return json(200, view);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SelfAssess attemptId="a1" />
    </QueryClientProvider>,
  );
  return sent;
}

function mark(point: string, state: "Got it" | "Partly" | "Missed") {
  const group = screen.getAllByRole("group").find((g) => g.querySelector("legend")?.textContent?.endsWith(point))!;
  fireEvent.click(group.querySelector(`input[value="${{ "Got it": "met", Partly: "partial", Missed: "missing" }[state]}"]`)!);
}

describe("self-assessment", () => {
  it("suggests a grade from the expected points like the server", () => {
    expect(suggestedGrade(["met", "met"])).toBe(3);
    expect(suggestedGrade(["met", "partial"])).toBe(2);
    expect(suggestedGrade(["partial", "missing"])).toBe(1);
    expect(suggestedGrade(["met", "missing", "missing"])).toBe(1);
    expect(suggestedGrade(["missing"])).toBe(0);
  });

  it("marks every expected point, suggests a grade and saves it as the learner's own", async () => {
    const sent = show();
    expect(await screen.findByText(/Compare with: Številski sistemi in kodi, p\. 47/)).toBeTruthy();
    const save = screen.getByRole("button", { name: "Save my self-assessment" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    mark("sign bit 1", "Got it");
    mark("normalised 1.1 × 2^-2", "Missed");
    mark("exponent 01111101", "Partly");
    expect(document.body.textContent).toContain("Your grade (suggested: 2/4 · Partial)");
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("2");
    fireEvent.click(save);
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ path: "/attempts/a1/self-assessment", body: { points: ["met", "missing", "partial"], grade: 2, reason: null } });
  });

  it("4 Transfer needs a reason", async () => {
    show({ ...VIEW, expected_points: ["sign bit 1"] });
    await screen.findByRole("group", { name: "1. sign bit 1" });
    mark("sign bit 1", "Got it");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "4" } });
    const save = screen.getByRole("button", { name: "Save my self-assessment" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "I also showed the denormalised case." } });
    expect(save.disabled).toBe(false);
  });

  it("explains when it is not possible", async () => {
    show({ ...VIEW, available: false, reason: "no_expected_points", message: "This question has no expected points to compare with, so ask an assistant to grade it.", expected_points: [] });
    expect(await screen.findByText(/no expected points to compare with/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save my self-assessment" })).toBeNull();
  });

  it("notes when the assistant's check differs by two or more and names the grader", () => {
    const base = { feedback: "", evidence_refs: [], strengths: [], gaps: [], remediation: null, factuality_flags: [], provider: null, model: null, confidence: "medium", created_at: "2026-11-22T20:00:00Z" };
    const attempt = {
      id: "a1",
      assessments: [
        { ...base, id: "s", evaluator_kind: "self", status: "provisional", grade: 3 },
        { ...base, id: "x", evaluator_kind: "ai", status: "final", grade: 1 },
      ],
      effective_assessment_id: "x",
    } as unknown as AttemptDetail;
    const { container } = render(<SelfCheckNote attempt={attempt} />);
    expect(container.textContent).toContain("Your self-assessment was 3/4 · Solid; the check gave 1/4 · Fragile.");
    expect(gradedBy("self")).toBe("You (self-assessed)");
  });
});
