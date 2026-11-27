import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PomodoroProvider } from "./components/Pomodoro";
import { FocusPage } from "./pages/Focus";

// Focus as drawn (UI direction, 2026-11-27).

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  delete (navigator as { wakeLock?: unknown }).wakeLock;
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const day = (date: string, minutes: number) => ({ date, minutes, sessions: minutes ? 1 : 0 });
const SUMMARY = {
  today: day("2026-11-27", 60),
  week_minutes: 165,
  days: [day("2026-11-21", 0), day("2026-11-22", 0), day("2026-11-23", 0), day("2026-11-24", 45), day("2026-11-25", 60), day("2026-11-26", 0), day("2026-11-27", 60)],
  by_course: [{ course_id: "k1", course_title: "Cell Biology", minutes: 120, sessions: 2 }, { course_id: "k2", course_title: "Linear Algebra", minutes: 45, sessions: 1 }],
  recent: [],
  removed: [],
  restore_days: 30,
};

function show() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/focus/summary") return json(SUMMARY);
    if (path === "/courses") return json([{ id: "k1", title: "Cell Biology", color: "blue", status: "active" }, { id: "k2", title: "Linear Algebra", color: "orange", status: "active" }]);
    return json({});
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PomodoroProvider>
          <FocusPage />
        </PomodoroProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Focus as drawn (2026-11-27)", () => {
  it("shows the six faces as a quiet picker, the week by day and course, and folds the rarer settings", async () => {
    show();
    const faces = screen.getByRole("radiogroup", { name: "Clock face" });
    expect(within(faces).getAllByRole("radio")).toHaveLength(6);
    fireEvent.click(within(faces).getByRole("radio", { name: /Ring/ }));
    expect(within(faces).getByRole("radio", { name: /Ring/ }).getAttribute("aria-checked")).toBe("true");
    const byCourse = await screen.findByRole("list", { name: "Focus time by course" });
    expect(byCourse.textContent).toContain("Cell Biology");
    expect(byCourse.textContent).toContain("2 h");
    expect(screen.getByText("2 h 45 min")).toBeTruthy();
    expect(screen.getByText("Timer settings").closest("details")?.open).toBe(false);
  });

  it("keeps the screen on while a block runs, where the browser can", async () => {
    show();
    expect((screen.getByRole("switch", { name: /Keep screen on/ }) as HTMLInputElement).disabled).toBe(true);
    cleanup();

    const release = vi.fn(async () => undefined);
    const request = vi.fn(async () => ({ release }));
    Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
    show();
    const sw = screen.getByRole("switch", { name: /Keep screen on/ }) as HTMLInputElement;
    fireEvent.click(sw);
    expect(sw.checked).toBe(true);
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(request).toHaveBeenCalledWith("screen"));
  });
});
