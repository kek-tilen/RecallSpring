import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerPage, SummaryPage } from "./pages/Answer";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function show(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/answer/:questionId" element={<AnswerPage />} />
          <Route path="/summary" element={<SummaryPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const QUESTION = { id: "q1", course_id: "k1", bloom_level: 2, prompt: "Where does glycolysis happen?", rubric: null };

describe("answer page for assistants without forms", () => {
  it("keeps the draft, sends the exact text and reuses one request key on retry", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(200, QUESTION))
      .mockResolvedValueOnce(json(503, { code: "unavailable", message: "Try again." }))
      .mockResolvedValueOnce(json(201, { attempt_id: "a1", status: "saved_awaiting_evaluation", saved_at: "2026-11-21T20:00:00Z" }));
    show("/answer/q1?session=s1");
    const box = await screen.findByRole("textbox", { name: /your answer/i });
    const typed = "  V citoplazmi.\n";
    fireEvent.change(box, { target: { value: typed } });
    expect(JSON.parse(localStorage.getItem("rs-answer-draft:q1")!).text).toBe(typed);

    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await screen.findByText("Try again.");
    expect(localStorage.getItem("rs-answer-draft:q1")).not.toBeNull(); // nothing lost on failure
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await screen.findByText(/Your answer was saved/);

    const [first, second] = fetch.mock.calls.slice(1).map((c) => c[1] as RequestInit);
    const body = JSON.parse(second!.body as string);
    expect(body).toMatchObject({ question_id: "q1", session_id: "s1", answer_text: typed, kind: "answer" });
    expect((first!.headers as Record<string, string>)["Idempotency-Key"]).toBe(body.client_request_id);
    expect((second!.headers as Record<string, string>)["Idempotency-Key"]).toBe(body.client_request_id);
    expect(localStorage.getItem("rs-answer-draft:q1")).toBeNull();
  });

  it("says when a summary link is incomplete instead of guessing", () => {
    show("/summary?course=k1&title=Lecture");
    expect(screen.getByText(/This link is incomplete/)).toBeTruthy();
  });

  it("saves a summary only for topics of that course", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(200, [{ id: "c1", term: "Glycolysis" }, { id: "c2", term: "Krebs cycle" }]))
      .mockResolvedValueOnce(json(201, { note_id: "n1" }));
    show("/summary?course=k1&concepts=c1,zz&title=Lecture+3&covered=p.+2");
    expect(await screen.findByText("Glycolysis")).toBeTruthy();
    expect(screen.queryByText("Krebs cycle")).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: /your summary/i }), { target: { value: "Moje besede." } });
    fireEvent.click(screen.getByRole("button", { name: "Save summary" }));
    await waitFor(() => expect(screen.getByText(/saved as a note/)).toBeTruthy());
    const body = JSON.parse((fetch.mock.calls[1]![1] as RequestInit).body as string);
    expect(body).toMatchObject({ course_id: "k1", concept_ids: ["c1"], title: "Lecture 3", text: "Moje besede." });
  });
});
