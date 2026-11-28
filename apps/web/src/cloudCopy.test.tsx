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
  available: { google: true, dropbox: true, onedrive: true, folder: true },
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
    setup(status({ ...off, available: { google: false, dropbox: false, onedrive: false, folder: false } }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    const google = screen.getByRole("button", { name: /Google Drive/ }) as HTMLButtonElement;
    expect(google.disabled).toBe(true);
    expect((screen.getByRole("button", { name: /^Dropbox/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/RS_CLOUD_GOOGLE_CLIENT_ID/)).toBeTruthy();
    expect(screen.getByText(/RS_CLOUD_DROPBOX_APP_KEY/)).toBeTruthy();
    expect(screen.getByText(/RS_CLOUD_ONEDRIVE_CLIENT_ID/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /^OneDrive/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Not available yet/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /^A synced folder/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Not offered on this server")).toBeTruthy();
  });

  it("shows a synced folder the server settings give, without anything to change", async () => {
    const server: CloudView = {
      ...connected,
      provider: "folder",
      connected_at: null,
      folder: { path: "/srv/sync/RecallSpring", where: "/srv/sync/RecallSpring", sync: "Nextcloud", from_server: true },
    };
    setup({ ...status(server), can_change: false });
    await screen.findByRole("heading", { level: 3, name: "Cloud copy" });
    expect(await within(row()).findByText(/^Nextcloud · handed over/)).toBeTruthy();
    expect(within(row()).getByText(/set in the server settings/)).toBeTruthy();
    expect(within(row()).queryByRole("button")).toBeNull();
  });

  it("copies to a synced folder after checking it", async () => {
    const folderOff = { ...off, folder: { suggestions: [{ app: "iCloud Drive", path: "C:\\Users\\ana\\iCloudDrive" }] } };
    const done: CloudView = {
      ...connected,
      provider: "folder",
      free_bytes: 182 * 1024 ** 3,
      folder: { path: "C:\\Users\\ana\\iCloudDrive\\RecallSpring backups", where: "iCloud Drive › RecallSpring backups", sync: "iCloud Drive" },
    };
    const calls = setup(status(folderOff), {
      "/cloud/folder/check": () => ({
      path: "C:\\Users\\ana\\iCloudDrive\\RecallSpring backups",
      ok: true,
      checks: [
        { id: "write", level: "ok", text: "RecallSpring can make this folder · 182 GB free on this disk" },
        { id: "sync", level: "ok", text: "iCloud Drive, recognised from the path" },
        { id: "upload", level: "warn", text: "RecallSpring sees what it put in the folder, not when iCloud Drive has uploaded it." },
      ],
      sync: "iCloud Drive",
    }),
      "/cloud/folder/connect": () => status(done),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    fireEvent.click(screen.getByRole("button", { name: /^A synced folder/ }));
    expect(screen.getByRole("heading", { level: 4, name: "A synced folder" })).toBeTruthy();
    const use = screen.getByRole("button", { name: "Use this folder" }) as HTMLButtonElement;
    expect(use.disabled).toBe(true); // checked first
    fireEvent.click(screen.getByRole("button", { name: "Use iCloud Drive" }));
    const input = within(screen.getByRole("form", { name: "Synced folder" })).getByRole("textbox") as HTMLInputElement;
    expect(input.value).toBe("C:\\Users\\ana\\iCloudDrive\\RecallSpring backups");
    fireEvent.click(screen.getByRole("button", { name: "Check folder" }));
    expect(await screen.findByText("iCloud Drive, recognised from the path")).toBeTruthy();
    expect(screen.getByText(/not when iCloud Drive has uploaded it/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use this folder" }));
    expect(await screen.findByRole("heading", { level: 4, name: "Connected" })).toBeTruthy();
    expect(screen.getByText("Folder: iCloud Drive › RecallSpring backups")).toBeTruthy();
    expect(screen.getByText(/182 GB free on this disk/)).toBeTruthy();
    const connect = calls.find((c) => c.url.endsWith("/cloud/folder/connect"));
    expect(connect?.body).toEqual({ path: "C:\\Users\\ana\\iCloudDrive\\RecallSpring backups" });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(within(row()).getByText(/^iCloud Drive · handed over/)).toBeTruthy();
    fireEvent.click(within(row()).getByRole("button", { name: "Manage" }));
    expect(screen.getByText("Disconnect: RecallSpring stops copying into the folder")).toBeTruthy();
    expect(screen.getByText("Keep the files in the folder")).toBeTruthy();
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

  it("connects Dropbox with a pasted code and names its folder", async () => {
    const pending = { provider: "dropbox", authorize_url: "https://www.dropbox.com/oauth2/authorize?x=1", expires_at: "2026-11-28T10:00:00+00:00" };
    const dropbox: CloudView = { ...connected, provider: "dropbox", free_bytes: null, state: "copying" };
    const calls = setup(status(off), {
      "/cloud/dropbox/start": () => pending,
      "/cloud/dropbox/finish": () => ({ state: "connected", backup: status(dropbox) }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    fireEvent.click(screen.getByRole("button", { name: /^Dropbox/ }));
    expect((await screen.findByRole("link", { name: "Open Dropbox" })).getAttribute("href")).toBe(pending.authorize_url);
    expect(screen.getByText(/only its own folder, Apps › RecallSpring, for your encrypted backups/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Code from Dropbox"), { target: { value: "sl.code-from-dropbox" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByRole("heading", { level: 4, name: "Connected" })).toBeTruthy();
    expect(screen.getByText("Folder: Dropbox › Apps › RecallSpring › Backups")).toBeTruthy();
    expect(calls.find((c) => c.url.endsWith("/cloud/dropbox/finish"))?.body).toEqual({ code: "sl.code-from-dropbox" });
  });

  it("starts the Dropbox sign-in again when the code came too late", async () => {
    const pending = { provider: "dropbox", authorize_url: "https://www.dropbox.com/oauth2/authorize?x=1", expires_at: "2026-11-28T10:00:00+00:00" };
    let starts = 0;
    const calls: { url: string }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url });
      const json = (body: unknown, s = 200) => new Response(JSON.stringify(body), { status: s, headers: { "Content-Type": "application/json" } });
      if (url.includes("/cloud/dropbox/start")) {
        starts += 1;
        return json(pending);
      }
      if (url.includes("/cloud/dropbox/finish")) return json({ code: "cloud_expired", message: "This sign-in expired. Start again." }, 409);
      if (url.includes("/deleted")) return json({ restorable_days: 30, items: [] });
      if (url.includes("/settings/backup") && (init?.method ?? "GET") === "GET") return json(status(off));
      return json({ code: "not_found", message: "Not found." }, 404);
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/settings#data"]}>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    fireEvent.click(screen.getByRole("button", { name: /^Dropbox/ }));
    fireEvent.change(await screen.findByLabelText("Code from Dropbox"), { target: { value: "sl.code-from-dropbox" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText(/This sign-in expired before a code was pasted/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(await screen.findByLabelText("Code from Dropbox")).toBeTruthy();
    expect(starts).toBe(2);
  });

  it("signs in to OneDrive with a code and says when a school blocks it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const msDevice = { provider: "onedrive", user_code: "FAKE1234", verification_url: "https://microsoft.com/devicelogin", expires_at: "2026-11-28T10:00:00+00:00", interval: 5 };
    let blocked = true;
    const calls = setup(status(off), {
      "/cloud/onedrive/start": () => msDevice,
      "/cloud/onedrive/poll": () =>
        blocked
          ? { state: "blocked", backup: status(off) }
          : { state: "connected", backup: status({ ...connected, provider: "onedrive", free_bytes: null }) },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    fireEvent.click(screen.getByRole("button", { name: /^OneDrive/ }));
    expect((await screen.findByLabelText("Code to enter at Microsoft")).textContent).toBe("FAKE1234");
    expect(screen.getByRole("link", { name: "microsoft.com/devicelogin" })).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5500);
    });
    expect(await screen.findByText(/Your school or work account does not allow this kind of sign-in/)).toBeTruthy();
    blocked = false;
    fireEvent.click(screen.getByRole("button", { name: "Get a new code" }));
    await screen.findByLabelText("Code to enter at Microsoft");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5500);
    });
    expect(await screen.findByRole("heading", { level: 4, name: "Connected" })).toBeTruthy();
    expect(screen.getByText("Folder: OneDrive › Apps › RecallSpring › Backups")).toBeTruthy();
    expect(calls.filter((c) => c.url.endsWith("/cloud/onedrive/start")).length).toBe(2);
  });
});
