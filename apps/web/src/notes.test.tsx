import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Markdown } from "./components/Markdown";
import { NotePage, NotesPage } from "./pages/Notes";

const PIC = "11111111-1111-4111-8111-111111111111";
const PDF = "22222222-2222-4222-8222-222222222222";
const GONE = "33333333-3333-4333-8333-333333333333";

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
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const NOTE = {
  id: "n1",
  course_id: "k1",
  title: "Cells",
  body: "Intro",
  revision: 1,
  saved_at: "2026-11-21T20:00:00Z",
  created_at: "2026-11-21T20:00:00Z",
  references: [],
  deleted_at: null,
};

const SOURCES = [
  { id: PDF, course_id: "k2", filename: "atp.pdf", kind: "pdf", folder: null, uploaded_at: "2026-11-20T10:00:00Z" },
  { id: PIC, course_id: "k1", filename: "cell.png", kind: "image", folder: "Drawings", uploaded_at: "2026-11-19T10:00:00Z" },
];

function routeFetch(sent: { method: string; path: string; body: unknown }[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (method !== "GET") sent.push({ method, path, body });
    if (path === "/courses") return json(200, [{ id: "k1", title: "Biology" }]);
    if (path === "/sources") return json(200, SOURCES);
    if (path === "/notes/n1" && method === "PATCH") {
      return json(200, { ...NOTE, ...body, revision: 2, references: [{ id: PIC, filename: "cell.png", kind: "image", course_id: "k1", missing: false }] });
    }
    if (path === "/notes/n1" && method === "DELETE") return json(200, { deleted: { ...NOTE, deleted_at: "2026-11-22T08:00:00Z" }, restorable_days: 30 });
    if (path === "/notes/n1") return json(200, NOTE);
    if (path === "/notes/n1/revisions") return json(200, []);
    if (path === "/notes/deleted") return json(200, [{ ...NOTE, deleted_at: "2026-11-22T08:00:00Z" }]);
    if (path === "/notes/n1/restore") return json(200, NOTE);
    if (path === "/notes") return json(200, []);
    return json(404, { code: "not_found", message: `unexpected ${method} ${path}` });
  });
}

function show(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/notes" element={<NotesPage />} />
          <Route path="/notes/:noteId" element={<NotePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("note references in Markdown", () => {
  it("shows pictures through RecallSpring, links other files and marks missing ones", () => {
    const refs = {
      [PIC]: { id: PIC, filename: "cell.png", kind: "image", course_id: "k1", missing: false },
      [PDF]: { id: PDF, filename: "atp.pdf", kind: "pdf", course_id: "k1", missing: false },
      [GONE]: { id: GONE, filename: null, kind: null, course_id: null, missing: true },
    };
    const text = `![a cell](source:${PIC})\n\nSee [the ATP sheet](source:${PDF}) and [old](source:${GONE}).`;
    const { container } = render(
      <MemoryRouter>
        <Markdown text={text} refs={refs} />
      </MemoryRouter>,
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe(`/api/v1/sources/${PIC}/file`);
    expect(img?.getAttribute("alt")).toBe("a cell");
    expect(screen.getByRole("link", { name: "the ATP sheet" }).getAttribute("href")).toBe(`/library/${PDF}`);
    expect(screen.getByText("old (missing file)")).toBeTruthy();
  });

  it("leaves source: text plain outside notes (chat replies)", () => {
    const { container } = render(
      <MemoryRouter>
        <Markdown text={`![x](source:${PIC})`} />
      </MemoryRouter>,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(`![x](source:${PIC})`);
  });
});

describe("Notes editor", () => {
  it("inserts a Library file at the cursor, previews it and saves the reference", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    routeFetch(sent);
    show("/notes/n1");
    const area = (await screen.findByLabelText("Note text")) as HTMLTextAreaElement;
    area.setSelectionRange(5, 5);
    fireEvent.click(screen.getByRole("button", { name: "Insert file" }));
    const insert = await screen.findByRole("button", { name: "Insert cell.png" });
    // The note's own course comes first.
    const buttons = screen.getAllByRole("button", { name: /^Insert .+\./ }).map((b) => b.getAttribute("aria-label"));
    expect(buttons).toEqual(["Insert cell.png", "Insert atp.pdf"]);
    fireEvent.click(insert);
    expect(area.value).toBe(`Intro\n![cell.png](source:${PIC})\n`); // a picture gets its own line
    expect(screen.getByText("Linked files:", { exact: false })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(document.querySelector(".note-preview img")?.getAttribute("src")).toBe(`/api/v1/sources/${PIC}/file`);

    fireEvent.click(screen.getByRole("button", { name: "Save now" }));
    await waitFor(() => expect(sent.some((s) => s.method === "PATCH")).toBe(true));
    expect((sent.find((s) => s.method === "PATCH")!.body as { body: string }).body).toBe(`Intro\n![cell.png](source:${PIC})\n`);
  });

  it("deletes a note only after confirmation", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    routeFetch(sent);
    show("/notes/n1");
    fireEvent.click(await screen.findByRole("button", { name: "Delete note" }));
    expect(await screen.findByText(/restore it under Notes/)).toBeTruthy();
    expect(sent).toEqual([]);
    const confirm = screen.getAllByRole("button", { name: "Delete note" }).at(-1)!;
    fireEvent.click(confirm);
    await waitFor(() => expect(sent).toEqual([{ method: "DELETE", path: "/notes/n1", body: null }]));
  });

  it("lists recently deleted notes with Restore", async () => {
    const sent: { method: string; path: string; body: unknown }[] = [];
    routeFetch(sent);
    show("/notes");
    fireEvent.click(await screen.findByRole("button", { name: "Restore Cells" }));
    await waitFor(() => expect(sent).toEqual([{ method: "POST", path: "/notes/n1/restore", body: null }]));
  });
});
