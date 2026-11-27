import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { COLLAPSED_STORE, CoursesPage } from "./pages/Courses";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const PROGRESS = { concepts: 1, study: { not_studied: 1, studied: 0, known: 0 }, bands: {} };
const course = (id: string, title: string, groupId: string | null, kind = "course") => ({
  id,
  title,
  kind,
  group_id: groupId,
  status: "active",
  description: null,
  color: null,
  group_path: [],
  active_target: null,
  last_target: null,
  progress: PROGRESS,
  sources: 0,
  notes: 0,
  simulations: 0,
  due_reviews: 0,
});
const group = (id: string, kind: string, name: string, parent: string | null) => ({
  id,
  parent_id: parent,
  kind,
  name,
  position: 0,
  status: "active",
  starts_on: null,
  ends_on: null,
  archived_at: null,
  courses: 0,
});

function serve(archived: { groups: unknown[]; courses: unknown[] }) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/overview/courses") return json([course("k1", "Biology 101", "s1"), course("k2", "Chemistry", "s1"), course("i1", "Spanish", null, "interest")]);
    if (path === "/groups") return json([group("u1", "university", "Example University", null), group("s1", "semester", "5th semester", "u1")]);
    if (path === "/library/archived") return json({ ...archived, folders: [], sources: [] });
    if (path === "/courses/deleted") return json([]);
    if (path === "/settings/assistants") return json({ items: [], in_use: null, chosen: null });
    return json({});
  });
}

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CoursesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Courses: sections open and close (owner 2026-11-23)", () => {
  it("closes a university with everything inside, says how many courses it holds and remembers it", async () => {
    serve({ groups: [], courses: [] });
    show();
    const uni = await screen.findByRole("button", { name: /Example University/, expanded: true });
    expect(screen.getByText("Biology 101")).toBeTruthy();
    fireEvent.click(uni);
    expect(uni.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Biology 101")).toBeNull();
    expect(screen.queryByText("5th semester")).toBeNull();
    expect(within(uni.closest("h2")!).getByText("2 courses")).toBeTruthy();
    expect(JSON.parse(localStorage.getItem(COLLAPSED_STORE)!)).toEqual(["u1"]);

    // a semester closes on its own; interests too
    fireEvent.click(uni);
    fireEvent.click(screen.getByRole("button", { name: /5th semester/, expanded: true }));
    expect(screen.queryByText("Chemistry")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Interests", expanded: true }));
    expect(screen.queryByText("Spanish")).toBeNull();
    expect(screen.getByText("1 interest")).toBeTruthy();
    cleanup();

    // remembered on the device
    show();
    expect(await screen.findByRole("button", { name: /5th semester/, expanded: false })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Interests", expanded: false })).toBeTruthy();
  });

  it("the archive closes only when something is in it", async () => {
    serve({ groups: [], courses: [] });
    show();
    expect(await screen.findByText("No archived semesters or courses.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Archived" })).toBeNull();
    cleanup();

    serve({
      groups: [{ ...group("s0", "semester", "4th semester", "u1"), status: "archived", path: "Example University / 4th semester" }],
      courses: [],
    });
    show();
    const archive = await screen.findByRole("button", { name: "Archived", expanded: true });
    expect(await screen.findByText("Example University / 4th semester")).toBeTruthy();
    fireEvent.click(archive);
    expect(screen.queryByText("Example University / 4th semester")).toBeNull();
    expect(screen.getByText("1 item")).toBeTruthy();
  });
});
