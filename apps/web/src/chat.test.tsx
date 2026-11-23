import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPage, whileWriting } from "./pages/Chat";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const lines = (events: unknown[]) =>
  new Response(events.map((e) => JSON.stringify(e)).join("\n") + "\n", { status: 200, headers: { "Content-Type": "application/x-ndjson" } });

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

function routeFetch(sent: { path: string; body: unknown }[], conv: typeof CONV = CONV, question: object = QUESTION) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    const body = init?.body instanceof FormData ? Object.fromEntries(init.body.entries()) : init?.body ? JSON.parse(String(init.body)) : null;
    if (method !== "GET") sent.push({ path, body });
    if (path === "/ai/chatgpt") return json(200, STATUS);
    if (path === "/ai/chatgpt/models") return json(200, [{ slug: "gpt-test", display_name: "GPT Test" }]);
    if (path === "/ai/chatgpt/conversations") {
      return json(200, { conversations: [{ id: "c1", title: "Quiz me", created_at: CONV.created_at, updated_at: CONV.updated_at, deleted_at: null, replies: 1 }], deleted: [], usage: { last_24_hours: CONV.totals, last_30_days: CONV.totals } });
    }
    if (path === "/ai/chatgpt/conversations/c1") return json(200, conv);
    if (path === "/sources" && method === "POST") {
      return json(201, { id: "s9", course_id: "k1", filename: "lecture3.pdf", kind: "pdf", category: "material", parse_state: "pending", section_count: 0 });
    }
    if (path === "/ai/chatgpt/conversations/c1/material") {
      const file = { id: "s9", course_id: "k1", filename: "lecture3.pdf", kind: "pdf", category: "material", has_text: false, reading: true };
      return json(200, { ...CONV, material: [file] });
    }
    if (path === "/questions/q1") return json(200, question);
    if (path === "/attempts/a1" && method === "GET") {
      return json(200, {
        id: "a1",
        question_id: "q1",
        kind: "answer",
        answer_text: "V citoplazmi.",
        answer_mode: "closed_notes",
        captured_via: "app_ui",
        status: "evaluated",
        submitted_at: "2026-11-21T20:01:00Z",
        assessments: [{ id: "s1", grade: 3, status: "final", confidence: "high", evidence_refs: [], strengths: [], gaps: [], feedback: "Right.", remediation: null, evaluator_kind: "ai", created_at: "2026-11-21T20:02:00Z" }],
        effective_assessment_id: "s1",
        photos: [],
      });
    }
    if (path === "/attempts") return json(201, { attempt_id: "a1", status: "saved_awaiting_evaluation", saved_at: "2026-11-21T20:01:00Z" });
    if (path === "/ai/chatgpt/messages/stream") {
      const done = { ...CONV, messages: [...CONV.messages, msg({ id: "m3", position: 3, role: "user", text: "next" })] };
      return lines([{ type: "saved", conversation_id: "c1" }, { type: "text", text: "next" }, { type: "done", conversation: done }]);
    }
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
    await waitFor(() => expect(sent.map((s) => s.path)).toEqual(["/attempts", "/ai/chatgpt/messages/stream"]));
    expect((sent[0]!.body as { answer_text: string }).answer_text).toBe("  V citoplazmi.\n");
    const message = sent[1]!.body as { message: string; recallspring: boolean; conversation_id: string };
    expect(message.message).toBe("[RecallSpring] I saved my answer to question q1 in the form. Please give me feedback.");
    expect(message.recallspring).toBe(true);
    expect(message.conversation_id).toBe("c1");
    // The conversation moved on (a newer turn), yet the sent form stays with the question and the exact answer.
    await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/Your answer was saved at .* and ChatGPT was told/));
    expect(screen.getByText("Where does glycolysis run?")).toBeTruthy();
    expect(screen.getByLabelText("Your answer").textContent).toBe("  V citoplazmi.\n");
    expect(screen.queryByText("(shown earlier)")).toBeNull();
  });

  it("shows the answer form of an earlier turn with the saved answer and its grade, not just a link", async () => {
    const later = {
      ...CONV,
      messages: [
        ...CONV.messages,
        msg({ id: "m3", position: 3, role: "user", text: "[RecallSpring] I saved my answer to question q1 in the form." }),
        msg({ id: "m4", position: 4, role: "assistant", text: "3/4, well done." }),
      ],
    };
    routeFetch([], later, { ...QUESTION, rubric: { expected_points: ["cytoplasm"] }, latest_attempt_id: "a1" });
    show();
    expect(await screen.findByLabelText("Your answer")).toBeTruthy();
    expect(screen.getByLabelText("Your answer").textContent).toBe("V citoplazmi.");
    expect(screen.getByText("Where does glycolysis run?")).toBeTruthy();
    expect(document.querySelector(".chat-form-saved .chip")?.textContent).toMatch(/^Solid \(3\/4\)/);
    expect(screen.queryByRole("textbox", { name: /your answer/i })).toBeNull();
    expect(screen.queryByText("(shown earlier)")).toBeNull();
  });

  it("an earlier form never answered stays a link", async () => {
    const later = { ...CONV, messages: [...CONV.messages, msg({ id: "m3", position: 3, role: "user", text: "Skip it" })] };
    routeFetch([], later, { ...QUESTION, latest_attempt_id: null });
    show();
    expect(await screen.findByText("(not answered yet)")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Answer form" }).getAttribute("href")).toBe("/answer/q1");
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
    await waitFor(() => expect(sent.some((s) => s.path === "/ai/chatgpt/messages/stream")).toBe(true));
    expect((sent.find((s) => s.path === "/ai/chatgpt/messages/stream")!.body as { recallspring: boolean }).recallspring).toBe(false);
  });

  it("shows the reply and RecallSpring's steps while ChatGPT writes, then the saved reply", async () => {
    const sent: { path: string; body: unknown }[] = [];
    const route = routeFetch(sent);
    const encoder = new TextEncoder();
    let push: (e: unknown) => void = () => {};
    let end: () => void = () => {};
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        push = (e) => controller.enqueue(encoder.encode(JSON.stringify(e) + "\n"));
        end = () => controller.close();
      },
    });
    const fallback = route.getMockImplementation()!;
    route.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/ai/chatgpt/messages/stream")) {
        sent.push({ path: "/ai/chatgpt/messages/stream", body: JSON.parse(String(init?.body)) });
        return new Response(body, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
      }
      return fallback(input, init);
    });
    show();
    await screen.findByRole("option", { name: "GPT Test" });
    fireEvent.change(screen.getByRole("textbox", { name: "Message to ChatGPT" }), { target: { value: "Explain glycolysis" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText(/waiting for ChatGPT/)).toBeTruthy();
    push({ type: "saved", conversation_id: "c1" });
    push({ type: "step", step: { call_id: "x", name: "get_course_outline", status: "ok", error_code: null, summary: "Read the course outline", writes: false, ms: 3 } });
    push({ type: "text", text: "Glycolysis splits " });
    push({ type: "text", text: "glucose." });
    expect(await screen.findByText("Glycolysis splits glucose.")).toBeTruthy();
    expect(screen.getByText("ChatGPT is writing…")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Messages" }).getAttribute("aria-busy")).toBe("true");
    const done = { ...CONV, messages: [...CONV.messages, msg({ id: "m3", position: 3, role: "user", text: "Explain glycolysis" }), msg({ id: "m4", position: 4, role: "assistant", text: "Glycolysis splits glucose into pyruvate." })] };
    push({ type: "done", conversation: done });
    end();
    expect(await screen.findByText("Glycolysis splits glucose into pyruvate.")).toBeTruthy();
    expect(screen.queryByText("ChatGPT is writing…")).toBeNull();
    expect(screen.getByRole("list", { name: "Messages" }).getAttribute("aria-busy")).toBeNull();
  });

  it("keeps a visual out of the reply until it is complete and checked", () => {
    const text = "Here:\n```recallspring-visual\n{\"type\": \"steps\"";
    expect(whileWriting(text)).toBe("Here:\n\n\n*Visual: shown when the reply is complete.*\n\n");
    expect(whileWriting(`${text}}\n\`\`\`\nAfter.`)).toContain("After.");
  });

  it("uploads a file from the composer into the library and this conversation", async () => {
    // jsdom has no modal dialogs: open and close them as attributes.
    Object.assign(HTMLDialogElement.prototype, {
      showModal(this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
      close(this: HTMLDialogElement) {
        this.removeAttribute("open");
      },
    });
    const sent: { path: string; body: unknown }[] = [];
    routeFetch(sent);
    const { baseElement } = show();
    fireEvent.click(await screen.findByRole("button", { name: "Upload files" }));
    await screen.findByRole("heading", { name: "Add files to this conversation" });
    expect(screen.queryByRole("combobox", { name: "Course" })).toBeNull(); // the conversation's course is used
    const input = baseElement.querySelector<HTMLInputElement>('input[type="file"]:not([webkitdirectory])')!;
    const file = new File(["%PDF-1.4"], "lecture3.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(sent.map((s) => s.path)).toEqual(["/sources", "/ai/chatgpt/conversations/c1/material"]));
    expect((sent[0]!.body as { course_id: string }).course_id).toBe("k1");
    expect(sent[1]!.body).toEqual({ source_ids: ["s9"] });
    expect(await screen.findByText(/RecallSpring is still reading lecture3\.pdf/)).toBeTruthy();
  });
});
