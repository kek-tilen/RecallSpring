import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
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

function CoursesMarker() {
  const state = useLocation().state as { newCourse?: boolean } | null;
  return <p>Courses, new course: {state?.newCourse ? "yes" : "no"}</p>;
}

function renderAt(path: string, qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/welcome" element={<WelcomePage />} />
          <Route path="/courses" element={<CoursesMarker />} />
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
    await screen.findByRole("group", { name: "Choose your assistant" });
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
  const session = (user: object = USER) => () => json(200, { user, expires_at: "2026-12-01T00:00:00Z" });
  const echo = (b: unknown) => json(200, { ...USER, ...(b as object) });
  const NOT_CONNECTED = { connected: false, registered: false, unreadable: false, email: null, name: null, scopes: [], plan_usage: false, signed_in_at: null, unavailable_reason: null };

  it("has no rail and saves one ticked assistant, then opens Courses with a new course started", async () => {
    const calls = mockApi({ "GET /auth/session": session(), "PUT /settings/profile": echo });
    renderAt("/welcome");
    const pick = await screen.findByRole("group", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.getByText(/None yet is fine/)).toBeTruthy();
    fireEvent.click(within(pick).getByRole("checkbox", { name: /^Codex/ }));
    const box = screen.getByRole("region", { name: "Connector command" });
    expect(within(box).getByText("Command for Codex")).toBeTruthy();
    expect(within(box).getByText(/install-connectors\.ps1 -Assistants codex -Username ana/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Courses, new course: yes");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ assistant: "codex" });
  });

  it("makes two or more a mix with one command for every app that has a connector", async () => {
    const calls = mockApi({
      "GET /auth/session": session(),
      "PUT /settings/profile": echo,
      "GET /ai/chatgpt": () => json(200, NOT_CONNECTED),
    });
    renderAt("/welcome");
    const pick = await screen.findByRole("group", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    for (const name of [/^Codex/, /^Claude Desktop/, /^ChatGPT/]) fireEvent.click(within(pick).getByRole("checkbox", { name }));
    const box = screen.getByRole("region", { name: "Connector command" });
    expect(within(box).getByText("Command for Claude Desktop and Codex")).toBeTruthy();
    expect(within(box).getByText(/-Assistants claude,codex -Username ana/)).toBeTruthy();
    expect(within(box).getByRole("region", { name: "Set up Claude Desktop" })).toBeTruthy();
    expect(within(box).getByRole("region", { name: "Set up Codex" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Sign in with ChatGPT" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Courses, new course: yes");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ assistant: "mix", assistant_mix: ["claude", "codex", "chatgpt"] });
  });

  it("saves the choice before leaving for ChatGPT, and the sign-in comes back to this page", async () => {
    const calls = mockApi({
      "GET /auth/session": session(),
      "PUT /settings/profile": echo,
      "GET /ai/chatgpt": () => json(200, NOT_CONNECTED),
      "POST /ai/chatgpt/connect": () => json(409, { code: "chatgpt_not_local", message: "Open it at http://127.0.0.1." }),
    });
    renderAt("/welcome");
    const pick = await screen.findByRole("group", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    fireEvent.click(within(pick).getByRole("checkbox", { name: /^ChatGPT/ }));
    expect(screen.queryByRole("region", { name: "Connector command" })).toBeNull(); // ChatGPT needs no command
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with ChatGPT" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/ai/chatgpt/connect"))).toBe(true));
    const writes = calls.filter((c) => c.method !== "GET");
    expect(writes.map((c) => c.method)).toEqual(["PUT", "POST"]);
    expect(writes[0]?.body).toEqual({ assistant: "chatgpt" });
    expect(writes[1]?.url).toContain("/ai/chatgpt/connect?back=welcome");
  });

  it("shows the saved choice and the sign-in result when ChatGPT sends the learner back", async () => {
    mockApi({
      "GET /auth/session": session({ ...USER, assistant: "chatgpt" }),
      "GET /ai/chatgpt": () => json(200, { ...NOT_CONNECTED, connected: true, plan_usage: true }),
    });
    renderAt("/welcome?chatgpt=connected");
    await screen.findByText(/Signed in with ChatGPT/);
    const pick = screen.getByRole("group", { name: "Choose your assistant" });
    expect((within(pick).getByRole("checkbox", { name: /^ChatGPT/ }) as HTMLInputElement).checked).toBe(true);
  });

  it("lets the learner continue without an assistant", async () => {
    const calls = mockApi({ "GET /auth/session": session(), "PUT /settings/profile": echo });
    renderAt("/welcome");
    await screen.findByRole("group", { name: "Choose your assistant" });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/auth/session"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Courses, new course: yes");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ assistant: null });
    expect(fill("Grades from {assistant} are estimates.", assistantWords("antigravity"))).toBe("Grades from Antigravity are estimates.");
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
