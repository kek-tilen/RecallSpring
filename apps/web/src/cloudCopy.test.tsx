import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./pages/Settings";
import type { CloudView } from "./types";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.open = false;
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const off: CloudView = {
  available: { google: true },
  provider: null,
  connected_at: null,
  state: "off",
  last_success_at: null,
  backups: null,
  bytes: null,
  free_bytes: null,
  error: null,
  next_try_at: null,
  progress: null,
  pending: null,
};

const connected: CloudView = {
  ...off,
  provider: "google",
  connected_at: "2026-11-27T09:00:00+00:00",
  state: "ok",
  last_success_at: "2026-11-27T09:14:00+00:00",
  backups: 9,
  bytes: 1.3 * 1024 ** 3,
  free_bytes: 11.4 * 1024 ** 3,
};

function status(cloud: CloudView, encrypted = true) {
  return {
    enabled: true,
    location: "D:\\Backups",
    location_source: "settings",
    server_location: "C:\\RS\\backups",
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
    snapshots: [],
    disk_bytes: 0,
    tools: "pg_dump",
    encryption: encrypted ? { on: true, key_id: "6954F17A", key_created_at: "2026-11-27T09:00:00+00:00" } : { on: false, key_id: null, key_created_at: null },
    unencrypted_snapshots: 0,
    remove_unencrypted_pending: false,
    cloud,
  };
}

function setup(first: ReturnType<typeof status>, routes: Record<string, (body: unknown) => unknown> = {}) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, url, body });
    for (const [path, fn] of Object.entries(routes)) if (url.includes(path)) return json(fn(body));
    if (url.includes("/deleted")) return json({ restorable_days: 30, items: [] });
    if (url.includes("/settings/backup")) return json(first);
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

const row = () => screen.getByRole("heading", { level: 3, name: "Cloud copy" }).closest("#cloud-copy") as HTMLElement;

describe("Cloud copy", () => {
  it("asks for encryption first and sits under Where backups go", async () => {
    setup(status(off, false));
    await screen.findByRole("heading", { level: 3, name: "Cloud copy" });
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles.indexOf("Cloud copy")).toBeGreaterThan(titles.indexOf("How often"));
    expect(within(row()).getByText("Off · backups stay on this computer")).toBeTruthy();
    expect(within(row()).getByRole("link", { name: "Turn on encryption first" }).getAttribute("href")).toBe("#backup-encryption");
    expect(within(row()).queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("says a server without a Google app ID cannot connect yet", async () => {
    setup(status({ ...off, available: { google: false } }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    const google = screen.getByRole("button", { name: /Google Drive/ }) as HTMLButtonElement;
    expect(google.disabled).toBe(true);
    expect(screen.getByText(/RS_CLOUD_GOOGLE_CLIENT_ID/)).toBeTruthy();
    expect(screen.getByText(/Only through a synced folder/)).toBeTruthy();
  });

  it("signs in with a code and shows the first copy", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let polls = 0;
    const calls = setup(status(off), {
      "/cloud/google/start": () => ({ user_code: "WDJB-MJHT", verification_url: "https://www.google.com/device", expires_at: "2026-11-27T10:00:00+00:00", interval: 5 }),
      "/cloud/google/poll": () => {
        polls += 1;
        return polls < 2
          ? { state: "pending", backup: status(off) }
          : { state: "connected", backup: status({ ...connected, state: "copying", progress: { done_files: 1, total_files: 3, done_bytes: 410 * 1024 ** 2, total_bytes: 1.3 * 1024 ** 3 } }) };
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    fireEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
    expect((await screen.findByLabelText("Code to enter at Google")).textContent).toBe("WDJB-MJHT");
    expect(screen.getByRole("link", { name: "google.com/device" }).getAttribute("href")).toBe("https://www.google.com/device");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_500);
    });
    expect(await screen.findByRole("heading", { level: 4, name: "Connected" })).toBeTruthy();
    expect(screen.getByText("Folder: My Drive › RecallSpring backups")).toBeTruthy();
    expect(screen.getAllByText(/Copying 2 of 3/).length).toBeGreaterThan(0);
    expect(calls.filter((c) => c.url.includes("/poll")).length).toBe(2);
  });

  it("copies now and disconnects, deleting the files only after asking again", async () => {
    const calls = setup(status(connected), {
      "/cloud/copy": () => status({ ...connected, state: "copying" }),
      "/cloud/disconnect": () => status(off),
    });
    expect(await within(await screen.findByText(/Google Drive · copied/)).findByText(/9 backups, 1.3 GB/)).toBeTruthy();
    fireEvent.click(within(row()).getByRole("button", { name: "Manage" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy now" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/cloud/copy"))).toBe(true));
    fireEvent.click(screen.getByLabelText("Delete them too"));
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(calls.some((c) => c.url.endsWith("/cloud/disconnect"))).toBe(false); // asks first
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect and delete" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/cloud/disconnect"))?.body).toEqual({ delete_files: true }));
    expect(await screen.findByText("Off · backups stay on this computer")).toBeTruthy();
  });

  it("offers to sign in again when Google withdrew access", async () => {
    setup(status({ ...connected, state: "revoked", error: { code: "revoked", message: "Google Drive no longer allows RecallSpring.", at: "2026-11-27T09:00:00+00:00" } }));
    expect(await screen.findByText(/stopped: Google Drive no longer allows RecallSpring/)).toBeTruthy();
    fireEvent.click(within(row()).getByRole("button", { name: "Manage" }));
    expect(screen.getByRole("button", { name: "Sign in to Google again" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Copy now" })).toBeNull();
  });
});
