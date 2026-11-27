import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { get, request } from "../api";
import { bytes, dateTime, plural } from "../format";
import { keys } from "../queries";
import type { CloudDevice, DriveView } from "../types";
import { CopyButton } from "./Copy";
import { Confirm, ErrorNote } from "./ui";

/** Settings › Data & backups › Your Google Drive (BYOS, 2026-11-27): a readable copy of the learner's own material,
 * by course, in their own Google account. One way: RecallSpring keeps working from its own copy. */

export const DRIVE_KEY = ["drive"] as const;

type Step = null | "about" | "code" | "manage";

function summary(d: DriveView): string {
  if (d.state === "off") return "Off · a readable copy of your material in your own Google Drive";
  if (d.state === "copying") {
    const p = d.progress;
    return p?.total_files ? `Copying ${Math.min(p.done_files + 1, p.total_files)} of ${p.total_files}` : "Copying…";
  }
  if (d.state === "revoked") return "Stopped: Google Drive no longer allows RecallSpring";
  if (d.state === "failing") return d.error?.message ?? "Copying is failing";
  if (!d.mirror) return "Connected · copying is off";
  const last = d.last_success_at ? ` · last copy ${dateTime(d.last_success_at)}` : "";
  return `Connected · ${plural(d.files ?? 0, "file")}, ${bytes(d.bytes ?? 0)}${last}`;
}

export function DriveRow() {
  const qc = useQueryClient();
  const view = useQuery({
    queryKey: DRIVE_KEY,
    queryFn: () => get<DriveView>("/drive"),
    refetchInterval: (q) => (q.state.data?.state === "copying" ? 2000 : false),
  });
  const d = view.data;
  const [step, setStep] = useState<Step>(null);
  const [device, setDevice] = useState<CloudDevice | null>(null);
  const [outcome, setOutcome] = useState<"denied" | "expired" | null>(null);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const set = (v: DriveView) => {
    qc.setQueryData(DRIVE_KEY, v);
    void qc.invalidateQueries({ queryKey: ["exports"] });
  };

  useEffect(() => {
    if (d?.pending && !device) setDevice(d.pending);
  }, [d?.pending, device]);

  const start = useMutation({
    mutationFn: () => request<CloudDevice>("/drive/start", { method: "POST" }),
    onSuccess: (c) => {
      setDevice(c);
      setOutcome(null);
      setStep("code");
    },
  });
  const cancel = useMutation({ mutationFn: () => request<DriveView>("/drive/cancel", { method: "POST" }), onSuccess: set });
  const options = useMutation({
    mutationFn: (json: { mirror?: boolean; exports?: boolean }) => request<DriveView>("/drive/settings", { method: "POST", json }),
    onSuccess: set,
  });
  const copyExisting = useMutation({
    mutationFn: () => request<DriveView>("/drive/copy-existing", { method: "POST", json: {} }),
    onSuccess: (v) => {
      set(v);
      void qc.invalidateQueries({ queryKey: keys.history });
    },
  });
  const disconnect = useMutation({
    mutationFn: (del: boolean) => request<DriveView>("/drive/disconnect", { method: "POST", json: { delete_files: del } }),
    onSuccess: (v) => {
      set(v);
      setConfirming(false);
      setDeleteFiles(false);
      setStep(null);
      void qc.invalidateQueries({ queryKey: keys.history });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });

  // While the code is shown: ask the server (which asks Google) every `interval` seconds.
  useEffect(() => {
    if (step !== "code" || !device) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await request<{ state: string; drive: DriveView }>("/drive/poll", { method: "POST" });
        if (stop) return;
        if (r.state === "connected") {
          set(r.drive);
          setDevice(null);
          setStep("manage");
          void qc.invalidateQueries({ queryKey: keys.history });
          void qc.invalidateQueries({ queryKey: keys.dashboard });
        } else if (r.state === "denied" || r.state === "expired") {
          setOutcome(r.state);
          setDevice(null);
        }
      } catch {
        /* a dropped request: the next tick asks again */
      }
    };
    const id = window.setInterval(() => void tick(), Math.max(5, device.interval) * 1000);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [step, device]); // eslint-disable-line react-hooks/exhaustive-deps -- set and qc are stable

  if (!d) {
    return (
      <div className="settings-row" id="drive">
        <span>
          <h3 className="settings-row-title">Your Google Drive</h3>
          <span className="small muted">{view.error ? "Could not load." : "…"}</span>
        </span>
      </div>
    );
  }
  const on = d.state !== "off";
  const warn = d.state === "failing" || d.state === "revoked";
  const open = step !== null;
  return (
    <div id="drive">
      <div className="settings-row">
        <span style={{ minWidth: 0 }}>
          <h3 className="settings-row-title">Your Google Drive</h3>
          <span className={`small ${warn ? "warn-text" : "muted"}`}>{summary(d)}</span>
        </span>
        <button
          type="button"
          className="btn small"
          aria-expanded={open}
          onClick={() => {
            if (open) {
              if (step === "code") cancel.mutate();
              setStep(null);
            } else setStep(on ? "manage" : d.pending ? "code" : "about");
          }}
        >
          {open ? "Close" : on ? "Manage" : "Connect"}
        </button>
      </div>

      {step === "about" && (
        <div className="assistant-steps stack" style={{ gap: 10 }}>
          <p className="small" style={{ margin: 0 }}>
            RecallSpring copies each file you add into <strong>My Drive › RecallSpring › your course</strong>, as it is. You can open them there
            any time.
          </p>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>Only the files it creates; nothing else in your Drive</span>
            </li>
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>RecallSpring keeps working from its own copy</span>
            </li>
            <li data-level="warn">
              <span aria-hidden="true">!</span>
              <span>Readable at Google, like any file you keep there</span>
            </li>
          </ul>
          {!d.available && (
            <p className="tiny muted" style={{ margin: 0 }}>
              Not available yet: whoever runs this RecallSpring sets <code>RS_CLOUD_GOOGLE_CLIENT_ID</code> and{" "}
              <code>RS_CLOUD_GOOGLE_CLIENT_SECRET</code> (docs/08 → Your Google Drive).
            </p>
          )}
          {start.error && <ErrorNote error={start.error} />}
          <div className="row">
            <button type="button" className="btn primary small" disabled={!d.available || start.isPending} onClick={() => start.mutate()}>
              Connect Google Drive
            </button>
            <button type="button" className="btn small" onClick={() => setStep(null)}>
              Not now
            </button>
          </div>
        </div>
      )}

      {step === "code" && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby="drive-code-h">
          <h4 id="drive-code-h" className="backup-key-title">
            Sign in to Google
          </h4>
          {device ? (
            <>
              <p className="small" style={{ margin: 0 }}>
                On any device, open{" "}
                <a href={device.verification_url} target="_blank" rel="noreferrer">
                  {device.verification_url.replace(/^https?:\/\/(www\.)?/, "")}
                </a>
                , sign in with your own account and enter:
              </p>
              <code className="recovery-key cloud-code" aria-label="Code to enter at Google">
                {device.user_code}
              </code>
              <p className="tiny muted" style={{ margin: 0 }}>
                The code expires at {dateTime(device.expires_at)}. This page continues by itself when you are done.
              </p>
              <div className="row">
                <CopyButton text={device.user_code} label="Copy code" />
                <button
                  type="button"
                  className="btn small"
                  onClick={() => {
                    cancel.mutate();
                    setStep(null);
                    setDevice(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="small" role="alert" style={{ margin: 0 }}>
                {outcome === "denied" ? "Google did not allow RecallSpring. Nothing was connected." : "The code expired before the sign-in finished."}
              </p>
              <div className="row">
                <button type="button" className="btn primary small" onClick={() => start.mutate()} disabled={start.isPending}>
                  Get a new code
                </button>
                <button type="button" className="btn small" onClick={() => setStep(null)}>
                  Cancel
                </button>
              </div>
            </>
          )}
          {start.error && <ErrorNote error={start.error} />}
        </section>
      )}

      {step === "manage" && on && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-label="Your Google Drive">
          <ul className="folder-checks">
            <li data-level={warn ? "warn" : "ok"}>
              <span aria-hidden="true">{warn ? "!" : "✓"}</span>
              <span>{d.state === "revoked" ? "Not connected any more" : "Connected"} · folder {d.folder}</span>
            </li>
          </ul>
          {d.state === "copying" && d.progress && (
            <p className="small" role="status" style={{ margin: 0 }}>
              Copying {Math.min(d.progress.done_files + 1, d.progress.total_files)} of {d.progress.total_files} · {bytes(d.progress.done_bytes)} of{" "}
              {bytes(d.progress.total_bytes)}
            </p>
          )}
          {warn && d.error && (
            <p className="small warn-text" style={{ margin: 0 }}>
              {d.error.message}
              {d.next_try_at && ` Next try ${dateTime(d.next_try_at)}.`}
            </p>
          )}
          {d.state === "revoked" && (
            <div className="row">
              <button type="button" className="btn primary small" onClick={() => start.mutate()} disabled={start.isPending}>
                Sign in to Google again
              </button>
            </div>
          )}
          <label className="check-row small">
            <input
              type="checkbox"
              checked={d.mirror ?? true}
              disabled={options.isPending}
              onChange={(e) => options.mutate({ mirror: e.target.checked })}
            />
            <span>Copy my material here</span>
          </label>
          {(d.not_yet?.files ?? 0) > 0 && (
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="small">
                Copy what is already here
                <br />
                <span className="tiny muted">
                  {plural(d.not_yet!.files, "file")}, {bytes(d.not_yet!.bytes)}
                  {d.free_bytes != null && ` · ${bytes(d.free_bytes)} free`}
                </span>
              </span>
              <button type="button" className="btn small" disabled={copyExisting.isPending} onClick={() => copyExisting.mutate()}>
                Copy
              </button>
            </div>
          )}
          <label className="check-row small">
            <input
              type="checkbox"
              checked={d.exports ?? false}
              disabled={options.isPending}
              onChange={(e) => options.mutate({ exports: e.target.checked })}
            />
            <span>Exports go here too</span>
          </label>
          {options.error && <ErrorNote error={options.error} />}
          {copyExisting.error && <ErrorNote error={copyExisting.error} />}
          {start.error && <ErrorNote error={start.error} />}
          <fieldset className="plain-choice">
            <legend className="small">Disconnect: RecallSpring forgets the sign-in and asks Google to withdraw it</legend>
            <label className="check-row small">
              <input type="radio" name="drive-files" checked={!deleteFiles} onChange={() => setDeleteFiles(false)} />
              <span>Keep the files in your Google Drive</span>
            </label>
            <label className="check-row small">
              <input type="radio" name="drive-files" checked={deleteFiles} onChange={() => setDeleteFiles(true)} />
              <span>Delete everything RecallSpring made there</span>
            </label>
          </fieldset>
          {disconnect.error && <ErrorNote error={disconnect.error} />}
          <div className="row">
            <button
              type="button"
              className="btn small"
              disabled={disconnect.isPending}
              onClick={() => (deleteFiles ? setConfirming(true) : disconnect.mutate(false))}
            >
              Disconnect
            </button>
          </div>
        </section>
      )}
      <Confirm
        open={confirming}
        title="Delete your Drive copy?"
        confirmLabel="Disconnect and delete"
        danger
        busy={disconnect.isPending}
        onConfirm={() => disconnect.mutate(true)}
        onClose={() => setConfirming(false)}
      >
        The folder RecallSpring in your Google Drive and everything in it ({plural(d.files ?? 0, "file")}
        {d.exports ? " and exports" : ""}) will be deleted. This cannot be undone. Your material in RecallSpring stays. This is recorded in History.
      </Confirm>
    </div>
  );
}
