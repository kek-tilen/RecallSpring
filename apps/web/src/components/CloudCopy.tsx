import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { request } from "../api";
import { bytes, dateTime, plural } from "../format";
import { keys } from "../queries";
import type { BackupStatus, CloudDevice, CloudView } from "../types";
import { CopyButton } from "./Copy";
import { Confirm, ErrorNote } from "./ui";

/** Settings › Data & backups › Cloud copy (2026-11-27): the encrypted backups to Google Drive, with no sync app.
 * Sign-in with a short code on any device; RecallSpring sees only the files it made. */

type Step = null | "choose" | "code" | "connected" | "manage";

function summary(c: CloudView): string {
  if (c.state === "off") return "Off · backups stay on this computer";
  const name = "Google Drive";
  if (c.state === "copying") {
    const p = c.progress;
    return p && p.total_files ? `${name} · copying ${Math.min(p.done_files + 1, p.total_files)} of ${p.total_files}` : `${name} · copying…`;
  }
  if (c.state === "revoked") return `${name} · stopped: Google Drive no longer allows RecallSpring`;
  if (c.state === "failing") return `${name} · ${c.last_success_at ? `last copy ${dateTime(c.last_success_at)}` : "not copied yet"} · ${c.error?.message ?? ""}`;
  if (c.state === "waiting" || !c.last_success_at) return `${name} · the first copy starts soon`;
  return `${name} · copied ${dateTime(c.last_success_at)} · ${plural(c.backups ?? 0, "backup")}, ${bytes(c.bytes ?? 0)}`;
}

function Progress({ c }: { c: CloudView }) {
  const p = c.progress;
  if (c.state !== "copying") return null;
  return (
    <p className="small" role="status" style={{ margin: 0 }}>
      {p && p.total_files
        ? `Copying ${Math.min(p.done_files + 1, p.total_files)} of ${p.total_files} · ${bytes(p.done_bytes)} of ${bytes(p.total_bytes)}`
        : "Copying…"}
    </p>
  );
}

export function CloudCopyRow({ b }: { b: BackupStatus }) {
  const qc = useQueryClient();
  const c = b.cloud;
  const [step, setStep] = useState<Step>(null);
  const [device, setDevice] = useState<CloudDevice | null>(c?.pending ?? null);
  const [outcome, setOutcome] = useState<"denied" | "expired" | null>(null);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const setView = (v: BackupStatus) => qc.setQueryData(keys.backup, v);

  const start = useMutation({
    mutationFn: () => request<CloudDevice>("/settings/backup/cloud/google/start", { method: "POST" }),
    onSuccess: (d) => {
      setDevice(d);
      setOutcome(null);
      setStep("code");
    },
  });
  const cancel = useMutation({
    mutationFn: () => request<BackupStatus>("/settings/backup/cloud/cancel", { method: "POST" }),
    onSuccess: setView,
  });
  const copyNow = useMutation({
    mutationFn: () => request<BackupStatus>("/settings/backup/cloud/copy", { method: "POST", json: {} }),
    onSuccess: setView,
  });
  const disconnect = useMutation({
    mutationFn: (del: boolean) => request<BackupStatus>("/settings/backup/cloud/disconnect", { method: "POST", json: { delete_files: del } }),
    onSuccess: (v) => {
      setView(v);
      setConfirming(false);
      setDeleteFiles(false);
      setStep(null);
      void qc.invalidateQueries({ queryKey: keys.history });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
  const signInAgain = useMutation({
    mutationFn: async () => {
      setView(await request<BackupStatus>("/settings/backup/cloud/disconnect", { method: "POST", json: { delete_files: false } }));
      return request<CloudDevice>("/settings/backup/cloud/google/start", { method: "POST" });
    },
    onSuccess: (d) => {
      setDevice(d);
      setOutcome(null);
      setStep("code");
    },
  });

  // While the code is shown: ask the server (which asks Google) every `interval` seconds.
  useEffect(() => {
    if (step !== "code" || !device) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await request<{ state: string; backup: BackupStatus }>("/settings/backup/cloud/google/poll", { method: "POST" });
        if (stop) return;
        if (r.state === "connected") {
          setView(r.backup);
          setStep("connected");
          void qc.invalidateQueries({ queryKey: keys.history });
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
  }, [step, device, qc]);

  // While copying: follow the progress.
  const copying = c?.state === "copying";
  useEffect(() => {
    if (!copying) return;
    const id = window.setInterval(() => void qc.invalidateQueries({ queryKey: keys.backup }), 2000);
    return () => window.clearInterval(id);
  }, [copying, qc]);

  if (!c) return null;
  const on = c.state !== "off";
  const encrypted = b.encryption.on;
  const warn = c.state === "failing" || c.state === "revoked";
  const open = step !== null;
  return (
    <div id="cloud-copy">
      <div className="settings-row">
        <span style={{ minWidth: 0 }}>
          <h3 className="settings-row-title">Cloud copy</h3>
          <span className={`small ${warn ? "warn-text" : "muted"}`}>{summary(c)}</span>
        </span>
        {b.can_change &&
          (!on && !encrypted ? (
            <a className="small" href="#backup-encryption">
              Turn on encryption first
            </a>
          ) : (
            <button
              type="button"
              className="btn small"
              aria-expanded={open}
              onClick={() => {
                if (open) {
                  if (step === "code") cancel.mutate();
                  setStep(null);
                } else setStep(on ? "manage" : "choose");
              }}
            >
              {open ? "Close" : on ? "Manage" : "Connect"}
            </button>
          ))}
      </div>

      {step === "choose" && (
        <div className="assistant-steps stack" style={{ gap: 10 }}>
          <p className="small" style={{ margin: 0 }}>
            RecallSpring uploads each encrypted backup after it is checked. It can touch only its own folder.
          </p>
          <div className="welcome-tiles cloud-tiles" aria-label="Where the copy goes" role="group">
            <button
              type="button"
              className="welcome-tile"
              disabled={!c.available.google || start.isPending}
              onClick={() => start.mutate()}
            >
              <strong>Google Drive</strong>
              <span className="tiny muted">{c.available.google ? "A folder in My Drive you can see" : "Needs a Google app ID in the server settings"}</span>
            </button>
            <div className="welcome-tile" aria-disabled="true">
              <strong>OneDrive</strong>
              <span className="tiny muted">Later</span>
            </div>
            <div className="welcome-tile" aria-disabled="true">
              <strong>Dropbox</strong>
              <span className="tiny muted">Later</span>
            </div>
            <div className="welcome-tile" aria-disabled="true">
              <strong>iCloud Drive</strong>
              <span className="tiny muted">Only through a synced folder (Where backups go)</span>
            </div>
          </div>
          {!c.available.google && (
            <p className="tiny muted" style={{ margin: 0 }}>
              Whoever runs this RecallSpring sets <code>RS_CLOUD_GOOGLE_CLIENT_ID</code> and <code>RS_CLOUD_GOOGLE_CLIENT_SECRET</code>{" "}
              (docs/08 → Cloud copy).
            </p>
          )}
          {start.error && <ErrorNote error={start.error} />}
          <div className="row">
            <button type="button" className="btn small" onClick={() => setStep(null)}>
              Not now
            </button>
          </div>
        </div>
      )}

      {step === "code" && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby="cloud-code-h">
          <h4 id="cloud-code-h" className="backup-key-title">
            Sign in to Google
          </h4>
          {device ? (
            <>
              <p className="small" style={{ margin: 0 }}>
                On any device, open{" "}
                <a href={device.verification_url} target="_blank" rel="noreferrer">
                  {device.verification_url.replace(/^https?:\/\/(www\.)?/, "")}
                </a>
                , sign in and enter:
              </p>
              <code className="recovery-key cloud-code" aria-label="Code to enter at Google">
                {device.user_code}
              </code>
              <ul className="folder-checks">
                <li data-level="ok">
                  <span aria-hidden="true">✓</span>
                  <span>Google will ask to let RecallSpring use only files it creates</span>
                </li>
              </ul>
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

      {step === "connected" && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby="cloud-done-h">
          <h4 id="cloud-done-h" className="backup-key-title">
            Connected
          </h4>
          <p className="small" style={{ margin: 0 }}>
            Google Drive, as the account you signed in with. Your encrypted backups are copied now, then after every backup.
          </p>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>Folder: My Drive › RecallSpring backups</span>
            </li>
            {c.free_bytes != null && (
              <li data-level="ok">
                <span aria-hidden="true">✓</span>
                <span>Room: {bytes(c.free_bytes)} free</span>
              </li>
            )}
            {b.unencrypted_snapshots > 0 && (
              <li data-level="ok">
                <span aria-hidden="true">✓</span>
                <span>Older backups that are not encrypted stay on this computer only</span>
              </li>
            )}
          </ul>
          <Progress c={c} />
          {c.state === "failing" && c.error && <p className="small warn-text" style={{ margin: 0 }}>{c.error.message}</p>}
          <div className="row">
            <button type="button" className="btn primary small" onClick={() => setStep(null)}>
              Done
            </button>
          </div>
        </section>
      )}

      {step === "manage" && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-label="Cloud copy">
          <dl className="kv">
            <dt>Where</dt>
            <dd>Google Drive › My Drive › RecallSpring backups</dd>
            <dt>Last copy</dt>
            <dd>{c.last_success_at ? `${dateTime(c.last_success_at)} · ${plural(c.backups ?? 0, "backup")} · ${bytes(c.bytes ?? 0)}` : "Not yet"}</dd>
            {c.free_bytes != null && (
              <>
                <dt>Room</dt>
                <dd>{bytes(c.free_bytes)} free</dd>
              </>
            )}
            {c.next_try_at && (
              <>
                <dt>Next try</dt>
                <dd>{dateTime(c.next_try_at)}</dd>
              </>
            )}
          </dl>
          <Progress c={c} />
          {c.error && <p className={`small ${c.state === "revoked" ? "warn-text" : ""}`} style={{ margin: 0 }}>{c.error.message}</p>}
          {copyNow.error && <ErrorNote error={copyNow.error} />}
          {signInAgain.error && <ErrorNote error={signInAgain.error} />}
          <div className="row">
            {c.state === "revoked" ? (
              <button type="button" className="btn primary small" onClick={() => signInAgain.mutate()} disabled={signInAgain.isPending}>
                Sign in to Google again
              </button>
            ) : (
              <button type="button" className="btn small" onClick={() => copyNow.mutate()} disabled={copyNow.isPending || copying}>
                Copy now
              </button>
            )}
          </div>
          <fieldset className="plain-choice">
            <legend className="small">Disconnect: RecallSpring forgets the sign-in and asks Google to withdraw it</legend>
            <label className="check-row small">
              <input type="radio" name="cloud-files" checked={!deleteFiles} onChange={() => setDeleteFiles(false)} />
              <span>Keep the files in Google Drive</span>
            </label>
            <label className="check-row small">
              <input type="radio" name="cloud-files" checked={deleteFiles} onChange={() => setDeleteFiles(true)} />
              <span>Delete them too</span>
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
        title="Delete the cloud copy?"
        confirmLabel="Disconnect and delete"
        danger
        busy={disconnect.isPending}
        onConfirm={() => disconnect.mutate(true)}
        onClose={() => setConfirming(false)}
      >
        The folder RecallSpring backups in your Google Drive and every backup in it will be deleted. This cannot be undone. The backups on this
        computer stay. This is recorded in History.
      </Confirm>
    </div>
  );
}
