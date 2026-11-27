import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./pages/Settings";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DAY = 86_400_000;
const iso = (ms: number) => new Date(ms).toISOString();

const status = {
  enabled: true,
  location: "D:\\Backups",
  location_source: "settings",
  server_location: "C:\\RS\\local-data\\backups",
  folder_from_web: true,
  sync: null,
  can_change: true,
  same_disk_as_storage: false,
  schedule: { every: "days", days: 1, day_of_month: null, at: "03:00", source: "server" },
  schedule_label: "Daily at 03:00",
  timezone: "Europe/Ljubljana",
  keep_last: 7,
  keeps: "daily_weekly",
  keep_daily: 7,
  keep_weekly: 4,
  last_attempt_at: null,
  last_success_at: null,
  last_error: null,
  last: null,
  next_due: "now",
  snapshots: ["20261127-091200", "20261120-030000", "20261125-030000"],
  disk_bytes: 0,
  tools: "pg_dump",
  encryption: { on: true, key_id: "6954F17A", key_created_at: "2026-11-27T09:00:00+00:00" },
  unencrypted_snapshots: 0,
  remove_unencrypted_pending: false,
};

function deletedList(now: number) {
  return {
    restorable_days: 30,
    items: [
      { type: "note", id: "n1", title: "Eigenvalues", course_title: "Linear algebra", deleted_at: iso(now), restorable_until: iso(now + 30 * DAY) },
      {
        type: "exam",
        id: "t1",
        title: "1st kolokvij",
        course_title: "Statistics",
        deleted_at: iso(now - 2 * DAY),
        restorable_until: iso(now + 28 * DAY - 60_000),
        due_date: "2026-12-10",
      },
      {
        type: "course",
        id: "c1",
        title: "Organic chemistry",
        course_title: null,
        deleted_at: iso(now - 24 * DAY),
        restorable_until: iso(now + 6 * DAY - 60_000),
        brings: { notes: 12, exams: 1, materials: 0 },
      },
    ],
  };
}

function setup(list: unknown) {
  const calls: { method: string; url: string }[] = [];
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, url });
    if (url.endsWith("/restore")) return json({});
    if (url.includes("/deleted")) return json(list);
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
  return calls;
}

describe("Data & backups rows", () => {
  it("keeps the rows in order with Backup details last", async () => {
    setup({ restorable_days: 30, items: [] });
    await screen.findByRole("heading", { level: 3, name: "Getting it back" });
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles.slice(-5)).toEqual(["Getting it back", "Recently deleted", "History", "Export", "Your Google Drive"]);
    const details = screen.getByText("Backup details").closest("details")!;
    const history = screen.getByRole("heading", { level: 3, name: "History" });
    expect(history.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByText("Nothing deleted in the last 30 days")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open recently deleted" })).toBeNull();
  });

  it("opens one list of what was deleted and restores an item with its own endpoint", async () => {
    const now = Date.now();
    const calls = setup(deletedList(now));
    expect(await screen.findByText(/3 items · restorable for 30 days · the next one goes in 5 days/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open recently deleted" }));
    const list = screen.getByRole("list", { name: "Recently deleted items" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("strong")?.textContent)).toEqual(["Eigenvalues", "1st kolokvij", "Organic chemistry"]);
    expect(within(rows[2]!).getByText(/With 12 notes, 1 exam/)).toBeTruthy();
    expect(within(rows[2]!).getByText("5 days left").className).toBe("warn-text");
    expect(screen.queryByRole("combobox")).toBeNull(); // no filter for a short list
    fireEvent.click(screen.getByRole("button", { name: "Restore exam 1st kolokvij" }));
    const done = await screen.findByRole("status");
    expect(done.textContent).toContain("1st kolokvij is back in Exams");
    expect(within(done).getByRole("link", { name: "Open Exams" }).getAttribute("href")).toBe("/exams");
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/targets/t1/restore"))).toBe(true);
  });

  it("shows the restore steps for this installation", async () => {
    setup({ restorable_days: 30, items: [] });
    fireEvent.click(await screen.findByRole("button", { name: "Show the restore steps" }));
    expect(screen.getByText(/3 backups here · newest 27 Nov 2026, 09:12 · oldest 20 Nov 2026, 03:00/)).toBeTruthy();
    expect(screen.getByText("recallspring backup-restore --database recallspring_restored --storage <an empty folder> --key <your recovery key file>")).toBeTruthy();
    expect(screen.getByText(/Encrypted backups need your recovery key file \(made 27 Nov 2026\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close the restore steps" }));
    await waitFor(() => expect(screen.queryByText(/backup-restore --database/)).toBeNull());
  });

  it("names the encryption button Recovery key and keeps Make a new key behind it", async () => {
    setup({ restorable_days: 30, items: [] });
    fireEvent.click(await screen.findByRole("button", { name: "Recovery key" }));
    expect(screen.getByText(/Made on 27 Nov 2026 \(key 6954F17A\)/)).toBeTruthy();
    expect(screen.queryByText(/RS1-|AGE-SECRET-KEY/)).toBeNull(); // the key is never shown again
    fireEvent.click(screen.getByRole("button", { name: "Make a new key" }));
    expect(screen.getByRole("button", { name: "Make my recovery key" })).toBeTruthy();
  });
});
