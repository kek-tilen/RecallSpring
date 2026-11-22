import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./api";
import { Highlighted, Meter } from "./components/ui";
import { gradeLabel, gradedBy } from "./format";
import { safeNext } from "./pages/Login";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

describe("api client", () => {
  it("sends the CSRF token and a fresh idempotency key on writes only", async () => {
    document.cookie = "rs_csrf=abc123; path=/";
    const fetch = mockFetch(200, { ok: true });
    await request("/notes", { json: { a: 1 } });
    await request("/notes", { json: { a: 1 } });
    await request("/dashboard");
    const [first, second, read] = fetch.mock.calls.map((c) => (c[1] as RequestInit).headers as Record<string, string>);
    expect(first!["X-CSRF-Token"]).toBe("abc123");
    expect(first!["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(first!["Idempotency-Key"]).not.toBe(second!["Idempotency-Key"]);
    expect(read!["X-CSRF-Token"]).toBeUndefined();
    expect(fetch.mock.calls[0]![0]).toBe("/api/v1/notes");
  });

  it("turns the error envelope into an ApiError", async () => {
    mockFetch(409, { code: "revision_conflict", message: "Both versions are kept.", request_id: "r-1", details: { x: 1 } });
    const error = await request("/notes/1", { method: "PATCH", json: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "revision_conflict", requestId: "r-1", message: "Both versions are kept." });
  });

  it("reports an unreachable server plainly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(request("/dashboard")).rejects.toMatchObject({ code: "offline" });
  });
});

describe("rendering learner and model text", () => {
  it("shows search highlights as text, never as markup", () => {
    const { container } = render(<Highlighted text={'before «<img src=x onerror=alert(1)>» after'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("mark")?.textContent).toBe("<img src=x onerror=alert(1)>");
  });

  it("keeps meter counts in the legend so colour is never the only cue", () => {
    render(
      <Meter
        label="Study progress"
        segments={[
          { label: "Not studied", value: 3, step: 0 },
          { label: "Known", value: 1, step: 3 },
        ]}
      />,
    );
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("Study progress. Not studied: 3, Known: 1");
    expect(screen.getByText("Not studied").parentElement?.textContent).toContain("3");
  });
});

describe("small helpers", () => {
  it("only redirects to paths inside the app after sign-in", () => {
    expect(safeNext("/courses/1?tab=notes")).toBe("/courses/1?tab=notes");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("/login")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });

  it("labels grades and graders honestly", () => {
    expect(gradeLabel(null)).toBe("Not graded");
    expect(gradeLabel(3)).toBe("Solid (3/4)");
    expect(gradedBy("ai")).toBe("Assistant");
    expect(gradedBy("ai", { name: "Codex", model: "gpt-5.5-codex" })).toBe("Codex · gpt-5.5-codex");
    expect(gradedBy("ai", { name: "Claude", model: null })).toBe("Claude");
    expect(gradedBy("deterministic")).toBe("RecallSpring (answer key)");
  });
});

describe("guide", () => {
  it("keeps the semester project template identical to docs/claude-projects.md", async () => {
    const { SEMESTER_TEMPLATE } = await import("./guide");
    // Read with Node (tests run in Node): the doc lives outside the app, so it is not imported as a module.
    const fsModule = "node:fs";
    const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as {
      readFileSync: (path: string, encoding: string) => string;
    };
    const cwd = (globalThis as unknown as { process: { cwd(): string } }).process.cwd(); // apps/web
    const doc = readFileSync(`${cwd}/../../docs/claude-projects.md`, "utf8").replace(/\r\n/g, "\n");
    expect(doc).toContain(SEMESTER_TEMPLATE);
  });

  it("offers every prompt in English and Slovenian with the same placeholders count", async () => {
    const { STEPS } = await import("./guide");
    for (const step of STEPS) {
      for (const p of step.prompts) {
        expect(p.en.length).toBeGreaterThan(0);
        expect(p.sl.length).toBeGreaterThan(0);
        expect((p.sl.match(/\[/g) ?? []).length).toBe((p.en.match(/\[/g) ?? []).length);
      }
    }
  });
});

describe("organisation helpers", () => {
  it("builds the university › faculty › semester path and survives a broken parent link", async () => {
    const { groupPath } = await import("./components/organise");
    const base = { position: 0, status: "active" as const, starts_on: null, ends_on: null, archived_at: null, courses: 0 };
    const groups = [
      { ...base, id: "u", parent_id: null, kind: "university" as const, name: "UM" },
      { ...base, id: "f", parent_id: "u", kind: "faculty" as const, name: "FERI" },
      { ...base, id: "s", parent_id: "f", kind: "semester" as const, name: "5. semester" },
      { ...base, id: "x", parent_id: "missing", kind: "semester" as const, name: "Orphan" },
    ];
    expect(groupPath(groups, "s")).toBe("UM › FERI › 5. semester");
    expect(groupPath(groups, "x")).toBe("Orphan");
    expect(groupPath(groups, null)).toBe("");
  });

  it("moves calendar dates without timezone drift", async () => {
    const { addDays, daysBetween } = await import("./format");
    expect(addDays("2026-03-28", 2)).toBe("2026-03-30"); // across the spring DST change
    expect(addDays("2026-12-30", 3)).toBe("2027-01-02");
    expect(daysBetween("2026-11-20", "2026-12-01")).toBe(11);
  });

  it("gives the assistant the simulation ID to grade", async () => {
    const { gradingPrompt } = await import("./components/QuizForm");
    expect(gradingPrompt({ title: "Simulation 1", quiz_id: "abc-123" })).toContain("(ID abc-123)");
  });
});

describe("source notes", () => {
  it("explains extraction notes in plain words and keeps unknown ones", async () => {
    const { parseNoteLabel } = await import("./format");
    expect(parseNoteLabel("pictures_not_extracted:1")).toBe(
      "1 picture inside the file is not part of the text. Your assistant can look at it on request.",
    );
    expect(parseNoteLabel("slides_without_text:2,5")).toBe(
      "Slides with little or no text: 2, 5. Your assistant can look at their pictures on request.",
    );
    expect(parseNoteLabel("hidden_sheets:1")).toBe("1 hidden sheet skipped.");
    expect(parseNoteLabel("truncated")).toBe("Only the beginning was extracted because the file is very large.");
    expect(parseNoteLabel("decoded_as:windows-1250")).toMatch(/^Read as Windows-1250/);
    expect(parseNoteLabel("includes_not_resolved:2")).toBe(
      "Includes 2 other files (\\input or \\include) that are not part of this one: upload them too.",
    );
    expect(parseNoteLabel("something_new:x")).toBe("something_new:x");
  });
});

describe("duplicate exams", () => {
  it("groups entries that point at each other once", async () => {
    const { duplicateGroups } = await import("./components/ExamCleanup");
    const base = {
      kind: "kolokvij", status: "upcoming", result: null, goal: null, scope_description: "", scope: [], notes: null,
      concepts_in_scope: 0, profile: null, days_left: 10, course_id: "c", course_title: "KV", course_color: null,
      course_status: "active", revision: 1, simulations: 0, due_date: "2026-11-30",
    };
    const a = { ...base, id: "a", name: "1. kolokvij", created_at: "2026-11-19T20:00:00Z", duplicates: ["b"] };
    const b = { ...base, id: "b", name: "Kolokvij", created_at: "2026-11-20T08:00:00Z", duplicates: ["a"] };
    const c = { ...base, id: "c2", name: "2. kolokvij", due_date: "2027-01-15", created_at: "2026-11-20T08:00:00Z", duplicates: [] };
    const groups = duplicateGroups([b, a, c]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.map((t) => t.id)).toEqual(["a", "b"]); // oldest first
  });
});
