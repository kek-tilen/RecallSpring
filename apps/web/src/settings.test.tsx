import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SECTIONS, SettingsPage } from "./pages/Settings";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function show(entry: string) {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => new Response(JSON.stringify({ code: "not_found", message: "Not found." }), { status: 404, headers: { "Content-Type": "application/json" } }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const where = (title: string) => screen.getByRole("heading", { level: 3, name: title }).closest(".settings-section")?.id;

describe("Settings", () => {
  it("lists five sections on the left and shows one at a time", () => {
    show("/settings");
    const toc = screen.getByRole("navigation", { name: "Settings sections" });
    expect(within(toc).getByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    const links = within(toc).getAllByRole("link", { name: /^(?!\?$)/ });
    const sections = links.filter((a) => a.getAttribute("href")?.includes("#"));
    expect(sections.map((a) => a.textContent)).toEqual(["Study", "Assistants", "Data & backups", "Appearance", "Account & system"]);
    expect(sections.map((a) => a.getAttribute("href"))).toEqual(SECTIONS.map((s) => `/settings#${s.id}`));
    expect(sections[0]!.getAttribute("aria-current")).toBe("page");
    expect(sections[1]!.getAttribute("aria-current")).toBeNull();
    // only Study is shown
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["Study"]);
    expect(where("Study time")).toBe("study");
    expect(screen.queryByRole("heading", { level: 3, name: "Theme" })).toBeNull();
  });

  it("opens the section that holds a card an old link names", () => {
    show("/settings#chatgpt");
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["Assistants"]);
    expect(where("ChatGPT (preview)")).toBe("assistants");
    expect(where("Assistant connector")).toBe("assistants");
    expect(document.getElementById("chatgpt")).toBeTruthy();
    cleanup();
    show("/settings#service");
    expect(where("Profile")).toBe("account");
    expect(document.getElementById("service")).toBeTruthy();
  });

  it("keeps Backups, History and Recently deleted under Data & backups", () => {
    show("/settings#data");
    expect(where("Backups")).toBe("data");
    expect(where("History")).toBe("data");
    expect(where("Recently deleted")).toBe("data");
    expect(screen.getByRole("link", { name: "Open history" }).getAttribute("href")).toBe("/history");
    expect(document.getElementById("backups")).toBeTruthy();
  });
});
