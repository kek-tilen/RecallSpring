import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { FocusTime, Recent, minutesText } from "./pages/Focus";
import type { FocusBlock, FocusSummary } from "./types";

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

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const BLOCK: FocusBlock = {
  id: "b1",
  client_session_id: "c1",
  course_id: null,
  course_title: null,
  started_at: "2026-11-22T14:57:00Z",
  ended_at: "2026-11-22T15:42:00Z",
  planned_minutes: 45,
  minutes: 45,
  completed: true,
  deleted_at: null,
};

const day = (date: string, minutes: number, sessions: number) => ({ date, minutes, sessions });
const SUMMARY: FocusSummary = {
  today: day("2026-11-22", 45, 1),
  days: [
    day("2026-11-16", 0, 0),
    day("2026-11-17", 120, 2),
    day("2026-11-18", 0, 0),
    day("2026-11-19", 0, 0),
    day("2026-11-20", 75, 2),
    day("2026-11-21", 1, 1),
    day("2026-11-22", 45, 1),
  ],
  week_minutes: 241,
  by_course: [{ course_id: null, course_title: null, minutes: 241, sessions: 6 }],
  recent: [BLOCK],
  removed: [],
  restore_days: 30,
};

function wrap(node: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("focus time", () => {
  it("writes minutes, hours and minutes, or whole hours", () => {
    expect(minutesText(45)).toBe("45 min");
    expect(minutesText(75)).toBe("1 h 15 min");
    expect(minutesText(120)).toBe("2 h");
  });

  it("each day shows its time on hover or keyboard focus", () => {
    const { container } = wrap(<FocusTime s={SUMMARY} />);
    const days = [...container.querySelectorAll(".focus-days li")];
    expect(days.every((d) => d.getAttribute("tabindex") === "0")).toBe(true);
    const tips = days.map((d) => d.querySelector(".focus-tip")?.textContent);
    expect(tips[1]).toBe("Tue 17 Nov2 h · 2 blocks");
    expect(tips[4]).toBe("Fri 20 Nov1 h 15 min · 2 blocks");
    expect(tips[0]).toBe("Mon 16 Nov0 min");
    expect(tips[6]).toBe("Today45 min · 1 block");
  });

  it("the course of a block can be set afterwards", async () => {
    const sent: { url: string; method?: string; body: unknown }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      sent.push({ url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url.includes("/courses")) return json(200, [{ id: "k1", title: "Digitalna tehnika" }]);
      if (url.includes("/focus-sessions/b1")) {
        return json(200, { ...SUMMARY, recent: [{ ...BLOCK, course_id: "k1", course_title: "Digitalna tehnika" }] });
      }
      return json(200, {});
    });
    wrap(<Recent s={SUMMARY} />);
    const select = (await screen.findByRole("combobox", { name: /Course for the block: 45 min · No course/ })) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("");
    fireEvent.change(select, { target: { value: "k1" } });
    await waitFor(() => expect(sent.some((r) => r.method === "PATCH")).toBe(true));
    const patch = sent.find((r) => r.method === "PATCH")!;
    expect(patch.url).toContain("/focus-sessions/b1");
    expect(patch.body).toEqual({ course_id: "k1" });
  });
});
