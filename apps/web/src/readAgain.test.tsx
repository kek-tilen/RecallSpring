import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { SourceTable } from "./pages/Library";
import type { Source } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const src = (id: string, parse_state: Source["parse_state"]) =>
  ({ id, course_id: "k1", filename: `${id}.pdf`, kind: "pdf", category: "material", parse_state, byte_size: 10, uploaded_at: "2026-11-22T10:00:00Z" }) as unknown as Source;

it("offers to read failed files again and asks the server once per failed file", async () => {
  const sent: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if ((init?.method ?? "GET") !== "GET") sent.push(path);
    return new Response("{}", { status: 202, headers: { "Content-Type": "application/json" } });
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SourceTable sources={[src("a", "failed"), src("b", "ready"), src("c", "failed")]} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText(/2 files could not be read/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Read these 2 files again" }));
  await waitFor(() => expect(sent).toEqual(["/api/v1/sources/a/reprocess", "/api/v1/sources/c/reprocess"]));
});
