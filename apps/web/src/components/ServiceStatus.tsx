import { useQuery } from "@tanstack/react-query";
import { API } from "../api";
import { dateTime } from "../format";

/**
 * Whether RecallSpring's background programs run (owner decision 2026-11-22: they run without a window). The API
 * answers this page, so it runs; the worker is known from its heartbeat (services/api runtime.py).
 */

export interface Readiness {
  status: "ready" | "not_ready";
  checks: { database: boolean; contracts: boolean };
  worker?: { state: "running" | "stopped" | "unknown"; last_seen: string | null };
}

async function readiness(): Promise<Readiness> {
  // 503 still carries the checks, so read the body whatever the status.
  const r = await fetch(`${API}/health/ready`, { credentials: "same-origin" });
  return (await r.json()) as Readiness;
}

export function ServiceStatus() {
  const q = useQuery({ queryKey: ["health", "ready"], queryFn: readiness, refetchInterval: 30_000 });
  if (q.isPending) return <p className="small muted">Checking…</p>;
  if (q.isError) return <p className="notice warn small">RecallSpring did not answer. Run scripts\start-local.ps1 -Restart.</p>;
  const r = q.data;
  const worker = r.worker?.state ?? "unknown";
  const ok = r.status === "ready" && worker === "running";
  return (
    <div className="stack" style={{ gap: 6 }}>
      <p className="small" style={{ margin: 0 }} role="status">
        <span className={`chip ${r.status === "ready" ? "good" : "warn"}`}>API {r.status === "ready" ? "ok" : "database unavailable"}</span>{" "}
        <span className={`chip ${worker === "running" ? "good" : "warn"}`}>
          Worker {worker === "running" ? "running" : worker === "stopped" ? "stopped" : "not seen yet"}
        </span>
      </p>
      {worker === "stopped" && r.worker?.last_seen && (
        <p className="small muted" style={{ margin: 0 }}>
          Last seen {dateTime(r.worker.last_seen)}. Imports and automatic backups wait until it runs again.
        </p>
      )}
      <p className="tiny muted" style={{ margin: 0 }}>
        {ok ? "Both run in the background without a window. " : "Start them with scripts\\start-local.ps1 -Restart. "}
        Status: <code>scripts\start-local.ps1 -Status</code> · logs: <code>scripts\logs.ps1</code> (<code>-Worker</code> for the worker).
      </p>
    </div>
  );
}
