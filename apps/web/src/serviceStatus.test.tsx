import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ServiceStatus } from "./components/ServiceStatus";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function show(status: number, body: object) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ServiceStatus />
    </QueryClientProvider>,
  );
}

describe("running in the background", () => {
  it("shows that the API and the worker run and where the logs are", async () => {
    show(200, { status: "ready", checks: { database: true, contracts: true }, worker: { state: "running", last_seen: "2026-11-22T20:10:51Z" } });
    expect(await screen.findByText("API ok")).toBeTruthy();
    expect(screen.getByText("Worker running")).toBeTruthy();
    expect(document.body.textContent).toContain("scripts\\logs.ps1");
  });

  it("says what waits when the worker stopped, also when the database is down", async () => {
    show(503, { status: "not_ready", checks: { database: false, contracts: true }, worker: { state: "stopped", last_seen: "2026-11-22T18:00:00Z" } });
    expect(await screen.findByText("API database unavailable")).toBeTruthy();
    expect(screen.getByText("Worker stopped")).toBeTruthy();
    expect(document.body.textContent).toContain("Imports and automatic backups wait");
    expect(document.body.textContent).toContain("scripts\\start-local.ps1 -Restart");
  });
});
