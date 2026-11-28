import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, get, request } from "../api";
import { bytes, dateTime, plural } from "../format";
import { keys } from "../queries";
import { isDropbox, PROVIDER_LABEL, type CloudDevice, type CloudProvider, type DriveView, type DropboxPending } from "../types";
import { COMPANY, DeviceSignIn, MissingSettings, withdrawText, type DeviceOutcome, type DeviceProvider } from "./CloudSignIn";
import { DropboxSignIn } from "./DropboxSignIn";
import { SyncedFolderStep } from "./SyncedFolder";
import { Confirm, ErrorNote } from "./ui";

/** Settings › Data & backups › Your cloud folder (BYOS, 2026-11-27; Dropbox, OneDrive and a synced folder 2026-11-28):
 * a readable copy of the learner's own material, by course, in their own Google Drive, Dropbox or OneDrive, or in a
 * subfolder of the synced folder the first account chose. One way: RecallSpring keeps working from its own copy. One
 * provider at a time. */

export const DRIVE_KEY = ["drive"] as const;

type Step = null | "about" | "folder" | "choose-folder" | "code" | "paste" | "manage";

const FOLDER: Record<Exclude<CloudProvider, "folder">, string> = {
  google: "My Drive › RecallSpring › your course",
  dropbox: "Dropbox › Apps › RecallSpring › Material › your course",
  onedrive: "OneDrive › Apps › RecallSpring › Material › your course",
};

function summary(d: DriveView): string {
  if (d.state === "off") return "Off · a readable copy of your material in your own Google Drive, Dropbox, OneDrive or a synced folder";
  if (d.state === "copying") {
    const p = d.progress;
    return p?.total_files ? `Copying ${Math.min(p.done_files + 1, p.total_files)} of ${p.total_files}` : "Copying…";
  }
  if (d.state === "revoked") return `Stopped: ${PROVIDER_LABEL[d.provider ?? "google"]} no longer allows RecallSpring`;
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
  const [dropbox, setDropbox] = useState<DropboxPending | null>(null);
  const [dropboxExpired, setDropboxExpired] = useState(false);
  const [outcome, setOutcome] = useState<DeviceOutcome | null>(null);
  const [signing, setSigning] = useState<DeviceProvider>("google");
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const set = (v: DriveView) => {
    qc.setQueryData(DRIVE_KEY, v);
    void qc.invalidateQueries({ queryKey: ["exports"] });
  };

  useEffect(() => {
    if (!d?.pending) return;
    if (isDropbox(d.pending)) {
      if (!dropbox) setDropbox(d.pending);
    } else if (!device) {
      setDevice(d.pending);
      setSigning(d.pending.provider ?? "google");
    }
  }, [d?.pending, device, dropbox]);

  const start = useMutation({
    mutationFn: (p: DeviceProvider) => request<CloudDevice>(p === "google" ? "/drive/start" : `/drive/${p}/start`, { method: "POST" }),
    onSuccess: (c, p) => {
      setDevice(c);
      setSigning(p);
      setOutcome(null);
      setStep("code");
    },
  });
  const startDropbox = useMutation({
    mutationFn: () => request<DropboxPending>("/drive/dropbox/start", { method: "POST" }),
    onSuccess: (p) => {
      setDropbox(p);
      setDropboxExpired(false);
      setStep("paste");
    },
  });
  const finishDropbox = useMutation({
    mutationFn: (code: string) => request<{ state: string; drive: DriveView }>("/drive/dropbox/finish", { method: "POST", json: { code } }),
    onSuccess: (r) => {
      set(r.drive);
      setDropbox(null);
      setStep("manage");
      void qc.invalidateQueries({ queryKey: keys.history });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "drive_expired") setDropboxExpired(true);
    },
  });
  const cancel = useMutation({ mutationFn: () => request<DriveView>("/drive/cancel", { method: "POST" }), onSuccess: set });
  const connectFolder = useMutation({
    mutationFn: () => request<{ state: string; drive: DriveView }>("/drive/folder/connect", { method: "POST" }),
    onSuccess: (r) => {
      set(r.drive);
      setStep("manage");
      void qc.invalidateQueries({ queryKey: keys.history });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
  const chooseFolder = useMutation({
    mutationFn: (path: string | null) => request<DriveView>("/drive/folder", { method: "PUT", json: { path } }),
    onSuccess: (v) => {
      set(v);
      setStep("about");
      void qc.invalidateQueries({ queryKey: keys.history });
    },
  });
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

  // While the code is shown: ask the server (which asks Google or Microsoft) every `interval` seconds.
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
        } else if (r.state !== "pending") {
          setOutcome(r.state as DeviceOutcome);
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
          <h3 className="settings-row-title">Your cloud folder</h3>
          <span className="small muted">{view.error ? "Could not load." : "…"}</span>
        </span>
      </div>
    );
  }
  const on = d.state !== "off";
  const warn = d.state === "failing" || d.state === "revoked";
  const open = step !== null;
  const provider: CloudProvider = d.provider ?? "google";
  const label = provider === "folder" ? "synced folder" : PROVIDER_LABEL[provider];
  const company = COMPANY[provider];
  const sf = d.synced_folder;
  return (
    <div id="drive">
      <div className="settings-row">
        <span style={{ minWidth: 0 }}>
          <h3 className="settings-row-title">Your cloud folder</h3>
          <span className={`small ${warn ? "warn-text" : "muted"}`}>{summary(d)}</span>
        </span>
        <button
          type="button"
          className="btn small"
          aria-expanded={open}
          onClick={() => {
            if (open) {
              if (step === "code" || step === "paste") cancel.mutate();
              setStep(null);
            } else setStep(on ? "manage" : d.pending ? (isDropbox(d.pending) ? "paste" : "code") : "about");
          }}
        >
          {open ? "Close" : on ? "Manage" : "Connect"}
        </button>
      </div>

      {step === "about" && (
        <div className="assistant-steps stack" style={{ gap: 10 }}>
          <p className="small" style={{ margin: 0 }}>
            RecallSpring copies each file you add into a folder for each course, as it is. You can open them there any time:
          </p>
          <ul className="small" style={{ margin: 0, paddingLeft: "1.2rem" }}>
            <li>
              Google Drive: <strong>{FOLDER.google}</strong>
            </li>
            <li>
              Dropbox: <strong>{FOLDER.dropbox}</strong>
            </li>
            <li>
              OneDrive: <strong>{FOLDER.onedrive}</strong>
            </li>
            {sf?.mine && (
              <li>
                A synced folder: <strong>{sf.mine} › your course</strong>
              </li>
            )}
          </ul>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>Only the files it creates (Google Drive) or its own folder (Dropbox, OneDrive); nothing else</span>
            </li>
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>RecallSpring keeps working from its own copy</span>
            </li>
            <li data-level="warn">
              <span aria-hidden="true">!</span>
              <span>Readable at Google, Dropbox or Microsoft, like any file you keep there</span>
            </li>
          </ul>
          <MissingSettings available={d.available} where="docs/08 → Your cloud folder" />
          {start.error && <ErrorNote error={start.error} />}
          {startDropbox.error && <ErrorNote error={startDropbox.error} />}
          <div className="row">
            <button
              type="button"
              className="btn primary small"
              disabled={!d.available.google || start.isPending}
              onClick={() => start.mutate("google")}
            >
              Connect Google Drive
            </button>
            <button
              type="button"
              className="btn primary small"
              disabled={!d.available.dropbox || startDropbox.isPending}
              onClick={() => startDropbox.mutate()}
            >
              Connect Dropbox
            </button>
            <button
              type="button"
              className="btn primary small"
              disabled={!d.available.onedrive || start.isPending}
              onClick={() => start.mutate("onedrive")}
            >
              Connect OneDrive
            </button>
            <button type="button" className="btn small" disabled={!d.available.folder} onClick={() => setStep("folder")}>
              Use a synced folder
            </button>
            <button type="button" className="btn small" onClick={() => setStep(null)}>
              Not now
            </button>
          </div>
          {sf?.can_choose ? (
            <p className="tiny muted" style={{ margin: 0 }}>
              {sf.where ? `Synced folder: ${sf.where}, a subfolder for each learner. ` : "No synced folder is offered yet. "}
              <button type="button" className="btn ghost small" onClick={() => setStep("choose-folder")}>
                {sf.where ? "Change the synced folder" : "Choose a synced folder"}
              </button>
            </p>
          ) : (
            !d.available.folder && (
              <p className="tiny muted" style={{ margin: 0 }}>
                A synced folder (iCloud Drive and other sync apps): whoever runs this RecallSpring chooses the folder first.
              </p>
            )
          )}
        </div>
      )}

      {step === "folder" && sf?.mine && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby="drive-folder-h">
          <h4 id="drive-folder-h" className="backup-key-title">
            A synced folder
          </h4>
          <p className="small" style={{ margin: 0 }}>
            RecallSpring copies each file you add into <strong>{sf.mine} › your course</strong>, as it is.
          </p>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>RecallSpring keeps working from its own copy</span>
            </li>
            <li data-level="warn">
              <span aria-hidden="true">!</span>
              <span>The folder is on the computer RecallSpring runs on and syncs to the account of whoever runs it, not to yours</span>
            </li>
          </ul>
          {connectFolder.error && <ErrorNote error={connectFolder.error} />}
          <div className="row">
            <button type="button" className="btn primary small" disabled={connectFolder.isPending} onClick={() => connectFolder.mutate()}>
              Use the synced folder
            </button>
            <button type="button" className="btn small" onClick={() => setStep("about")}>
              Back
            </button>
          </div>
        </section>
      )}

      {step === "choose-folder" && sf?.can_choose && (
        <>
          <SyncedFolderStep
            id="drive-choose-h"
            intro={
              <>
                Each learner&apos;s material goes into their own folder: <strong>folder › sign-in name › course</strong>.
                {sf.where && ` Now: ${sf.where}.`}
              </>
            }
            checkUrl="/drive/folder/check"
            suggestions={sf.suggestions}
            name="RecallSpring"
            busy={chooseFolder.isPending}
            error={chooseFolder.error}
            note={
              <p className="tiny warn-text" style={{ margin: 0 }}>
                This folder syncs to <strong>your</strong> account at the sync app. Learners who use it put their copy in your account, not in
                theirs; RecallSpring tells them so.
              </p>
            }
            onUse={(path) => chooseFolder.mutate(path)}
            onCancel={() => setStep("about")}
          />
          {sf.where && (
            <div className="row">
              <button type="button" className="btn ghost small" disabled={chooseFolder.isPending} onClick={() => chooseFolder.mutate(null)}>
                Stop offering the synced folder
              </button>
            </div>
          )}
        </>
      )}

      {step === "code" && (
        <DeviceSignIn
          id="drive-code-h"
          provider={device?.provider ?? signing}
          device={device}
          outcome={outcome}
          what="a readable copy of your material"
          busy={start.isPending}
          error={start.error}
          onRestart={() => start.mutate(signing)}
          onCancel={() => {
            cancel.mutate();
            setStep(null);
            setDevice(null);
          }}
        />
      )}

      {step === "paste" && (
        <DropboxSignIn
          pending={dropbox}
          what="a readable copy of your material"
          busy={finishDropbox.isPending || startDropbox.isPending}
          error={finishDropbox.error}
          expired={dropboxExpired}
          onCode={(code) => finishDropbox.mutate(code)}
          onRestart={() => startDropbox.mutate()}
          onCancel={() => {
            cancel.mutate();
            setDropbox(null);
            setStep(null);
          }}
        />
      )}

      {step === "manage" && on && (
        <section className="assistant-steps stack" style={{ gap: 10 }} aria-label="Your cloud folder">
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
              <button
                type="button"
                className="btn primary small"
                onClick={() => (provider === "dropbox" ? startDropbox.mutate() : provider !== "folder" && start.mutate(provider))}
                disabled={start.isPending || startDropbox.isPending}
              >
                Sign in to {company} again
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
          {startDropbox.error && <ErrorNote error={startDropbox.error} />}
          <fieldset className="plain-choice">
            <legend className="small">{withdrawText(provider)}</legend>
            <label className="check-row small">
              <input type="radio" name="drive-files" checked={!deleteFiles} onChange={() => setDeleteFiles(false)} />
              <span>{provider === "folder" ? "Keep the files in the folder" : `Keep the files in your ${label}`}</span>
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
        title={`Delete your ${label} copy?`}
        confirmLabel="Disconnect and delete"
        danger
        busy={disconnect.isPending}
        onConfirm={() => disconnect.mutate(true)}
        onClose={() => setConfirming(false)}
      >
        The folder{" "}
        {provider === "google"
          ? "RecallSpring in your Google Drive"
          : provider === "folder"
            ? d.folder
            : `Apps › RecallSpring › Material in your ${label}`}{" "}
        and everything in it (
        {plural(d.files ?? 0, "file")}
        {d.exports ? " and exports" : ""}) will be deleted. This cannot be undone. Your material in RecallSpring stays. This is recorded in History.
      </Confirm>
    </div>
  );
}
