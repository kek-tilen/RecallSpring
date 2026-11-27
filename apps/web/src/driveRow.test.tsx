import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { DriveRow } from "./components/DriveRow";
import { ExportRow } from "./components/ExportRow";
import type { DriveView, ExportView } from "./types";

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
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const off: DriveView = { available: true, state: "off", pending: null };
const on = (over: Partial<DriveView> = {}): DriveView => ({
  available: true,
  state: "ok",
  pending: null,
  connected_at: "2026-11-27T09:00:00+00:00",
  folder: "My Drive › RecallSpring",
  mirror: true,
  exports: false,
  files: 3,
  bytes: 5 * 1024 ** 2,
  not_yet: { files: 214, bytes: 1.1 * 1024 ** 3 },
  free_bytes: 9.8 * 1024 ** 3,
  last_success_at: "2026-11-27T09:05:00+00:00",
  progress: null,
  error: null,
  next_try_at: null,
  ...over,
});
const device = { user_code: "WDJB-MJHT", verification_url: "https://www.google.com/device", expires_at: "2026-11-27T09:30:00+00:00", interval: 5 };

function serve(first: unknown, routes: Record<string, (body: unknown) => unknown> = {}) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, url, body });
    const hit = Object.entries(routes).find(([p]) => method === "POST" && url.endsWith(p));
    const out = hit ? hit[1](body) : first;
    return new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

function show(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("Your Google Drive row", () => {
  it("connects with a code, then copies by itself", async () => {
    let connected = false;
    const calls = serve(off, {
      "/drive/start": () => device,
      "/drive/poll": () => (connected ? { state: "connected", drive: on() } : { state: "pending", drive: off }),
    });
    show(<DriveRow />);
    expect(await screen.findByText("Off · a readable copy of your material in your own Google Drive")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(screen.getByText("Readable at Google, like any file you keep there")).toBeTruthy();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(screen.getByRole("button", { name: "Connect Google Drive" }));
    expect(await screen.findByLabelText("Code to enter at Google")).toBeTruthy();
    expect(screen.getByText("WDJB-MJHT")).toBeTruthy();
    connected = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(await screen.findByText(/Connected · folder My Drive › RecallSpring/)).toBeTruthy();
    expect(calls.some((c) => c.url.endsWith("/drive/poll"))).toBe(true);
    expect(screen.getByText(/214 files, 1.1 GB · 9.8 GB free/)).toBeTruthy();
  });

  it("copies what is already here, sets the options and disconnects after asking", async () => {
    const calls = serve(on(), {
      "/drive/copy-existing": () => on({ state: "copying", not_yet: { files: 0, bytes: 0 }, progress: { done_files: 0, total_files: 214, done_bytes: 0, total_bytes: 1 } }),
      "/drive/settings": (b) => on({ exports: (b as { exports?: boolean }).exports ?? false, not_yet: { files: 0, bytes: 0 } }),
      "/drive/disconnect": () => off,
    });
    show(<DriveRow />);
    expect(await screen.findByText(/Connected · 3 files, 5 MB · last copy/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Manage" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByText(/Copying 1 of 214/, { selector: "p" })).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Exports go here too"));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/drive/settings"))?.body).toEqual({ exports: true }));
    fireEvent.click(screen.getByLabelText("Delete everything RecallSpring made there"));
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(await screen.findByText(/This cannot be undone. Your material in RecallSpring stays/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect and delete" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/drive/disconnect"))?.body).toEqual({ delete_files: true }));
  });

  it("says when Google withdrew access", async () => {
    serve(on({ state: "revoked", error: { code: "revoked", message: "Google Drive no longer allows RecallSpring. Your material is safe here; connect again to keep copying.", at: "" } }));
    show(<DriveRow />);
    expect(await screen.findByText("Stopped: Google Drive no longer allows RecallSpring")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Manage" }));
    expect(screen.getByRole("button", { name: "Sign in to Google again" })).toBeTruthy();
  });
});

describe("Export to Drive", () => {
  const courses = [{ id: "c1", title: "Biology", files: 10, bytes: 300 * 1024 ** 2, notes: 4, answers: 20 }];
  const view = (drive: boolean): ExportView => ({ courses, current: null, last_export_at: null, keep_hours: 24, drive });

  it("offers To my Drive only when it is on", async () => {
    const calls = serve(view(true), { "/exports": () => view(true) });
    show(<ExportRow />);
    fireEvent.click(await screen.findByRole("button", { name: "Export" }));
    expect(screen.getByLabelText(/To my Drive/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make the export" }));
    await waitFor(() => expect((calls.find((c) => c.method === "POST")?.body as { destination: string }).destination).toBe("drive"));
  });

  it("has no choice without it", async () => {
    serve(view(false));
    show(<ExportRow />);
    fireEvent.click(await screen.findByRole("button", { name: "Export" }));
    expect(screen.queryByLabelText(/To my Drive/)).toBeNull();
  });
});
