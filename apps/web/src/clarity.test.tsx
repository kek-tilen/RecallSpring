import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ChatExplanationForm, ClarityPanel, wordDiff, type ExplanationVersion, type ExplanationView } from "./components/Clarity";

beforeAll(() => {
  Object.assign(HTMLDialogElement.prototype, {
    showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
    close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const version = (number: number, text: string, over: Partial<ExplanationVersion> = {}): ExplanationVersion => ({
  id: `v${number}`,
  number,
  text,
  words: text.trim().split(/\s+/).length,
  source: "learner",
  source_attempt_id: null,
  word_limit: null,
  created_at: "2026-11-23T10:00:00Z",
  deleted_at: null,
  feedback: [],
  ...over,
});

const view = (versions: ExplanationVersion[], deleted: ExplanationVersion[] = []): ExplanationView => ({
  concept: { id: "k1", term: "Glycolysis", course_id: "c1" },
  versions,
  deleted,
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("wordDiff", () => {
  it("marks added and removed words and keeps the rest", () => {
    const parts = wordDiff("Glycolysis happens in mitochondria.", "Glycolysis happens in the cytoplasm.");
    expect(parts!.filter((p) => p.kind === "removed").map((p) => p.text.trim())).toEqual(["mitochondria."]);
    expect(parts!.filter((p) => p.kind === "added").map((p) => p.text).join("")).toContain("cytoplasm.");
    expect(parts!.filter((p) => p.kind !== "removed").map((p) => p.text).join("")).toBe("Glycolysis happens in the cytoplasm.");
  });
});

describe("Concept-to-Clarity panel", () => {
  it("shows the newest version with its feedback, never a grade, and earlier versions folded", async () => {
    const v2 = version(2, "Glycolysis splits glucose into two pyruvate in the cytoplasm.", {
      feedback: [
        {
          id: "f1",
          grader: { name: "Claude", model: "claude-test" },
          correct: ["Two pyruvate"],
          missing: ["Net ATP"],
          wrong: [],
          evidence_refs: ["s1"],
          feedback: "Much clearer than version 1.",
          created_at: "2026-11-23T10:05:00Z",
        },
      ],
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, view([version(1, "Glycolysis splits glucose."), v2])));
    wrap(<ClarityPanel conceptId="k1" />);
    expect(await screen.findByText("Version 2 (newest)")).toBeTruthy();
    expect(screen.getByText("Much clearer than version 1.")).toBeTruthy();
    expect(screen.getByText("Net ATP")).toBeTruthy();
    expect(screen.getByText(/Claude · claude-test/).textContent).toContain("not a grade");
    expect(screen.queryByText(/\/4\)/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Changes from v1" }));
    expect(screen.getByLabelText("Changes from version 1 to version 2").querySelector("ins")).toBeTruthy();
    expect(screen.getByText(/Version 1 ·/)).toBeTruthy(); // the earlier one, folded
  });

  it("deletes only after confirming and can restore", async () => {
    const calls: { url: string; method: string }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (method === "DELETE") return json(200, view([], [version(1, "First try.", { deleted_at: "2026-11-23T11:00:00Z" })]));
      if (url.endsWith("/restore")) return json(200, view([version(1, "First try.")]));
      return json(200, view([version(1, "First try.")]));
    });
    wrap(<ClarityPanel conceptId="k1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete version 1" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete version" }));
    await waitFor(() => expect(screen.getByText("Recently deleted (1)")).toBeTruthy());
    expect(calls.find((c) => c.method === "DELETE")!.url).toContain("/explanation-versions/v1");
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(screen.getByText("Version 1 (newest)")).toBeTruthy());
  });

  it("saves the text exactly, with the same request id as idempotency key, and can start from the last version", async () => {
    let posted: { body: Record<string, string>; key: string | null } | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        posted = { body: JSON.parse(String(init.body)), key: new Headers(init.headers).get("Idempotency-Key") };
        return json(201, view([version(1, "Old."), version(2, posted.body.text!)]));
      }
      return json(200, view([version(1, "Old.")]));
    });
    wrap(<ClarityPanel conceptId="k1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Write a new version" }));
    fireEvent.click(screen.getByRole("button", { name: "Start from my last version" }));
    const box = screen.getByLabelText(/Explain Glycolysis in your own words/) as HTMLTextAreaElement;
    expect(box.value).toBe("Old.");
    expect(document.activeElement).toBe(box); // keep writing at the end of the copy
    expect((screen.getByRole("button", { name: "Save version" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Same as version 1/)).toBeTruthy();
    fireEvent.change(box, { target: { value: "  Old, but better.\n" } });
    expect(screen.getByText(/3 words/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save version" }));
    await waitFor(() => expect(screen.getByText("Version 2 (newest)")).toBeTruthy());
    expect(posted!.body.text).toBe("  Old, but better.\n");
    expect(posted!.body.source).toBe("learner");
    expect(posted!.key).toBe(posted!.body.client_request_id);
  });
});

describe("Chat explanation form", () => {
  it("tells the conversation which version was saved", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) =>
      init?.method === "POST" ? json(201, view([version(1, "Mine.", { source: "discuss" })])) : json(200, view([])),
    );
    const onSaved = vi.fn();
    wrap(<ChatExplanationForm conceptId="k1" source="discuss" onSaved={onSaved} />);
    fireEvent.change(await screen.findByLabelText(/Explain Glycolysis/), { target: { value: "Mine." } });
    fireEvent.click(screen.getByRole("button", { name: "Save version" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(1, "Glycolysis"));
    expect(screen.getByText(/version 1/)).toBeTruthy();
  });
});
