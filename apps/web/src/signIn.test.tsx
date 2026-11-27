import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SignInRows } from "./components/SignInRows";
import { LoginPage } from "./pages/Login";
import { b64urlToBytes, bytesToB64url, credentialJson, onIpAddress, passkeyAddress } from "./passkey";
import type { PasskeyItem, SignInView } from "./types";

const laptop: PasskeyItem = {
  id: "p1",
  name: "Windows Hello",
  address: "localhost",
  synced: false,
  created_at: "2026-11-27T09:00:00+00:00",
  last_used_at: new Date().toISOString(),
};

function view(passkeys: PasskeyItem[] = [], confirmed = false): SignInView {
  return {
    remote_host: null,
    password_changed_at: "2026-11-20T09:00:00+00:00",
    password_changed: false,
    passkeys,
    confirmed_until: confirmed ? new Date(Date.now() + 240_000).toISOString() : null,
  };
}

const bytes = (...n: number[]) => new Uint8Array(n).buffer;

function fakeCredential(kind: "create" | "get"): PublicKeyCredential {
  const response =
    kind === "create"
      ? { clientDataJSON: bytes(1), attestationObject: bytes(2), getTransports: () => ["internal"] }
      : { clientDataJSON: bytes(1), authenticatorData: bytes(3), signature: bytes(4), userHandle: bytes(5) };
  return {
    id: "AQI",
    rawId: bytes(1, 2),
    type: "public-key",
    response,
    authenticatorAttachment: "platform",
    getClientExtensionResults: () => ({}),
  } as unknown as PublicKeyCredential;
}

let create: ReturnType<typeof vi.fn>;
let getCred: ReturnType<typeof vi.fn>;

beforeEach(() => {
  create = vi.fn(async () => fakeCredential("create"));
  getCred = vi.fn(async () => fakeCredential("get"));
  vi.stubGlobal("PublicKeyCredential", Object.assign(function PublicKeyCredential() {}, { isConditionalMediationAvailable: async () => false }));
  Object.defineProperty(navigator, "credentials", { configurable: true, value: { create, get: getCred } });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

type Route = (body: unknown, method: string) => unknown;

function serve(routes: Record<string, Route>) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, url, body });
    const hit = Object.entries(routes)
      .filter(([path]) => url.endsWith(path) || url.includes(`${path}?`))
      .sort((a, b) => b[0].length - a[0].length)[0];
    if (!hit) return new Response(JSON.stringify({ code: "not_found", message: "Not found." }), { status: 404 });
    const out = hit[1](body, method);
    if (out instanceof Response) return out;
    return new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

function renderWith(node: React.ReactNode, path = "/settings") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["session"], { user: { username: "alex" }, expires_at: "2026-11-28T09:00:00+00:00" });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const options = { challenge_id: "c1", options: { challenge: "AQID", rpId: "localhost", rp: { id: "localhost", name: "RecallSpring" }, user: { id: "BAU", name: "alex", displayName: "alex" } } };

describe("passkey helpers", () => {
  it("round-trips base64url and builds the server's JSON", () => {
    expect(bytesToB64url(b64urlToBytes("AQID_-8"))).toBe("AQID_-8");
    const json = credentialJson(fakeCredential("get"));
    expect(json.rawId).toBe("AQI");
    expect(json.response).toEqual({ clientDataJSON: "AQ", authenticatorData: "Aw", signature: "BA", userHandle: "BQ" });
    expect((credentialJson(fakeCredential("create")).response as Record<string, unknown>).transports).toEqual(["internal"]);
  });

  it("knows where passkeys work", () => {
    expect(onIpAddress("127.0.0.1")).toBe(true);
    expect(onIpAddress("localhost")).toBe(false);
    expect(passkeyAddress(null, "localhost")).toBe(true);
    expect(passkeyAddress(null, "demo.localhost")).toBe(true);
    expect(passkeyAddress("study.example.org", "study.example.org")).toBe(true);
    expect(passkeyAddress(null, "study.example.org")).toBe(false);
  });
});

describe("Login with a passkey", () => {
  it("signs in with the button", async () => {
    const calls = serve({
      "/auth/setup": () => ({ needs_setup: false, refusal: null }),
      "/auth/passkey/login/options": () => options,
      "/auth/passkey/login": () => ({ user: { username: "alex" }, expires_at: "2026-11-28T09:00:00+00:00" }),
    });
    renderWith(<LoginPage />, "/login");
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with a passkey" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/passkey/login"))).toBe(true));
    const finish = calls.find((c) => c.url.endsWith("/auth/passkey/login"))!;
    expect(finish.body).toMatchObject({ challenge_id: "c1", credential: { rawId: "AQI", type: "public-key" } });
    expect(getCred.mock.calls[0]![0].publicKey.challenge).toBeInstanceOf(ArrayBuffer);
  });

  it("says so in one line when the passkey is cancelled", async () => {
    getCred.mockRejectedValueOnce(new DOMException("no", "NotAllowedError"));
    serve({ "/auth/setup": () => ({ needs_setup: false, refusal: null }), "/auth/passkey/login/options": () => options });
    renderWith(<LoginPage />, "/login");
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with a passkey" }));
    expect((await screen.findByRole("alert")).textContent).toContain("cancelled or timed out");
    expect(screen.getByLabelText("Password")).toBeTruthy();
  });

  it("has no passkey button where the browser has no passkeys", async () => {
    vi.stubGlobal("PublicKeyCredential", undefined);
    serve({ "/auth/setup": () => ({ needs_setup: false, refusal: null }) });
    renderWith(<LoginPage />, "/login");
    await screen.findByRole("button", { name: "Sign in" });
    expect(screen.queryByRole("button", { name: "Sign in with a passkey" })).toBeNull();
  });
});

describe("Settings › Sign-in", () => {
  it("shows the three rows", async () => {
    serve({ "/auth/passkeys": () => view([laptop]) });
    renderWith(<SignInRows />);
    expect(await screen.findByText(/1 passkey · last used today on localhost/)).toBeTruthy();
    expect(screen.getByText(/Set 20 Nov 2026 · the fallback/)).toBeTruthy();
    expect(screen.getByText("Signed in as alex on this browser")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Password", "Passkeys", "Sign out"]);
  });

  it("asks to confirm, then adds and names a passkey", async () => {
    let current = view();
    const calls = serve({
      "/auth/passkeys": (_b, method) => (method === "POST" ? { passkey: laptop, sign_in: (current = view([laptop], true)) } : current),
      "/auth/confirm": () => (current = view([], true)),
      "/auth/passkeys/options": () => options,
      "/auth/passkeys/p1": (body) => (current = view([{ ...laptop, name: (body as { name: string }).name }], true)),
    });
    renderWith(<SignInRows />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    expect(await screen.findByRole("heading", { name: "Confirm it is you" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use a passkey instead" })).toBeNull(); // none at this address yet
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "the password" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Passkey added" })).toBeTruthy();
    expect(screen.getByText("Only on this device (not synced)")).toBeTruthy();
    expect(calls.find((c) => c.url.endsWith("/auth/confirm"))?.body).toEqual({ password: "the password" });
    expect(create).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Work laptop" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Work laptop" }));
  });

  it("removes a passkey only after asking", async () => {
    const calls = serve({
      "/auth/passkeys": () => view([laptop], true),
      "/auth/passkeys/p1": () => view([], true),
    });
    renderWith(<SignInRows />);
    fireEvent.click(await screen.findByRole("button", { name: "Manage" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Windows Hello" }));
    const ask = screen.getByRole("alertdialog", { name: "Remove passkey" });
    expect(ask.textContent).toContain("the password still works");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(within(ask).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/auth/passkeys/p1"))).toBe(true));
  });

  it("changes the password after checking the two fields", async () => {
    const calls = serve({ "/auth/passkeys": () => view(), "/auth/password": () => ({ ...view(), password_changed: true }) });
    renderWith(<SignInRows />);
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "old one" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "a long new password" } });
    fireEvent.change(screen.getByLabelText("New password again"), { target: { value: "a long new passwrd" } });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(screen.getByRole("alert").textContent).toContain("do not match");
    fireEvent.change(screen.getByLabelText("New password again"), { target: { value: "a long new password" } });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByText(/Other browsers and devices are signed out/)).toBeTruthy();
    expect(calls.find((c) => c.url.endsWith("/auth/password"))?.body).toEqual({ current_password: "old one", new_password: "a long new password" });
  });
});
