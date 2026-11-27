import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { opensHelp } from "./components/Layout";
import { STEPS } from "./guide";
import { GuidePage } from "./pages/Guide";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const key = (k: string, target: EventTarget | null = document.body, mods: Partial<KeyboardEvent> = {}) =>
  ({ key: k, ctrlKey: false, metaKey: false, altKey: false, target, ...mods }) as KeyboardEvent;

describe("Help", () => {
  it("opens with the ? key, but not while typing, in a dialog or with a modifier", () => {
    expect(opensHelp(key("?"))).toBe(true);
    expect(opensHelp(key("/"))).toBe(false);
    expect(opensHelp(key("?", document.body, { ctrlKey: true }))).toBe(false);
    const input = document.createElement("input");
    const area = document.createElement("textarea");
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    const inDialog = document.createElement("button");
    dialog.append(inDialog);
    document.body.append(input, area, dialog);
    expect(opensHelp(key("?", input))).toBe(false);
    expect(opensHelp(key("?", area))).toBe(false);
    expect(opensHelp(key("?", inDialog))).toBe(false);
    input.remove();
    area.remove();
    dialog.remove();
  });

  it("shows the Guide's steps as numbered sections", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(JSON.stringify({ code: "not_found", message: "Not found." }), { status: 404, headers: { "Content-Type": "application/json" } }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/guide"]}>
          <GuidePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const steps = STEPS.map((s) => screen.getByRole("heading", { level: 2, name: s.title }));
    expect(steps).toHaveLength(STEPS.length);
    expect(steps[0]!.closest("li")?.querySelector(".step-num")?.textContent).toBe("1");
  });
});
