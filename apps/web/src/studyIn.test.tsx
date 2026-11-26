import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PLAN_MESSAGE, StudyIn, STUDY_IN_STORE, launcher, offeredAssistants, startMessage } from "./components/StudyIn";
import type { AssistantsStatus } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const item = (key: AssistantsStatus["items"][number]["key"], connected: boolean) => ({ key, connected, tokens: 0, last_used_at: null });
const COURSE = { id: "k1", title: "Biology 101" };

function serve(status: AssistantsStatus) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/settings/assistants") return json(status);
    if (path === "/auth/session") return json({ user: { assistant: null } });
    return new Response("{}", { status: 404 });
  });
}

function Where() {
  const at = useLocation();
  return <p>at {at.pathname + at.search}</p>;
}

function show(plan = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/courses"]}>
        <Routes>
          <Route path="/courses" element={plan ? <StudyIn /> : <StudyIn course={COURSE} />} />
          <Route path="/chat/:id" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Study in… (ADR-012 §3)", () => {
  it("offers the connected assistants, else the welcome choice or mix, else all", () => {
    const base = { in_use: null, chosen: null };
    expect(offeredAssistants({ ...base, items: [item("chatgpt", true), item("claude", true), item("codex", false)] }, null)).toEqual(["claude", "chatgpt"]);
    expect(offeredAssistants({ ...base, items: [item("claude", false)], mix: ["codex", "antigravity"] }, "mix")).toEqual(["codex", "antigravity"]);
    expect(offeredAssistants({ ...base, items: [] }, "claude")).toEqual(["claude"]);
    expect(offeredAssistants(undefined, null)).toEqual(["claude", "codex", "antigravity", "chatgpt"]);
    // a status without items (still loading or an older server) falls back the same way
    expect(offeredAssistants({} as AssistantsStatus, null)).toEqual(["claude", "codex", "antigravity", "chatgpt"]);
  });

  it("opens Claude Desktop with the start message ready, copies it and remembers the choice", async () => {
    serve({ items: [item("claude", true), item("chatgpt", true)], in_use: null, chosen: null });
    const open = vi.spyOn(launcher, "open").mockImplementation(() => {});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Study in…" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Claude Desktop" }));
    await waitFor(() => expect(open).toHaveBeenCalled());
    const text = startMessage(COURSE);
    expect(text).toBe("Let's study Biology 101 (course_id k1).");
    expect(open).toHaveBeenCalledWith(`claude://claude.ai/new?q=${encodeURIComponent(text)}`);
    expect(writeText).toHaveBeenCalledWith(text);
    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining("ready to send"));
    expect(localStorage.getItem(STUDY_IN_STORE)).toBe("claude");
    // the remembered choice is only marked: the button still opens the menu, nothing starts by itself
    open.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Study in…" }));
    expect(open).not.toHaveBeenCalled();
    expect(screen.getByRole("menuitem", { name: /Claude Desktop.*last used/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Chat (ChatGPT)" })).toBeTruthy();
  });

  it("Codex gets its documented prompt link; Chat opens a new conversation for the course", async () => {
    serve({ items: [item("codex", true), item("chatgpt", true)], in_use: null, chosen: null });
    const open = vi.spyOn(launcher, "open").mockImplementation(() => {});
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Study in…" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Codex" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(`codex://new?prompt=${encodeURIComponent(startMessage(COURSE))}`));

    fireEvent.click(screen.getByRole("button", { name: "Study in…" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Chat \(ChatGPT\)/ }));
    expect(await screen.findByText("at /chat/new?course=k1")).toBeTruthy();
    expect(localStorage.getItem(STUDY_IN_STORE)).toBe("chatgpt");
  });

  it("Antigravity and Copy only copy the message; nothing is opened", async () => {
    serve({ items: [item("antigravity", true)], in_use: "antigravity", chosen: null });
    const open = vi.spyOn(launcher, "open").mockImplementation(() => {});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    show();
    // even with one assistant the learner chooses from the menu
    fireEvent.click(screen.getByRole("button", { name: "Study in…" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Antigravity" }));
    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining("study folder in Antigravity"));
    fireEvent.click(screen.getByRole("button", { name: "Study in…" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy the start message only" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
    expect(open).not.toHaveBeenCalled();
  });
});

describe("Go through today's plan in… on Home (2026-11-26)", () => {
  it("opens the assistant with the planning message for all courses, never a course_id", async () => {
    serve({ items: [item("codex", true), item("claude", true), item("chatgpt", true)], in_use: null, chosen: null });
    const open = vi.spyOn(launcher, "open").mockImplementation(() => {});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    show(true);
    expect(PLAN_MESSAGE).not.toContain("course_id");
    const button = screen.getByRole("button", { name: "Go through today's plan in…" });
    expect(button.className).not.toContain("primary"); // Home's one primary button stays the next step
    fireEvent.click(button);
    expect(screen.getByRole("menu", { name: "Go through today's plan in" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Codex" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(`codex://new?prompt=${encodeURIComponent(PLAN_MESSAGE)}`));
    expect(writeText).toHaveBeenCalledWith(PLAN_MESSAGE);
    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining("Planning study folder"));

    fireEvent.click(screen.getByRole("button", { name: "Go through today's plan in…" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Claude Desktop" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(`claude://claude.ai/new?q=${encodeURIComponent(PLAN_MESSAGE)}`));

    // Chat: a new planning conversation (no course) with the message waiting in the box
    fireEvent.click(screen.getByRole("button", { name: "Go through today's plan in…" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Chat (ChatGPT)" }));
    expect(await screen.findByText(`at /chat/new?message=${encodeURIComponent(PLAN_MESSAGE)}`)).toBeTruthy();
  });
});
