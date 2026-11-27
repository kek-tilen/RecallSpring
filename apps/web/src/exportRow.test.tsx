import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExportRow } from "./components/ExportRow";
import type { ExportItem, ExportView } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const courses = [
  { id: "c1", title: "Biology", files: 10, bytes: 300 * 1024 ** 2, notes: 4, answers: 20 },
  { id: "c2", title: "History", files: 2, bytes: 5 * 1024 ** 2, notes: 1, answers: 0 },
];

const item = (over: Partial<ExportItem>): ExportItem => ({
  id: "e1",
  state: "queued",
  destination: "download",
  options: { course_ids: null, material: true, notes: true, answers: true },
  progress: null,
  counts: null,
  byte_size: null,
  file_name: "RecallSpring export 2026-11-27.zip",
  error: null,
  created_at: "2026-11-27T09:00:00+00:00",
  finished_at: null,
  expires_at: null,
  downloaded_at: null,
  ...over,
});

const view = (current: ExportItem | null, last: string | null = null): ExportView => ({ courses, current, last_export_at: last, keep_hours: 24 });

function serve(first: ExportView, routes: Record<string, (body: unknown) => unknown> = {}) {
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
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ExportRow />
    </QueryClientProvider>,
  );
  return calls;
}

describe("Export row", () => {
  it("chooses courses and parts, then shows the export being made", async () => {
    const calls = serve(view(null), {
      "/exports": () => view(item({ state: "running", progress: { done_files: 3, total_files: 12 } })),
      "/exports/e1/cancel": () => view(item({ state: "cancelled" })),
    });
    expect(await screen.findByText("Never · your material, notes and answers as a ZIP to download")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(screen.getByText(/About 305 MB · 12 files, 5 notes, 20 answers/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Choose/));
    fireEvent.click(screen.getByLabelText("History"));
    fireEvent.click(screen.getByLabelText(/Answers and grades/));
    expect(screen.getByText(/About 300 MB · 10 files, 4 notes, 0 answers/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make the export" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        course_ids: ["c1"],
        material: true,
        notes: true,
        answers: false,
        destination: "download",
      }),
    );
    expect(await screen.findByText("3 of 12 items")).toBeTruthy();
    expect(screen.getByText(/Today says when it is ready/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/exports/e1/cancel"))).toBe(true));
  });

  it("offers the finished ZIP and says it is kept a day, unencrypted", async () => {
    const expires = new Date(Date.now() + 20 * 3600_000).toISOString();
    const ready = item({ state: "ready", byte_size: 1.2 * 1024 ** 3, counts: { files: 214, notes: 63, answers: 412 }, expires_at: expires });
    const calls = serve(view(ready), { "/exports/e1/cancel": () => view(item({ state: "expired" }), "2026-11-27T09:05:00+00:00") });
    expect(await screen.findByText(/Ready · 1.2 GB · kept until/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toBe("/api/v1/exports/e1/download");
    expect(screen.getByText("214 files, 63 notes, 412 answers")).toBeTruthy();
    expect(screen.getByText(/Kept here for 24 hours, then deleted. It is not encrypted/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make a new one" }));
    expect(screen.getByRole("button", { name: "Make the export" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete it now" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/exports/e1/cancel"))).toBe(true));
    expect(await screen.findByText(/last export 27 Nov 2026/)).toBeTruthy();
  });

  it("says when the last export failed", async () => {
    serve(view(item({ state: "failed", error: "not_enough_space", finished_at: "2026-11-27T09:00:00+00:00" })));
    expect(await screen.findByText(/The last export failed · The server ran out of disk space/)).toBeTruthy();
  });
});
