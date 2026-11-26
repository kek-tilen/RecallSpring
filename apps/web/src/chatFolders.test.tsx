import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ChatPage } from "./pages/Chat";

beforeAll(() => {
  // jsdom has no <dialog> methods.
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
const lines = (events: unknown[]) =>
  new Response(events.map((e) => JSON.stringify(e)).join("\n") + "\n", { status: 200, headers: { "Content-Type": "application/x-ndjson" } });

const STATUS = { connected: true, registered: true, unreadable: false, email: null, name: null, scopes: [], plan_usage: true, signed_in_at: null, unavailable_reason: null };
const TOTALS = { replies: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0 };
const AT = "2026-11-23T20:00:00Z";

const folder = (id: string, name: string, parent: string | null, n: number, extra: object = {}) => ({
  id,
  parent_id: parent,
  name,
  icon: "folder",
  color: null,
  course: null,
  pinned: false,
  conversations: n,
  ...extra,
});
const FOLDERS = [folder("f9", "Zoo", null, 0, { pinned: true }), folder("f1", "Biology", null, 1, { icon: "flask", color: "#0f6e56" }), folder("f2", "Midterm 1", "f1", 1)];
const summary = (id: string, title: string, folderId: string | null) => ({ id, title, folder_id: folderId, plain: false, created_at: AT, updated_at: AT, deleted_at: null, replies: 1 });
const LIST = {
  folders: FOLDERS,
  conversations: [summary("c1", "Osmosis", "f2"), summary("c2", "Cells", "f1"), summary("c3", "Loose one", null)],
  deleted: [],
  usage: { last_24_hours: TOTALS, last_30_days: TOTALS },
};
const conv = (id: string, title: string, folderId: string | null) => ({
  id,
  title,
  folder_id: folderId,
  plain: false,
  created_at: AT,
  updated_at: AT,
  deleted_at: null,
  material: [],
  totals: TOTALS,
  older_turns_not_sent: false,
  course: null,
  messages: [],
});

function serve(sent: { method: string; path: string; body: unknown }[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (method !== "GET") sent.push({ method, path, body });
    if (path === "/ai/chatgpt") return json(200, STATUS);
    if (path === "/ai/chatgpt/models") return json(200, [{ slug: "gpt-test", display_name: "GPT Test" }]);
    if (path === "/courses") return json(200, [{ id: "k1", title: "Biology 101" }]);
    if (path === "/ai/chatgpt/conversations") return json(200, LIST);
    if (path === "/ai/chatgpt/conversations/c1") return json(200, conv("c1", "Osmosis", "f2"));
    if (path === "/ai/chatgpt/conversations/c3") return json(200, conv("c3", "Loose one", null));
    if (path === "/ai/chatgpt/conversations/c1/folder") return json(200, LIST);
    if (path === "/ai/chatgpt/folders") return json(200, { ...LIST, folders: [...FOLDERS, folder("f5", body.name, null, 0)] });
    if (path === "/ai/chatgpt/ghost/stream") {
      const reply = { text: "Boo, here is the answer.", model: "gpt-test-2026-11-01", usage: { total_tokens: 9 }, visuals: [], steps: [], older_turns_not_sent: false };
      return lines([{ type: "text", text: "Boo" }, { type: "done", reply }]);
    }
    if (path === "/ai/chatgpt/ghost/keep") return json(200, conv("c7", "Kept", null));
    if (path === "/ai/chatgpt/conversations/c7") return json(200, conv("c7", "Kept", null));
    if (path === "/ai/chatgpt/messages/stream") {
      return lines([{ type: "saved", conversation_id: "c8" }, { type: "done", conversation: { ...conv("c8", "Plain", null), plain: true } }]);
    }
    if (path === "/ai/chatgpt/conversations/c8") return json(200, { ...conv("c8", "Plain", null), plain: true });
    return json(404, { code: "not_found", message: "Not found." });
  });
}

function show(at: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/chat/:conversationId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function write(text: string) {
  const box = await screen.findByLabelText("Message to ChatGPT");
  await waitFor(() => expect((box as HTMLTextAreaElement).disabled).toBe(false));
  await screen.findByRole("option", { name: "GPT Test" });
  fireEvent.change(box, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
}

describe("Chat folders (ADR-012 §4)", () => {
  it("lists folders pinned first, opens the one holding the current conversation and keeps loose ones apart", async () => {
    serve([]);
    show("/chat/c1");
    const tree = await screen.findByRole("list", { name: "Folders" });
    // pinned first, then by name
    expect(tree.textContent!.indexOf("Zoo")).toBeLessThan(tree.textContent!.indexOf("Biology"));
    // Biology and its subfolder open because the current conversation is in Midterm 1
    expect(within(tree).getByRole("button", { name: /Biology/, expanded: true })).toBeTruthy();
    expect(within(tree).getByRole("button", { name: /Midterm 1/, expanded: true })).toBeTruthy();
    expect(within(tree).getByText("Osmosis")).toBeTruthy();
    expect(within(tree).getByText("Cells")).toBeTruthy();
    // folder counts include the subfolders
    expect(within(tree).getByRole("button", { name: /Biology/, expanded: true }).textContent).toContain("2");
    expect(screen.getByRole("list", { name: "Conversations without a folder" }).textContent).toContain("Loose one");
    // Zoo stays closed until clicked
    const zoo = within(tree).getByRole("button", { name: /Zoo/, expanded: false });
    expect(zoo.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(zoo);
    expect(zoo.getAttribute("aria-expanded")).toBe("true");
    expect(JSON.parse(localStorage.getItem("rs.chat.folders.open") ?? "[]")).toEqual(["f9"]);
  });

  it("creates a folder with an icon and a colour", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    serve(sent);
    show("/chat/c3");
    fireEvent.click(await screen.findByRole("button", { name: "New folder" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Chemistry" } });
    fireEvent.click(screen.getByRole("radio", { name: "flask" }));
    fireEvent.click(screen.getByRole("radio", { name: "Teal" }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(sent.some((s) => s.path === "/ai/chatgpt/folders")).toBe(true));
    expect(sent.find((s) => s.path === "/ai/chatgpt/folders")!.body).toEqual({
      name: "Chemistry",
      icon: "flask",
      color: "#0f6e56",
      course_id: null,
      pinned: false,
      parent_id: null,
    });
  });

  it("moves a conversation with Move to…", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    serve(sent);
    show("/chat/c3");
    fireEvent.click(await screen.findByRole("button", { name: "Move to…" }));
    const dialog = screen.getByRole("dialog", { name: "Move to…" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Midterm 1/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(sent).toContainEqual({ method: "PUT", path: "/ai/chatgpt/conversations/c3/folder", body: { folder_id: "f2" } }));
  });
});

describe("Plain and Ghost chats (ADR-012 §5)", () => {
  it("Study in… → Chat preselects the course for a new conversation", async () => {
    serve([]);
    show("/chat/new?course=k1");
    await screen.findByRole("option", { name: "Study: Biology 101" });
    await waitFor(() => expect((screen.getByLabelText("What this chat is for") as HTMLSelectElement).value).toBe("k1"));
  });

  it("Go through today's plan in… → Chat waits with the message in a planning conversation, never sends it", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    serve(sent);
    show(`/chat/new?message=${encodeURIComponent("Let's go through today's plan.")}`);
    await screen.findByRole("option", { name: "Study: Biology 101" });
    expect((screen.getByLabelText("What this chat is for") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Message to ChatGPT") as HTMLTextAreaElement).value).toBe("Let's go through today's plan.");
    expect(sent.some((s) => s.path === "/ai/chatgpt/messages/stream")).toBe(false);
  });

  it("a plain chat has no RecallSpring switch and says so to the server", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    serve(sent);
    show("/chat/new");
    await screen.findByRole("option", { name: "Study: Biology 101" });
    expect(screen.getByRole("button", { name: /RecallSpring/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What this chat is for"), { target: { value: "plain" } });
    expect(screen.queryByRole("button", { name: /RecallSpring/ })).toBeNull();
    await write("Just talk");
    await waitFor(() => expect(sent.some((s) => s.path === "/ai/chatgpt/messages/stream")).toBe(true));
    const body = sent.find((s) => s.path === "/ai/chatgpt/messages/stream")!.body as Record<string, unknown>;
    expect(body.plain).toBe(true);
    expect(body.recallspring).toBe(false);
    expect(body.course_id).toBeNull();
  });

  it("a ghost chat sends the whole history, has no attachments, and Keep this chat saves it", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    serve(sent);
    show("/chat/new");
    const toggle = await screen.findByRole("button", { name: "Ghost" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(toggle.querySelector(".ghost-mark.on")).toBeTruthy(); // the ghost fills when on
    expect(screen.getByText(/lives only in this tab; RecallSpring does not save it/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Choose material" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Upload files" })).toBeNull();

    await write("First question");
    expect(await screen.findByText("Boo, here is the answer.")).toBeTruthy();
    await write("Second question");
    await waitFor(() => expect(sent.filter((s) => s.path === "/ai/chatgpt/ghost/stream")).toHaveLength(2));
    const second = sent.filter((s) => s.path === "/ai/chatgpt/ghost/stream")[1]!.body as { turns: { role: string; text: string }[] };
    expect(second.turns.map((t) => t.text)).toEqual(["First question", "Boo, here is the answer.", "Second question"]);
    expect(sent.some((s) => s.path === "/ai/chatgpt/messages/stream")).toBe(false); // nothing saved the normal way

    await screen.findAllByText("Boo, here is the answer.");
    fireEvent.click(screen.getByRole("button", { name: "Keep this chat" }));
    await waitFor(() => expect(sent.some((s) => s.path === "/ai/chatgpt/ghost/keep")).toBe(true));
    const kept = sent.find((s) => s.path === "/ai/chatgpt/ghost/keep")!.body as { turns: unknown[]; plain: boolean };
    expect(kept.turns).toHaveLength(4);
    expect(kept.plain).toBe(false);
  });
});
