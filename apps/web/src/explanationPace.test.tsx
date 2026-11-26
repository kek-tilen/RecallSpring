import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExplanationPaceControl, ExplanationPaceDefault } from "./components/ExplanationPace";

// Owner notes 2026-11-26, part D: a default explanation pace in Settings, and a course may choose its own.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const USER = { id: "u1", username: "learner", timezone: "Europe/Ljubljana", assistant: null, explanation_pace: "balanced" };

function serve(coursePace: string | null) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/auth/session") return json({ user: USER, expires_at: "2026-12-01T00:00:00Z" });
    if (path === "/courses") return json([{ id: "k1", title: "Biology", description: null, status: "active", kind: "course", color: null, group_id: null, explanation_pace: coursePace }]);
    if (path === "/settings/profile") return json({ ...USER, ...JSON.parse(String(init?.body)) });
    if (path === "/courses/k1/explanation-pace") return json({ pace: "step", source: "course" });
    return new Response("{}", { status: 404 });
  });
}

const sent = (fetch: ReturnType<typeof serve>, path: string) =>
  fetch.mock.calls
    .filter(([input, init]) => String(input).includes(path) && init?.method === "PUT")
    .map(([, init]) => JSON.parse(String(init?.body)));

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("Explanation pace (owner 2026-11-26)", () => {
  it("sets the default for every course in Settings", async () => {
    const fetch = serve(null);
    wrap(<ExplanationPaceDefault />);
    const select = (await screen.findByRole("combobox", { name: /How your assistant explains/ })) as HTMLSelectElement;
    expect(select.value).toBe("balanced");
    expect(screen.getByText(/only the size of each part changes/)).toBeTruthy();
    fireEvent.change(select, { target: { value: "step" } });
    await waitFor(() => expect(sent(fetch, "/settings/profile")).toEqual([{ explanation_pace: "step" }]));
  });

  it("lets a course follow the default or choose its own", async () => {
    const fetch = serve(null);
    wrap(<ExplanationPaceControl courseId="k1" />);
    expect(await screen.findByRole("option", { name: "Default (Balanced)" })).toBeTruthy();
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("default");
    fireEvent.change(select, { target: { value: "step" } });
    await waitFor(() => expect(sent(fetch, "/courses/k1/explanation-pace")).toEqual([{ pace: "step" }]));
  });

  it("shows a course's own pace and can go back to the default", async () => {
    const fetch = serve("chunks");
    wrap(<ExplanationPaceControl courseId="k1" />);
    const select = (await screen.findByRole("combobox")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("chunks"));
    expect(screen.getByText(/A whole topic in one go/)).toBeTruthy();
    fireEvent.change(select, { target: { value: "default" } });
    await waitFor(() => expect(sent(fetch, "/courses/k1/explanation-pace")).toEqual([{ pace: null }]));
  });
});
