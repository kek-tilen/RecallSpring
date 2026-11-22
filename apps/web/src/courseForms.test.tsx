import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { DeleteCourseDialog, NewCourseDialog, RecentlyDeletedCourses } from "./components/CourseForms";

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
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const COURSE = { id: "k1", title: "Digitalna forenzika", kind: "course" as const };
type Sent = { method: string; path: string; body: unknown };

function routeFetch(sent: Sent[], overrides: (s: Sent) => Response | null = () => null) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const s = { method: init?.method ?? "GET", path: url.pathname.replace("/api/v1", ""), body: init?.body ? JSON.parse(String(init.body)) : null };
    if (s.method !== "GET") sent.push(s);
    const o = overrides(s);
    if (o) return o;
    if (s.path === "/groups") return json(200, []);
    if (s.path === "/courses/k1/contents") {
      return json(200, {
        title: COURSE.title,
        counts: { materials: 3, folders: 0, concepts: 12, notes: 2, exams: 1, simulations: 1, questions: 9, answers: 4, conversations: 0, focus_blocks: 0 },
        restorable_days: 30,
      });
    }
    if (s.path === "/courses/k1" && s.method === "DELETE") return json(200, { deleted: COURSE, restorable_days: 30 });
    if (s.path === "/courses" && s.method === "POST") return json(201, { id: "new", title: s.body && (s.body as { title: string }).title });
    if (s.path === "/courses/new" && s.method === "PATCH") return json(200, { id: "new", title: "x" });
    if (s.path === "/courses/deleted") return json(200, [{ ...COURSE, color: null, deleted_at: "2026-11-22T09:00:00Z" }]);
    if (s.path === "/courses/k1/restore") return json(200, COURSE);
    return json(200, []);
  });
}

function show(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/courses/k1"]}>
        <Routes>
          <Route path="/courses/:id" element={ui} />
          <Route path="/courses" element={<p>Courses page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("deleting a course", () => {
  it("lists what goes and enables Delete only after I understand and the exact name", async () => {
    const sent: Sent[] = [];
    routeFetch(sent);
    show(<DeleteCourseDialog course={COURSE} open onClose={() => {}} />);
    expect(await screen.findByText("3 materials")).toBeTruthy();
    expect(screen.getByText("12 concepts")).toBeTruthy();
    expect(screen.getByText("4 answers with their grades")).toBeTruthy();
    expect(screen.queryByText(/Chat conversation/)).toBeNull(); // zero counts are left out
    const del = screen.getByRole("button", { name: "Delete course" }) as HTMLButtonElement;
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(del.disabled).toBe(true);
    expect(box.disabled).toBe(true);

    fireEvent.click(screen.getByLabelText(/I understand that everything in this course will be deleted/));
    fireEvent.change(box, { target: { value: "digitalna forenzika" } });
    expect(del.disabled).toBe(true);
    fireEvent.change(box, { target: { value: "Digitalna forenzika " } });
    expect(del.disabled).toBe(true);
    fireEvent.change(box, { target: { value: "Digitalna forenzika" } });
    expect(del.disabled).toBe(false);

    fireEvent.click(del);
    await screen.findByText("Courses page");
    expect(sent).toEqual([{ method: "DELETE", path: "/courses/k1", body: { confirm_title: "Digitalna forenzika" } }]);
  });

  it("unticking I understand disables Delete again", async () => {
    routeFetch([]);
    show(<DeleteCourseDialog course={COURSE} open onClose={() => {}} />);
    const box = screen.getByLabelText(/I understand/);
    fireEvent.click(box);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: COURSE.title } });
    fireEvent.click(box);
    expect((screen.getByRole("button", { name: "Delete course" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("restores a recently deleted course", async () => {
    const sent: Sent[] = [];
    routeFetch(sent);
    show(<RecentlyDeletedCourses />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore Digitalna forenzika" }));
    await waitFor(() => expect(sent).toEqual([{ method: "POST", path: "/courses/k1/restore", body: null }]));
  });
});

describe("new course", () => {
  it("creates the course and sets its colour afterwards", async () => {
    const sent: Sent[] = [];
    routeFetch(sent);
    show(<NewCourseDialog open onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("e.g. Digital forensics"), { target: { value: "  Kriptografija " } });
    fireEvent.click(screen.getByRole("radio", { name: "Red" }));
    fireEvent.click(screen.getByRole("button", { name: "Create course" }));
    await waitFor(() => expect(sent.length).toBe(2));
    expect(sent[0]).toEqual({
      method: "POST",
      path: "/courses",
      body: { title: "Kriptografija", kind: "course", long_term_retention: true, description: null },
    });
    expect(sent[1]).toEqual({ method: "PATCH", path: "/courses/new", body: { color: "red" } });
  });

  it("shows the server's message when the name is taken", async () => {
    routeFetch([], (s) =>
      s.path === "/courses" && s.method === "POST"
        ? json(409, { code: "course_exists", message: "A course with this name already exists." })
        : null,
    );
    show(<NewCourseDialog open onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("e.g. Digital forensics"), { target: { value: "Biology" } });
    fireEvent.click(screen.getByRole("button", { name: "Create course" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already exists");
  });
});
