import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { TargetDialog } from "./components/TargetDialog";
import { FolderBrowser, descendants } from "./pages/Library";
import type { Folder, Target } from "./types";

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
  Element.prototype.scrollIntoView = () => {};
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

type Handler = (url: string, init?: RequestInit) => unknown;
function serve(handler: Handler) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    return json(handler(url, init) ?? {});
  });
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const folder = (id: string, name: string, parent: string | null, files: number): Folder => ({
  id,
  course_id: "k1",
  parent_id: parent,
  name,
  path: name,
  archived: false,
  hidden: false,
  archived_at: null,
  files,
  revision: 1,
  created_at: "2026-11-19T10:00:00Z",
});

const src = (id: string, filename: string, folderId: string | null, category = "material", folderName: string | null = null) => ({
  id,
  course_id: "k1",
  filename,
  kind: "pdf",
  category,
  folder_id: folderId,
  folder: folderName,
  archived: false,
  hidden: false,
  archived_at: null,
  duplicate_of_id: null,
  parse_state: "ready",
  page_count: 3,
  byte_size: 1000,
  uploaded_at: "2026-11-19T10:00:00Z",
});

describe("material counts include subfolders (owner 2026-11-23)", () => {
  const FOLDERS = [folder("f1", "Snov", null, 2), folder("f2", "Kolokviji", "f1", 1)];
  const SOURCES = [
    src("s1", "Predavanje 1.pdf", "f1"),
    src("s2", "Predavanje 2.pdf", "f1"),
    src("s3", "kolokvij-2025.pdf", "f2", "past_paper", "Snov / Kolokviji"),
  ];

  it("finds folders at any depth", () => {
    expect(descendants(FOLDERS, "f1")).toEqual(["f2"]);
  });

  it("counts everything below and shows a filtered kind from every folder", async () => {
    serve((url) => (url.includes("/folders") ? FOLDERS : url.includes("/sources") ? SOURCES : {}));
    wrap(<FolderBrowser courseId="k1" folderId={null} href={(id) => `?folder=${id ?? ""}`} />);
    expect(await screen.findByRole("button", { name: "All 3" })).toBeTruthy();
    expect(screen.getByText("All 3 files are in the folders above.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Past papers 1" }));
    expect(screen.getByText("kolokvij-2025.pdf")).toBeTruthy();
    expect(screen.getByText("Snov / Kolokviji")).toBeTruthy(); // its folder is shown
  });
});

describe("ending the focus after the last exam (owner 2026-11-23)", () => {
  const TARGET = {
    id: "t1",
    kind: "kolokvij",
    name: "1. Kolokvij",
    due_date: "2026-11-23",
    days_left: 0,
    status: "upcoming",
    result: null,
    goal: null,
    scope_description: "Vse",
    scope: [],
    notes: null,
    concepts_in_scope: 3,
    profile: null,
  } as Target;

  function setup(otherUpcoming: boolean) {
    const sent: string[] = [];
    serve((url, init) => {
      if (init?.method && init.method !== "GET") sent.push(`${init.method} ${url.replace(/^.*\/api\/v1/, "")}`);
      if (url.includes("/settings/study"))
        return { focus: { course_id: "k1", course_title: "Biology 101", kind: "course", until: "2026-11-23" } };
      if (url.endsWith("/targets"))
        return otherUpcoming ? [{ ...TARGET, id: "t2", course_id: "k1", status: "upcoming", days_left: 20 }] : [];
      if (url.includes("/courses")) return [];
      if (url.includes("/sources")) return [];
      return {};
    });
    const onClose = vi.fn();
    wrap(<TargetDialog target={{ ...TARGET, course_id: "k1" }} courseId="k1" open onClose={onClose} />);
    return { sent, onClose };
  }

  async function markPassed() {
    await screen.findByRole("option", { name: "Passed" });
    await new Promise((r) => setTimeout(r, 20)); // focus and exams loaded
    fireEvent.change(screen.getByDisplayValue("Upcoming"), { target: { value: "passed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
  }

  it("asks when the focused course has no other exam coming, and ends the focus", async () => {
    const { sent, onClose } = setup(false);
    await markPassed();
    expect(await screen.findByText(/1. Kolokvij is passed and this course has no other exam/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "End focus" }));
    await waitFor(() => expect(sent).toContain("PUT /settings/focus"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("does not ask while another exam of the course is coming", async () => {
    const { sent, onClose } = setup(true);
    await markPassed();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "End focus" })).toBeNull();
    expect(sent).toEqual(["PATCH /targets/t1"]);
  });
});

describe("Before this exam (ADR-014 §4)", () => {
  const TARGET = {
    id: "t1",
    kind: "kolokvij",
    name: "1. Kolokvij",
    due_date: "2026-12-12",
    days_left: 16,
    status: "upcoming",
    result: null,
    goal: "exam_only",
    before_exam: { choice: "extra_review", label: "An extra review before the exam", goal_default: "extra_review", chosen: false },
    scope_description: "Vse",
    scope: [],
    notes: null,
    concepts_in_scope: 3,
    profile: null,
  } as Target;

  function setup(target: Target = TARGET) {
    const bodies: unknown[] = [];
    serve((url, init) => {
      if (init?.method === "PATCH") bodies.push(JSON.parse(String(init.body)));
      if (url.endsWith("/targets") || url.includes("/courses") || url.includes("/sources")) return [];
      return {};
    });
    const onClose = vi.fn();
    wrap(<TargetDialog target={{ ...target, course_id: "k1" }} courseId="k1" open onClose={onClose} />);
    return { bodies, onClose };
  }
  const radio = (name: RegExp) => screen.findByRole("radio", { name }) as Promise<HTMLInputElement>;

  it("starts at the goal's default and warns about intense", async () => {
    setup();
    const extra = await radio(/An extra review before the exam/);
    expect(extra.checked).toBe(true);
    expect(extra.closest("label")!.textContent).toContain("An extra review before the exam (default)");
    expect((await radio(/Intense/)).closest("label")!.textContent).not.toContain("(default)");
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(await radio(/Intense/));
    expect(screen.getByRole("status").textContent).toContain("noticeably more reviews");
  });

  it("saves the learner's choice, and the goal's default as no choice", async () => {
    const first = setup();
    fireEvent.click(await radio(/Intense/));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(first.onClose).toHaveBeenCalled());
    expect(first.bodies).toEqual([{ before_exam: "intense" }]);
    cleanup();

    const chosen = { ...TARGET, before_exam: { ...TARGET.before_exam!, choice: "intense", label: "Intense", chosen: true } } as Target;
    const second = setup(chosen);
    fireEvent.click(await radio(/An extra review before the exam/));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(second.onClose).toHaveBeenCalled());
    expect(second.bodies).toEqual([{ before_exam: "default" }]);
  });
});

describe("Photos: select all (owner 2026-11-25)", () => {
  const img = (id: string, filename: string) => ({ ...src(id, filename, null), kind: "image", page_count: null });
  const SOURCES = [src("s1", "Lecture 1.pdf", null), img("i1", "4.png"), img("i2", "5.png")];

  it("selects every photo at once and clears them again", async () => {
    serve((url) => (url.includes("/folders") ? [] : url.includes("/sources") ? SOURCES : {}));
    wrap(<FolderBrowser courseId="k1" folderId={null} href={(id) => `?folder=${id ?? ""}`} />);
    fireEvent.click(await screen.findByRole("button", { name: "Select all" }));
    const box = (name: string) => screen.getByRole("checkbox", { name: `Select ${name}` }) as HTMLInputElement;
    expect([box("4.png").checked, box("5.png").checked, box("Lecture 1.pdf").checked]).toEqual([true, true, false]);
    expect(screen.getByText("2 items selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Deselect all" }));
    expect([box("4.png").checked, box("5.png").checked]).toEqual([false, false]);
  });

  it("selects all material from the table header, apart from the photos", async () => {
    const PDFS = [src("s1", "Lecture 1.pdf", null), src("s2", "Lecture 2.pdf", null), img("i1", "4.png")];
    serve((url) => (url.includes("/folders") ? [] : url.includes("/sources") ? PDFS : {}));
    wrap(<FolderBrowser courseId="k1" folderId={null} href={(id) => `?folder=${id ?? ""}`} />);
    const all = (await screen.findByRole("checkbox", { name: "Select all material" })) as HTMLInputElement;
    fireEvent.click(all);
    const box = (name: string) => screen.getByRole("checkbox", { name: `Select ${name}` }) as HTMLInputElement;
    expect([box("Lecture 1.pdf").checked, box("Lecture 2.pdf").checked, box("4.png").checked, all.checked]).toEqual([true, true, false, true]);
    fireEvent.click(all);
    expect([box("Lecture 1.pdf").checked, box("Lecture 2.pdf").checked]).toEqual([false, false]);
  });
});
