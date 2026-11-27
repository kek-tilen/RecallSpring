import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("chooses where backups go after checking the folder", async () => {
    const status = {
      enabled: true,
      location: "C:\RS\local-data\backups",
      location_source: "default",
      server_location: "C:\RS\local-data\backups",
      folder_from_web: true,
      sync: null,
      can_change: true,
      same_disk_as_storage: true,
      interval_hours: 24,
      keep_daily: 7,
      keep_weekly: 4,
      last_attempt_at: null,
      last_success_at: null,
      last_error: null,
      last: null,
      next_due: "now",
      snapshots: [],
      disk_bytes: 0,
      tools: "pg_dump",
    };
    const target = "D:\Dropbox\RecallSpring backups";
    const calls: { method: string; url: string; body: unknown }[] = [];
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url.includes("/settings/backup/folder/check"))
        return json({
          path: target,
          ok: true,
          sync: "Dropbox",
          checks: [
            { id: "write", level: "ok", text: "RecallSpring can make this folder · 412 GB free" },
            { id: "disk", level: "ok", text: "Another disk than your uploads, so a broken disk does not take both" },
            { id: "sync", level: "ok", text: "Looks like a Dropbox folder: copies leave this computer when Dropbox syncs" },
          ],
        });
      if (url.includes("/settings/backup/folder")) return json({ ...status, location: target, location_source: "settings", sync: "Dropbox", same_disk_as_storage: false });
      if (url.includes("/settings/backup")) return json(status);
      return new Response(JSON.stringify({ code: "not_found", message: "Not found." }), { status: 404, headers: { "Content-Type": "application/json" } });
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/settings#data"]}>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    const form = screen.getByRole("form", { name: "Where backups go" });
    const use = within(form).getByRole("button", { name: "Use this folder" }) as HTMLButtonElement;
    expect(use.disabled).toBe(true); // not before a check
    fireEvent.change(within(form).getByRole("textbox"), { target: { value: target } });
    fireEvent.click(within(form).getByRole("button", { name: "Check folder" }));
    const results = await within(form).findByRole("list", { name: "Folder check" });
    expect(within(results).getByText(/Looks like a Dropbox folder/)).toBeTruthy();
    expect(within(results).getByText(/not encrypted yet/)).toBeTruthy();
    expect(use.disabled).toBe(false);
    fireEvent.click(use);
    await waitFor(() => expect(screen.queryByRole("form", { name: "Where backups go" })).toBeNull());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toContain("/settings/backup/folder");
    expect(put?.body).toEqual({ path: target });
    expect(screen.getByText(/in your Dropbox folder/)).toBeTruthy();
  });
});
