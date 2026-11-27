import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { AnswersTab } from "./pages/Course";
import { AssistantsPanel } from "./components/Assistants";
import type { AssistantsStatus, ConnectorSettings } from "./types";

beforeAll(() => {
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
  vi.restoreAllMocks();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

type Key = "claude" | "codex" | "antigravity" | "chatgpt";
const item = (key: Key, connected: boolean, last: string | null = null) => ({ key, connected, tokens: connected && key !== "chatgpt" ? 1 : 0, last_used_at: last });
const items = (connected: Key[]) => (["claude", "codex", "antigravity", "chatgpt"] as Key[]).map((k) => item(k, connected.includes(k), connected.includes(k) ? "2026-11-27T09:40:00Z" : null));

const token = (client: string, label: string) => ({
  id: `t-${client}`,
  label,
  client,
  created_at: "2026-11-20T10:00:00Z",
  last_used_at: "2026-11-27T09:40:00Z",
  revoked_at: null,
});

const connector = (extra: Record<string, unknown> = {}): ConnectorSettings =>
  ({ limit_percent: 60, daily_default: 200, daily_limit: 120, used_today: 14, tokens: [token("codex", "Codex laptop")], remote_url: null, ...extra }) as ConnectorSettings;

let codexReached = false; // whether the remote Codex has made its first request (set by a test)

/** Records every request; answers the writes the panel makes. */
function api() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  codexReached = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path === "/settings/profile") return json(200, { id: "u1", username: "demo", timezone: "UTC" });
    if (path === "/settings/connector/tokens") return json(201, { ...token("codex", "Codex · another computer"), id: "t-new", token: "rsc_SECRETEXAMPLE" });
    if (path.endsWith("/disconnect")) return json(200, { client: "codex", revoked: 1 });
    if (path === "/settings/connector") {
      const used = codexReached ? "2026-11-27T09:40:00Z" : null;
      return json(200, connector({ tokens: [{ ...token("codex", "Codex · another computer"), id: "t-new", last_used_at: used }] }));
    }
    return json(404, { code: "not_found", message: path });
  });
  return calls;
}

describe("Settings → Assistants", () => {
  it("shows the tick boxes, a row per ticked assistant and the daily limit", () => {
    api();
    const s: AssistantsStatus = { items: items(["codex"]), in_use: "codex", chosen: "mix", mix: ["claude", "codex"] };
    wrap(<AssistantsPanel s={s} c={connector()} />);
    const tiles = screen.getByRole("group", { name: "Assistants you use" });
    expect(within(tiles).getByRole("checkbox", { name: "Claude Desktop" })).toHaveProperty("checked", true);
    expect(within(tiles).getByRole("checkbox", { name: "ChatGPT" })).toHaveProperty("checked", false);
    expect(screen.getByRole("heading", { level: 3, name: "Codex" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Manage Codex" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Set up Claude Desktop" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 3, name: "ChatGPT" })).toBeNull();
    expect(screen.getByText(/60 % · 120 requests a day for all assistants together · 14 used today/)).toBeTruthy();
    expect(screen.getByText(/RecallSpring names Codex in its tips/)).toBeTruthy();
  });

  it("opens the setup steps in place; another computer needs an address", () => {
    api();
    const s: AssistantsStatus = { items: items([]), in_use: "claude", chosen: "claude" };
    wrap(<AssistantsPanel s={s} c={connector()} />);
    const setUp = screen.getByRole("button", { name: "Set up Claude Desktop" });
    fireEvent.click(setUp);
    expect(setUp.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(/install-claude-desktop-connector\.ps1/)).toBeTruthy();
    expect(screen.getByText(/RecallSpring needs an address other computers can reach/)).toBeTruthy();
    fireEvent.click(setUp);
    expect(screen.queryByText(/install-claude-desktop-connector\.ps1/)).toBeNull();
  });

  it("sets up Codex on another computer with a token and the address", async () => {
    api();
    const s: AssistantsStatus = { items: items([]), in_use: "codex", chosen: "codex" };
    wrap(<AssistantsPanel s={s} c={connector({ tokens: [], remote_url: "https://study.example.org/mcp" })} />);
    fireEvent.click(screen.getByRole("button", { name: "Set up Codex" }));
    fireEvent.click(screen.getByRole("button", { name: "From another computer" }));
    expect(screen.getByText(/url = "https:\/\/study\.example\.org\/mcp"/)).toBeTruthy();
    expect(screen.getByText(/bearer_token_env_var = "RECALLSPRING_TOKEN"/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make a token for Codex" }));
    expect(await screen.findByText('setx RECALLSPRING_TOKEN "rsc_SECRETEXAMPLE"')).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    expect(screen.getByText(/Waiting for Codex/)).toBeTruthy();
    codexReached = true;
    // The new token's first use (a server time) is newer than any use when the check began.
    expect(await screen.findByText(/Connected: Codex reached RecallSpring/, {}, { timeout: 4500 })).toBeTruthy(); // polled every 3 s
  });

  it("says Claude needs a public address to connect from another computer", () => {
    api();
    const s: AssistantsStatus = { items: items([]), in_use: "claude", chosen: "claude" };
    wrap(<AssistantsPanel s={s} c={connector({ remote_url: "https://study.example.org/mcp", remote_from_internet: false })} />);
    fireEvent.click(screen.getByRole("button", { name: "Set up Claude Desktop" }));
    fireEvent.click(screen.getByRole("button", { name: "From another computer" }));
    expect(screen.getByText(/has no public address, so Claude cannot reach it/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Make a token for Claude Desktop" })).toBeNull();
  });

  it("asks before unticking a connected assistant, and can disconnect it too", async () => {
    const calls = api();
    const s: AssistantsStatus = { items: items(["codex"]), in_use: "codex", chosen: "mix", mix: ["claude", "codex"] };
    wrap(<AssistantsPanel s={s} c={connector()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Codex" }));
    expect(screen.getByText(/Codex is still connected \(1 token\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Also disconnect" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/settings/profile")).toBe(true));
    const writes = calls.filter((c) => c.method !== "GET");
    expect(writes.map((c) => c.path)).toEqual(["/settings/connector/clients/codex/disconnect", "/settings/profile"]);
    expect(writes[1]!.body).toEqual({ assistant: "claude" });
  });

  it("keeps a connected assistant connected when asked", async () => {
    const calls = api();
    const s: AssistantsStatus = { items: items(["codex"]), in_use: "codex", chosen: "mix", mix: ["claude", "codex"] };
    wrap(<AssistantsPanel s={s} c={connector()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Codex" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep it connected" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/settings/profile")).toBe(true));
    expect(calls.some((c) => c.path.endsWith("/disconnect"))).toBe(false);
    // Still connected, so its row stays, marked as not in the list.
    expect(screen.getByText("Not in your list")).toBeTruthy();
  });
});

describe("Course → Answers", () => {
  it("opens the exact answer and the grade explanation", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
      const path = url.pathname.replace("/api/v1", "");
      if (path === "/attempts") {
        return json(200, [
          {
            attempt_id: "a1",
            course_id: "k1",
            question: "Explain attack surface vs attack vector.",
            question_type: "open",
            bloom_level: 2,
            kind: "answer",
            captured_via: "answer_form",
            status: "evaluated",
            submitted_at: "2026-11-22T09:18:00Z",
            quiz_id: null,
            grade: 4,
            assessment_status: "final",
            graded_by: "ai",
            grader: { name: "Codex", model: "GPT-6" },
          },
        ]);
      }
      if (path === "/attempts/a1") {
        return json(200, {
          id: "a1",
          question_id: "q1",
          kind: "answer",
          answer_text: "Login form = surface; SQL injection = vector.",
          answer_mode: "closed_notes",
          captured_via: "answer_form",
          status: "evaluated",
          submitted_at: "2026-11-22T09:18:00Z",
          effective_assessment_id: "s1",
          assessments: [
            {
              id: "s1",
              evaluator_kind: "ai",
              provider: "codex_app",
              model: "GPT-6",
              status: "final",
              grade: 4,
              confidence: "high",
              feedback: "You separated the two correctly.",
              evidence_refs: ["sec1"],
              strengths: ["Correct example for each"],
              gaps: [],
              remediation: null,
              factuality_flags: [],
              created_at: "2026-11-22T09:18:30Z",
            },
          ],
        });
      }
      return json(404, { code: "not_found", message: path });
    });
    wrap(<AnswersTab courseId="k1" />);
    const toggle = await screen.findByRole("button", { name: /Explain attack surface/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(await screen.findByText("Login form = surface; SQL injection = vector.")).toBeTruthy();
    expect(screen.getByText("You separated the two correctly.")).toBeTruthy();
    expect(screen.getByText("Correct example for each")).toBeTruthy();
    expect(screen.getByText(/Codex · GPT-6 · confidence high · based on 1 passage of your material/)).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });
});
