/**
 * Same-origin client for the RecallSpring API. The session cookie is HttpOnly; writes echo the readable
 * `rs_csrf` cookie in `X-CSRF-Token` (double submit) and carry a fresh `Idempotency-Key`.
 */

export const API = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | undefined;
  readonly requestId: string | undefined;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

function csrfToken(): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith("rs_csrf="));
  return match ? decodeURIComponent(match.slice("rs_csrf=".length)) : "";
}

export function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6]! & 0x0f) | 0x40;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const h = Array.from(b, (x: number) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

let onUnauthenticated: (() => void) | null = null;

export function setUnauthenticatedHandler(fn: () => void): void {
  onUnauthenticated = fn;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  json?: unknown;
  form?: FormData;
  key?: string;
  params?: Record<string, string | number | undefined | null>;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.json !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (method !== "GET") {
    headers["X-CSRF-Token"] = csrfToken();
    headers["Idempotency-Key"] = opts.key ?? newKey();
  }
  if (opts.form) body = opts.form;
  else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.params ?? {})) if (v !== undefined && v !== null) query.set(k, String(v));
  const qs = query.toString();
  let res: Response;
  try {
    res = await fetch(`${API}${path}${qs ? `?${qs}` : ""}`, { method, headers, body, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "offline", "RecallSpring is not reachable. Check that the local server is running.");
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const e = (data ?? {}) as { code?: string; message?: string; details?: Record<string, unknown>; request_id?: string };
    if (res.status === 401 && path !== "/auth/login") onUnauthenticated?.();
    throw new ApiError(res.status, e.code ?? "error", e.message ?? `Request failed (${res.status}).`, e.details, e.request_id);
  }
  return data as T;
}

export const get = <T>(path: string, params?: RequestOptions["params"]) => request<T>(path, { params });
