import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { assistantWords } from "./assistant";
import { fill, GOOD_TO_KNOW } from "./guide";
import { LoginPage } from "./pages/Login";
import { WelcomePage } from "./pages/Welcome";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const USER = { id: "u1", username: "ana", timezone: "UTC", assistant: null };

type Call = { url: string; method: string; body: unknown };

function mockApi(routes: Record<string, (body: unknown) => Response>) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    for (const [key, handler] of Object.entries(routes)) {
      const [m, path = ""] = key.split(" ");
      if (m === method && url.includes(path)) return handler(body);
    }
    return json(404, { error: { code: "not_found", message: "Not found." } });
  });
  return calls;
}

function renderAt(path: string, qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/welcome" element={<WelcomePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
}

describe("first run", () => {
  it("creates the first account with the time zone and opens the welcome page", async () => {
    const calls = mockApi({
      "GET /auth/setup": () => json(200, { needs_setup: true, refusal: null }),
      "POST /auth/setup": (b) => json(201, { user: { ...USER, timezone: (b as { timezone: string }).timezone }, expires_at: "2026-12-01T00:00:00Z" }),
      "GET /auth/session": () => json(200, { user: USER, expires_at: "2026-12-01T00:00:00Z" }),
    });
    renderAt("/login");
    await screen.findByRole("heading", { name: "Welcome to RecallSpring" });
    fireEvent.change(screen.getByLabelText(/^Username/), { target: { value: "ana" } });
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "a-long-password" } });
    fireEvent.change(screen.getByLabelText(/^Repeat password/), { target: { value: "a-long-passwork" } });
    expect(screen.getByText("The passwords do not match.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Create account" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/^Repeat password/), { target: { value: "a-long-password" } });
    fireEvent.change(screen.getByLabelText(/^Time zone/), { target: { value: "UTC" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Choose your assistant" });
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ username: "ana", password: "a-long-password", timezone: "UTC" });
  });

  it("explains where to create the account when this browser may not", async () => {
    mockApi({ "GET /auth/setup": () => json(200, { needs_setup: true, refusal: "not_local" }) });
    renderAt("/login");
    await screen.findByText("RecallSpring has no account yet");
    expect(screen.queryByRole("button", { name: "Create account" })).toBeNull();
  });

  it("shows the normal sign-in once an account exists", async () => {
    mockApi({ "GET /auth/setup": () => json(200, { needs_setup: false, refusal: null }) });
    renderAt("/login");
    await screen.findByRole("button", { name: "Sign in" });
    expect(screen.getByText(/separate from any AI assistant/)).toBeTruthy();
  });
});

describe("welcome", () => {
  it("saves the chosen assistant and shows its next steps", async () => {
    const calls = mockApi({
      "GET /auth/session": () => json(200, { user: USER, expires_at: "2026-12-01T00:00:00Z" }),
      "PUT /settings/profile": (b) => json(200, { ...USER, ...(b as object) }),
    });
    renderAt("/welcome");
    await screen.findByRole("heading", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    fireEvent.click(screen.getByRole("radio", { name: /^Codex/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Next: set up Codex");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ assistant: "codex" });
    expect(screen.getByText(/install-codex-connector\.ps1 -Username ana/)).toBeTruthy();
  });

  it("offers Antigravity with its own installer", async () => {
    const calls = mockApi({
      "GET /auth/session": () => json(200, { user: USER, expires_at: "2026-12-01T00:00:00Z" }),
      "PUT /settings/profile": (b) => json(200, { ...USER, ...(b as object) }),
    });
    renderAt("/welcome");
    await screen.findByRole("heading", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    fireEvent.click(screen.getByRole("radio", { name: /^Antigravity/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Next: set up Antigravity");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ assistant: "antigravity" });
    expect(screen.getByText(/install-antigravity-connector\.ps1 -Username ana/)).toBeTruthy();
    expect(screen.getByText(/It connects Antigravity and makes a Planning folder/)).toBeTruthy();
    expect(fill("Grades from {assistant} are estimates.", assistantWords("antigravity"))).toBe("Grades from Antigravity are estimates.");
  });

  it("saves a mix of at least two assistants and shows the setup steps of each", async () => {
    const calls = mockApi({
      "GET /auth/session": () => json(200, { user: USER, expires_at: "2026-12-01T00:00:00Z" }),
      "PUT /settings/profile": (b) => json(200, { ...USER, ...(b as object) }),
    });
    renderAt("/welcome");
    await screen.findByRole("heading", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    fireEvent.click(screen.getByRole("radio", { name: /^Mix/ }));
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(screen.getByText("Choose at least two.")).toBeTruthy();
    const group = screen.getByRole("group", { name: "Assistants in your mix" });
    fireEvent.click(within(group).getByRole("checkbox", { name: "ChatGPT" }));
    expect(save.disabled).toBe(true);
    fireEvent.click(within(group).getByRole("checkbox", { name: "Claude" }));
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await screen.findByText("Next: set up your assistants");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ assistant: "mix", assistant_mix: ["claude", "chatgpt"] });
    expect(screen.getByRole("region", { name: "Set up Claude" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Set up ChatGPT" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Set up Codex" })).toBeNull();
  });
});

describe("assistant wording", () => {
  it("names the chosen assistant and stays neutral without one", () => {
    expect(fill("Grades from {assistant} are estimates.", assistantWords("codex"))).toBe("Grades from Codex are estimates.");
    expect(fill("{Assistant} only keeps it.", assistantWords(null))).toBe("Your assistant only keeps it.");
    expect(assistantWords("chatgpt").where).toBe("in Chat");
  });

  it("shows Claude Desktop tips only to Claude users", () => {
    const shown = (key: "claude" | "codex") => GOOD_TO_KNOW.filter((f) => !f.only || f.only.includes(key)).map((f) => f.text);
    expect(shown("codex").some((t) => t.includes("Claude Desktop"))).toBe(false);
    expect(shown("claude").some((t) => t.includes("Claude Desktop"))).toBe(true);
  });
});
