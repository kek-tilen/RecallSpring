import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "./pages/Chat";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const STATUS = { connected: true, registered: true, unreadable: false, email: "l@example.com", name: null, scopes: [], plan_usage: true, signed_in_at: null, unavailable_reason: null };

const msg = (over: Record<string, unknown>) => ({
  position: 1,
  created_at: "2026-11-21T20:00:00Z",
  completed_at: "2026-11-21T20:00:05Z",
  model_requested: "gpt-test",
  model: null,
  response_id: null,
  account: null,
  usage: null,
  duration_ms: null,
  error_code: null,
  visuals: [],
  citations: {},
  context: [],
  tool_calls: [],
  ...over,
});

const CONV = {
  id: "c1",
  title: "Quiz me",
  created_at: "2026-11-21T20:00:00Z",
  updated_at: "2026-11-21T20:00:05Z",
  deleted_at: null,
  material: [],
  totals: { replies: 1, input_tokens: 100, output_tokens: 10, total_tokens: 110 },
  older_turns_not_sent: false,
  course: { id: "k1", title: "Biology 101" },
  messages: [
    msg({
      id: "m1",
      role: "user",
      text: "Quiz me",
      tool_calls: [
        { call_id: "a", name: "get_course_outline", status: "ok", error_code: null, summary: "Read the course outline", writes: false, ms: 5 },
        { call_id: "b", name: "create_questions", status: "ok", error_code: null, summary: "Saved 1 question", writes: true, ms: 9 },
        { call_id: "c", name: "open_answer_form", status: "ok", error_code: null, summary: "Showed an answer form", writes: false, ms: 2, form: { kind: "answer", question_id: "q1" } },
        { call_id: "d", name: "mark_concepts_known", status: "error", error_code: "not_found", summary: "Concept not found.", writes: true, ms: 1 },
      ],
    }),
    msg({ id: "m2", position: 2, role: "assistant", text: "Answer below.", model: "gpt-test-2026-11-01" }),
  ],
};

const QUESTION = { id: "q1", course_id: "k1", bloom_level: 1, prompt: "Where does glycolysis run?", rubric: null };

function routeFetch(sent: { path: string; body: unknown }[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    if (method !== "GET") sent.push({ path, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path === "/ai/chatgpt") return json(200, STATUS);
    if (path === "/ai/chatgpt/models") return json(200, [{ slug: "gpt-test", display_name: "GPT Test" }]);
    if (path === "/ai/chatgpt/conversations") {
      return json(200, { conversations: [{ id: "c1", title: "Quiz me", created_at: CONV.created_at, updated_at: CONV.updated_at, deleted_at: null, replies: 1 }], deleted: [], usage: { last_24_hours: CONV.totals, last_30_days: CONV.totals } });
    }
    if (path === "/ai/chatgpt/conversations/c1") return json(200, CONV);
    if (path === "/questions/q1") return json(200, QUESTION);
    if (path === "/attempts") return json(201, { attempt_id: "a1", status: "saved_awaiting_evaluation", saved_at: "2026-11-21T20:01:00Z" });
    if (path === "/ai/chatgpt/messages") return json(200, { ...CONV, messages: [...CONV.messages, msg({ id: "m3", position: 3, role: "user", text: "next" })] });
    return json(404, { code: "not_found", message: "Not found." });
  });
}

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/chat/c1"]}>
        <Routes>
          <Route path="/chat/:conversationId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ChatGPT using RecallSpring in Chat", () => {
  it("lists the steps, shows the answer form and tells ChatGPT once the exact answer is saved", async () => {
    const sent: { path: string; body: unknown }[] = [];
    routeFetch(sent);
    show();
    expect(await screen.findByText(/Used RecallSpring: 4 steps · 1 saved · 1 not done/)).toBeTruthy();
    expect(screen.getByText("Not done: Concept not found.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Biology 101" })).toBeTruthy();
    const box = await screen.findByRole("textbox", { name: /your answer/i });
    fireEvent.change(box, { target: { value: "  V citoplazmi.\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and send to ChatGPT" }));
    await waitFor(() => expect(sent.map((s) => s.path)).toEqual(["/attempts", "/ai/chatgpt/messages"]));
    expect((sent[0]!.body as { answer_text: string }).answer_text).toBe("  V citoplazmi.\n");
    const message = sent[1]!.body as { message: string; recallspring: boolean; conversation_id: string };
    expect(message.message).toBe("[RecallSpring] I saved my answer to question q1 in the form. Please give me feedback.");
    expect(message.recallspring).toBe(true);
    expect(message.conversation_id).toBe("c1");
  });

  it("lets the learner chat without RecallSpring and remembers it", async () => {
    const sent: { path: string; body: unknown }[] = [];
    routeFetch(sent);
    show();
    const pill = await screen.findByRole("button", { name: "RecallSpring" });
    expect(pill.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(pill);
    expect(pill.getAttribute("aria-pressed")).toBe("false");
    expect(localStorage.getItem("rs.chatgpt.recallspring")).toBe("off");
    await screen.findByRole("option", { name: "GPT Test" });
    fireEvent.change(screen.getByRole("textbox", { name: "Message to ChatGPT" }), { target: { value: "Just chat" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sent.some((s) => s.path === "/ai/chatgpt/messages")).toBe(true));
    expect((sent.find((s) => s.path === "/ai/chatgpt/messages")!.body as { recallspring: boolean }).recallspring).toBe(false);
  });
});
