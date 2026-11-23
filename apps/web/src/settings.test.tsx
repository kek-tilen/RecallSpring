import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SECTIONS, SettingsPage } from "./pages/Settings";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Settings", () => {
  it("is one page in five sections with contents that link to them", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(JSON.stringify({ code: "not_found", message: "Not found." }), { status: 404, headers: { "Content-Type": "application/json" } }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/settings"]}>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const toc = screen.getByRole("navigation", { name: "Settings sections" });
    const links = within(toc).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["Study", "Assistants", "Data & backups", "Appearance", "Account & system"]);
    expect(links.map((a) => a.getAttribute("href"))).toEqual(SECTIONS.map((s) => `#${s.id}`));
    expect(links[0]!.getAttribute("aria-current")).toBe("true");
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(SECTIONS.map((s) => s.title));
    // each card sits in its section, and old links (/settings#chatgpt, #profile, #service) still find their card
    const where = (title: string) => screen.getByRole("heading", { level: 3, name: title }).closest(".settings-section")?.id;
    expect(where("Study time")).toBe("study");
    expect(where("ChatGPT (preview)")).toBe("assistants");
    expect(where("Assistant connector")).toBe("assistants");
    expect(where("Backups")).toBe("data");
    expect(where("Theme")).toBe("appearance");
    expect(where("Profile")).toBe("account");
    for (const id of ["chatgpt", "connector", "backups", "profile", "service", "assistants"]) expect(document.getElementById(id)).toBeTruthy();
  });
});
