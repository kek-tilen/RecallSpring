import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { TimeZoneSelect, useSaveProfile } from "./Welcome";
import { greeting } from "./Home";
import { request } from "../api";
import { Async, Card, Confirm, ErrorNote } from "../components/ui";
import { Link, useLocation } from "react-router";
import { bytes, dateLabel, dateTime, plural, relativeDay, timeOnly } from "../format";
import { keys, useAssistants, useBackup, useConnector, useSession, useStudySettings } from "../queries";
import { PreferencesEditor } from "./Import";
import { AssistantsPanel } from "../components/Assistants";
import { ExplanationPaceDefault } from "../components/ExplanationPace";
import { ServiceStatus } from "../components/ServiceStatus";
import { GettingItBack, RecentlyDeletedRow } from "../components/DataRows";
import { CloudCopyRow } from "../components/CloudCopy";
import { SignInRows } from "../components/SignInRows";
import { readTheme, saveTheme, THEMES, type ThemeId } from "../theme";
import type { BackupFolderCheck, BackupKey, BackupStatus, StudySettings } from "../types";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function StudyForm({ initial }: { initial: StudySettings }) {
  const qc = useQueryClient();
  const [minutes, setMinutes] = useState(initial.weekly_minutes);
  const [maintenance, setMaintenance] = useState(initial.maintenance_percent);
  const [style, setStyle] = useState(initial.style_percent);
  const [interest, setInterest] = useState(initial.interest_percent);
  const save = useMutation({
    mutationFn: () =>
      request<StudySettings>("/settings/study", {
        method: "PUT",
        json: { weekly_minutes: minutes, maintenance_percent: maintenance, style_percent: style, interest_percent: interest },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.studySettings });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
  const dirty =
    minutes.join() !== initial.weekly_minutes.join() ||
    maintenance !== initial.maintenance_percent ||
    style !== initial.style_percent ||
    interest !== initial.interest_percent;

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <form className="stack" onSubmit={submit}>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="small" style={{ fontWeight: 600, marginBottom: 8 }}>
          Minutes per day
        </legend>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(84px, 1fr))", gap: 8 }}>
          {DAYS.map((d, i) => (
            <label key={d} className="field">
              {d}
              <input
                type="number"
                min={0}
                max={720}
                step={5}
                value={minutes[i]}
                onChange={(e) => setMinutes(minutes.map((m, j) => (j === i ? Math.max(0, Math.min(720, Number(e.target.value) || 0)) : m)))}
              />
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field">
        Maintenance share: {maintenance}%
        <span className="hint">Time kept for material of a passed midterm so it is not forgotten.</span>
        <input type="range" min={0} max={50} value={maintenance} onChange={(e) => setMaintenance(Number(e.target.value))} />
      </label>
      <label className="field">
        Past-paper style: {style}%
        <span className="hint">Share of simulation questions in the style of your old papers; the rest go deeper.</span>
        <input type="range" min={0} max={100} step={5} value={style} onChange={(e) => setStyle(Number(e.target.value))} />
      </label>
      <label className="field">
        Interests: {interest === 0 ? "university first" : `${interest}% of each day`}
        <span className="hint">
          {interest === 0
            ? "Your interests get only the time left after today's course work, and only while every exam is on track."
            : "This share of each day is kept for your interests, even when an exam is tight; exam checks count only the rest."}
        </span>
        <input
          type="range"
          min={0}
          max={50}
          step={5}
          value={interest}
          aria-valuetext={interest === 0 ? "University first" : `${interest} percent`}
          onChange={(e) => setInterest(Number(e.target.value))}
        />
      </label>
      {initial.focus && (
        <div className="notice small">
          Focus: <strong>{initial.focus.course_title}</strong> comes first until {dateLabel(initial.focus.until)}.{" "}
          <Link to={`/courses/${initial.focus.course_id}`}>Open it to end the focus.</Link>
        </div>
      )}
      {save.error && <ErrorNote error={save.error} />}
      <div className="row">
        <button type="submit" className="btn primary" disabled={!dirty || save.isPending}>
          Save study settings
        </button>
        {save.isSuccess && !dirty && <span className="small muted">Saved.</span>}
      </div>
    </form>
  );
}

const CHECK_LABEL: Record<NonNullable<BackupStatus["last"]>["check"], string> = {
  restored: "Restored into a test database; every table matched",
  listed: "Dump read back (no permission for a test restore)",
  none: "Not checked (turned off in the server settings)",
};

function BackupPanel({ b }: { b: BackupStatus }) {
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => request<BackupStatus>("/settings/backup", { method: "POST", json: {} }),
    onSuccess: (v) => {
      qc.setQueryData(keys.backup, v);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
    onError: () => {
      void qc.invalidateQueries({ queryKey: keys.backup });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="settings-row">
        <span>
          <span className="settings-row-title">Backups</span>
          <span className="small muted">
            {b.last_success_at ? `Last one ${relativeDay(b.last_success_at).toLowerCase()}, ${timeOnly(b.last_success_at)}` : "No backup yet"}
            {" · "}
            {whereKept(b)}
          </span>
        </span>
        <button type="button" className="btn small" onClick={() => run.mutate()} disabled={run.isPending || !b.tools}>
          {run.isPending ? "Backing up…" : "Back up now"}
        </button>
      </div>
      {b.last_error && (
        <div className="notice bad" role="alert">
          <strong>The last backup failed{b.last_error.at ? ` (${dateTime(b.last_error.at)})` : ""}.</strong> {b.last_error.message}
        </div>
      )}
      {!b.tools && (
        <div className="notice bad" role="alert">
          pg_dump was not found, so no backup can be made. Install the PostgreSQL client tools or set RS_BACKUP_PG_BIN (docs/08 → Backups).
        </div>
      )}
      {run.error && <ErrorNote error={run.error} />}
      {run.isSuccess && !run.isPending && (
        <div className="notice small" role="status">
          Backed up and checked.
        </div>
      )}
    </div>
  );
}

/** Backup details, under all Data & backups rows (2026-11-27). */
function BackupDetails({ b }: { b: BackupStatus }) {
  const last = b.last;
  return (
    <details className="settings-details">
        <summary>Backup details</summary>
      <div className="stack" style={{ gap: 14 }}>
      <p className="small">
        A copy of your study records and uploaded files.{" "}
        {b.enabled
          ? `RecallSpring makes one ${b.schedule_label.toLowerCase()} (${b.timezone}) while it runs and keeps ${keepsText(b, b.keeps === "daily_weekly")}.`
          : "Automatic backups are turned off in the server settings; you can still back up here."}
      </p>
      <dl className="kv">
        <dt>Last backup</dt>
        <dd>{b.last_success_at ? dateTime(b.last_success_at) : "Never"}</dd>
        {last && (
          <>
            <dt>Records</dt>
            <dd>
              {plural(last.rows, "row")} in {plural(last.tables, "table")} ({bytes(last.dump_bytes)})
            </dd>
            <dt>Uploaded files</dt>
            <dd>
              {plural(last.files, "file")} ({bytes(last.files_bytes)})
              {last.files_missing > 0 && <span className="chip warn"> {last.files_missing} missing from storage</span>}
            </dd>
            <dt>Check</dt>
            <dd>{CHECK_LABEL[last.check]}</dd>
          </>
        )}
        <dt>Next</dt>
        <dd>
          {!b.enabled ? "Only when you back up here" : b.next_due === "now" || !b.next_due ? "As soon as the RecallSpring worker runs" : dateTime(b.next_due)}
        </dd>
        <dt>Kept</dt>
        <dd>
          {plural(b.snapshots.length, "backup")}, {bytes(b.disk_bytes)}
        </dd>
        <dt>Folder</dt>
        <dd className="tiny" style={{ wordBreak: "break-all" }}>
          {b.location}
        </dd>
      </dl>
      {b.same_disk_as_storage && (
        <div className="notice warn small">
          Backups are on the same disk as RecallSpring. They protect against mistakes and a damaged database, not against a broken
          disk or a lost computer. Choose another disk or a synced folder under Where backups go, or copy this folder elsewhere now and
          then.
        </div>
      )}
      </div>
      </details>
  );
}

const EVERY_CHOICES: [string, string][] = [
  ["1", "Daily"],
  ["3", "Every 3 days"],
  ["7", "Weekly"],
  ["14", "Every 2 weeks"],
  ["monthly", "Monthly"],
  ["custom", "Every … days"],
];

function choiceOf(s: BackupStatus["schedule"]): string {
  if (s.every === "monthly") return "monthly";
  return ["1", "3", "7", "14"].includes(String(s.days)) ? String(s.days) : "custom";
}

function keepsText(b: BackupStatus, daily: boolean): string {
  return daily ? `the newest of each of the last ${b.keep_daily} days and ${b.keep_weekly} weeks` : `the last ${b.keep_last} backups`;
}

/** How often backups run and at what time, in the first account's time zone (2026-11-27). */
function BackupSchedule({ b }: { b: BackupStatus }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("1");
  const [days, setDays] = useState("10");
  const [at, setAt] = useState("03:00");
  const save = useMutation({
    mutationFn: (body: { every: "days" | "monthly"; days?: number; at: string }) =>
      request<BackupStatus>("/settings/backup/schedule", { method: "PUT", json: body }),
    onSuccess: (v) => {
      qc.setQueryData(keys.backup, v);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      setOpen(false);
    },
  });
  const n = choice === "custom" ? Number(days) : Number(choice);
  const daysOk = choice === "monthly" || (Number.isInteger(n) && n >= 1 && n <= 90);
  const timeOk = /^([01]\d|2[0-3]):[0-5]\d$/.test(at);
  const lose = choice === "monthly" ? "a month" : n > 1 ? `${n} days` : null;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!daysOk || !timeOk) return;
    save.mutate(choice === "monthly" ? { every: "monthly", at } : { every: "days", days: n, at });
  }
  return (
    <>
      <div className="settings-row">
        <span>
          <span className="settings-row-title">How often</span>
          <span className="small muted">
            {b.schedule_label} · keeps {keepsText(b, b.keeps === "daily_weekly")}
            {!b.folder_from_web && " · set in the server settings"}
          </span>
        </span>
        {b.can_change && !open && (
          <button
            type="button"
            className="btn small"
            aria-label="Change how often backups run"
            onClick={() => {
              setChoice(choiceOf(b.schedule));
              if (b.schedule.days) setDays(String(b.schedule.days));
              setAt(b.schedule.at);
              save.reset();
              setOpen(true);
            }}
          >
            Change
          </button>
        )}
      </div>
      {open && (
        <form className="backup-folder stack" aria-label="How often backups run" onSubmit={submit}>
          <div className="backup-schedule-fields">
            <label className="field">
              <span className="small">Back up</span>
              <select value={choice} onChange={(e) => setChoice(e.target.value)}>
                {EVERY_CHOICES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {choice === "custom" && (
              <label className="field">
                <span className="small">Days between backups</span>
                <input type="number" min={1} max={90} step={1} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} />
              </label>
            )}
            <label className="field">
              <span className="small">At</span>
              <input type="time" value={at} required onChange={(e) => setAt(e.target.value)} />
            </label>
          </div>
          <p className="tiny muted" style={{ margin: 0 }}>
            {choice === "monthly" && "On today's day of the month, or the last day of a shorter month. "}
            Time in {b.timezone}. A backup missed while RecallSpring was off runs as soon as it runs again. Keeps{" "}
            {keepsText(b, choice === "1")}.
          </p>
          {!daysOk && (
            <p className="small" role="alert" style={{ margin: 0 }}>
              Choose 1 to 90 days.
            </p>
          )}
          {daysOk && lose && (
            <div className="notice warn small">If the disk or the database fails, up to {lose} of study records could be lost.</div>
          )}
          {save.error && <ErrorNote error={save.error} />}
          <div className="row">
            <button type="submit" className="btn primary small" disabled={!daysOk || !timeOk || save.isPending}>
              Save
            </button>
            <button type="button" className="btn small" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </>
  );
}

function whereKept(b: BackupStatus): string {
  const where = b.sync ? `in your ${b.sync} folder` : b.same_disk_as_storage ? "on the same disk as your uploads" : "on another disk";
  return b.encryption.on ? `encrypted · ${where}` : where;
}

const SYNC_HELP: [string, string][] = [
  ["Google Drive", "Google Drive for desktop (Windows, macOS). Pick a folder inside My Drive."],
  ["OneDrive", "Built into Windows; app for macOS. A work or school account may limit what you can store."],
  ["Dropbox", "App for Windows, macOS and Linux."],
  ["iCloud Drive", "Built into macOS; iCloud for Windows. The only way for iCloud: a server cannot write to it directly."],
];

/** Where backups go, chosen here and checked before it is saved (2026-11-27). Backups already made stay put. */
function BackupFolder({ b }: { b: BackupStatus }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const check = useMutation({
    mutationFn: (p: string) => request<BackupFolderCheck>("/settings/backup/folder/check", { method: "POST", json: { path: p } }),
  });
  const save = useMutation({
    mutationFn: (p: string | null) => request<BackupStatus>("/settings/backup/folder", { method: "PUT", json: { path: p } }),
    onSuccess: (v) => {
      qc.setQueryData(keys.backup, v);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      close();
    },
  });
  function close() {
    setOpen(false);
    check.reset();
  }
  // A result belongs to the path as it was checked; editing the path asks for a new check.
  const checked = check.data && check.variables === path.trim() ? check.data : null;
  const where = [b.same_disk_as_storage ? "same disk as your uploads" : "another disk", b.sync && `synced by ${b.sync}`].filter(Boolean).join(" · ");
  return (
    <>
      <div className="settings-row">
        <span>
          <span className="settings-row-title">Where backups go</span>
          <span className="small muted">
            <span className="backup-path">{b.location}</span> · {where}
            {!b.folder_from_web && " · set in the server settings"}
          </span>
        </span>
        {b.can_change && !open && (
          <button
            type="button"
            className="btn small"
            onClick={() => {
              setPath(b.location);
              setOpen(true);
            }}
          >
            Change
          </button>
        )}
      </div>
      {open && (
        <form
          className="backup-folder stack"
          aria-label="Where backups go"
          onSubmit={(e) => {
            e.preventDefault();
            if (path.trim()) check.mutate(path.trim());
          }}
        >
          <label className="field">
            <span className="small">Folder on the computer RecallSpring runs on</span>
            <span className="backup-folder-input">
              <input value={path} onChange={(e) => setPath(e.target.value)} spellCheck={false} autoComplete="off" maxLength={1000} />
              <button type="submit" className="btn small" disabled={!path.trim() || check.isPending}>
                {check.isPending ? "Checking…" : "Check folder"}
              </button>
            </span>
            <span className="hint">Paste the full path, for example from Explorer or Finder. RecallSpring writes only inside it.</span>
          </label>
          {checked && (
            <ul className="folder-checks" aria-label="Folder check" aria-live="polite">
              {checked.checks.map((c) => (
                <li key={c.id} data-level={c.level}>
                  <span aria-hidden="true">{c.level === "ok" ? "✓" : "!"}</span>
                  <span>
                    {c.level === "bad" && <span className="sr-only">Problem: </span>}
                    {c.level === "warn" && <span className="sr-only">Note: </span>}
                    {c.text}
                  </span>
                </li>
              ))}
              {checked.ok && checked.sync && !b.encryption.on && (
                <li data-level="warn">
                  <span aria-hidden="true">!</span>
                  <span>Encryption is off: anyone who can open this {checked.sync} folder can read the backups. Turn it on under Encryption.</span>
                </li>
              )}
            </ul>
          )}
          {checked?.ok && checked.path !== b.location && (
            <p className="tiny muted" style={{ margin: 0 }}>
              Backups already made stay in {b.location}. The next one starts in the new folder.
            </p>
          )}
          {check.error && <ErrorNote error={check.error} />}
          {save.error && <ErrorNote error={save.error} />}
          <div className="row">
            <button
              type="button"
              className="btn primary small"
              disabled={!checked?.ok || !checked.path || save.isPending}
              onClick={() => checked?.path && save.mutate(checked.path)}
            >
              Use this folder
            </button>
            <button type="button" className="btn small" onClick={close}>
              Cancel
            </button>
            {b.location_source === "settings" && (
              <button type="button" className="btn ghost small" onClick={() => save.mutate(null)} disabled={save.isPending}>
                Use the server&apos;s folder
              </button>
            )}
          </div>
          <details className="settings-details">
            <summary>Using a synced folder</summary>
            <ul className="list small">
              {SYNC_HELP.map(([name, text]) => (
                <li key={name}>
                  <strong>{name}</strong>: {text}
                </li>
              ))}
            </ul>
            <p className="tiny muted" style={{ margin: 0 }}>
              On a Linux server only Dropbox has an official app; the others need a tool such as rclone.
            </p>
          </details>
        </form>
      )}
    </>
  );
}

type KeyStep = "manage" | "about" | "key" | "check";

function keyFile(k: BackupKey): string {
  return [
    `# RecallSpring recovery key ${k.key_id}`,
    `# Made ${new Date().toISOString().slice(0, 10)}. It opens the backups made with this key; nothing else can.`,
    "# Keep it away from the computer RecallSpring runs on: a password manager, a USB stick, or printed.",
    "# Restore: recallspring backup-restore --database <new name> --key <this file>",
    k.identity,
    "",
  ].join("\n");
}

/** Encryption with a recovery key (2026-11-27): shown once, saved by the learner, proved, then turned on. */
function BackupEncryption({ b }: { b: BackupStatus }) {
  const qc = useQueryClient();
  const on = b.encryption.on;
  const [step, setStep] = useState<KeyStep | null>(null);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [proof, setProof] = useState("");
  const [removePlain, setRemovePlain] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const make = useMutation({
    mutationFn: () => request<BackupKey>("/settings/backup/key", { method: "POST", json: {} }),
    onSuccess: () => setStep("key"),
  });
  const key = make.data ?? null;
  const save = useMutation({
    mutationFn: (k: BackupKey) =>
      request<BackupStatus>("/settings/backup/encryption", { method: "PUT", json: { recipient: k.recipient, remove_unencrypted: removePlain } }),
    onSuccess: (v) => {
      qc.setQueryData(keys.backup, v);
      void qc.invalidateQueries({ queryKey: keys.history });
      close();
    },
  });
  /** Forget the key: it lives only in this component until the learner has saved it. */
  function close() {
    setStep(null);
    setSaved(false);
    setCopied(false);
    setProof("");
    setRemovePlain(false);
    setConfirming(false);
    make.reset();
  }
  function download(k: BackupKey) {
    const url = URL.createObjectURL(new Blob([keyFile(k)], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `recallspring-recovery-key-${k.key_id}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function copy(k: BackupKey) {
    try {
      await navigator.clipboard.writeText(k.identity);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  const proved = key !== null && proof.trim().toUpperCase() === key.identity.slice(-4).toUpperCase();
  const plainCount = b.unencrypted_snapshots;
  return (
    <>
      <div className="settings-row">
        <span>
          <span className="settings-row-title">Encryption</span>
          <span className="small muted">
            {on
              ? `On${b.encryption.key_created_at ? ` since ${dateLabel(b.encryption.key_created_at)}` : ""} · key ${b.encryption.key_id} · only your recovery key opens a backup`
              : "Off · anyone who has the backup folder can read the backups"}
          </span>
        </span>
        {b.can_change && step === null && (
          <button type="button" className="btn small" aria-expanded={false} onClick={() => setStep(on ? "manage" : "about")}>
            {on ? "Recovery key" : "Turn on"}
          </button>
        )}
        {step === "manage" && (
          <button type="button" className="btn small" aria-expanded onClick={close}>
            Close
          </button>
        )}
      </div>
      {b.remove_unencrypted_pending && plainCount > 0 && (
        <p className="tiny muted" style={{ margin: 0 }}>
          {plural(plainCount, "unencrypted backup")} will be removed after the next encrypted one.
        </p>
      )}
      {step === "manage" && (
        <section className="backup-key stack" aria-labelledby="backup-key-h">
          <h4 id="backup-key-h" className="backup-key-title">
            Your recovery key
          </h4>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>
                Made {b.encryption.key_created_at ? `on ${dateLabel(b.encryption.key_created_at)}` : "earlier"} (key {b.encryption.key_id}). Backups
                made since then need it.
              </span>
            </li>
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>RecallSpring keeps only the half that locks; it cannot open a backup or show the key again.</span>
            </li>
          </ul>
          <p className="small" style={{ margin: 0 }}>
            Lost it, or think someone else has it? Make a new one. New backups use the new key; backups made before still need the old
            one.
          </p>
          <div className="row">
            <button type="button" className="btn small" onClick={() => setStep("about")}>
              Make a new key
            </button>
          </div>
        </section>
      )}
      {step === "about" && (
        <section className="backup-key stack" aria-labelledby="backup-key-h">
          <h4 id="backup-key-h" className="backup-key-title">
            {on ? "A new recovery key" : "Encrypt backups"}
          </h4>
          <p className="small" style={{ margin: 0 }}>
            Backups are then locked with a key only you hold. RecallSpring keeps backing up every day but cannot read them.
          </p>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>A copy in a cloud folder is useless without your key</span>
            </li>
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>Nothing changes in how you study</span>
            </li>
            <li data-level="warn">
              <span aria-hidden="true">!</span>
              <span>Lose the key and these backups cannot be restored, by you or by anyone</span>
            </li>
            {on && (
              <li data-level="warn">
                <span aria-hidden="true">!</span>
                <span>Backups made so far still need key {b.encryption.key_id}; keep it until they are gone</span>
              </li>
            )}
          </ul>
          {make.error && <ErrorNote error={make.error} />}
          <div className="row">
            <button type="button" className="btn primary small" onClick={() => make.mutate()} disabled={make.isPending}>
              {make.isPending ? "Making…" : "Make my recovery key"}
            </button>
            <button type="button" className="btn small" onClick={close}>
              Not now
            </button>
          </div>
        </section>
      )}
      {step === "key" && key && (
        <section className="backup-key stack" aria-labelledby="backup-key-h">
          <h4 id="backup-key-h" className="backup-key-title">
            Your recovery key
          </h4>
          <p className="small" style={{ margin: 0 }}>
            Shown only now. Keep it somewhere other than this computer: a password manager, or printed.
          </p>
          <code className="recovery-key" aria-label="Recovery key">
            {key.identity}
          </code>
          <div className="row">
            <button type="button" className="btn small" onClick={() => download(key)}>
              Download
            </button>
            <button type="button" className="btn small" onClick={() => void copy(key)}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <label className="check-row small">
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
            <span>I keep it somewhere other than this computer</span>
          </label>
          <div className="row">
            <button type="button" className="btn primary small" disabled={!saved} onClick={() => setStep("check")}>
              Next
            </button>
            <button type="button" className="btn small" onClick={close}>
              Cancel
            </button>
          </div>
        </section>
      )}
      {step === "check" && key && (
        <form
          className="backup-key stack"
          aria-labelledby="backup-key-h"
          onSubmit={(e) => {
            e.preventDefault();
            if (!proved) return;
            if (removePlain) setConfirming(true);
            else save.mutate(key);
          }}
        >
          <h4 id="backup-key-h" className="backup-key-title">
            Check your key
          </h4>
          <label className="field">
            <span className="small">Type the last 4 characters of your recovery key</span>
            <input className="key-proof" value={proof} onChange={(e) => setProof(e.target.value)} maxLength={4} autoComplete="off" spellCheck={false} />
          </label>
          {!on && plainCount > 0 && (
            <fieldset className="plain-choice">
              <legend className="small">Older backups that are not encrypted ({plainCount})</legend>
              <label className="check-row small">
                <input type="radio" name="plain" checked={!removePlain} onChange={() => setRemovePlain(false)} />
                <span>Keep them (they go with the usual 7 days and 4 weeks)</span>
              </label>
              <label className="check-row small">
                <input type="radio" name="plain" checked={removePlain} onChange={() => setRemovePlain(true)} />
                <span>Delete them after the first encrypted one</span>
              </label>
            </fieldset>
          )}
          {save.error && <ErrorNote error={save.error} />}
          <div className="row">
            <button type="submit" className="btn primary small" disabled={!proved || save.isPending}>
              {on ? "Use the new key" : "Turn on encryption"}
            </button>
            <button type="button" className="btn small" onClick={() => setStep("key")}>
              Back
            </button>
            <button type="button" className="btn small" onClick={close}>
              Cancel
            </button>
          </div>
        </form>
      )}
      <Confirm
        open={confirming}
        title="Delete unencrypted backups?"
        confirmLabel="Turn on and delete them"
        danger
        busy={save.isPending}
        onConfirm={() => key && save.mutate(key)}
        onClose={() => setConfirming(false)}
      >
        After the first encrypted backup, the {plural(plainCount, "older backup")} that {plainCount === 1 ? "is" : "are"} not encrypted will be
        deleted from the backup folder. This cannot be undone. A sync app may still keep its own copies for a while.
      </Confirm>
    </>
  );
}

function ThemePicker() {
  const [theme, setTheme] = useState<ThemeId>(readTheme);
  function pick(t: ThemeId) {
    setTheme(t);
    saveTheme(t);
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="theme-grid" role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} className="theme-card" onClick={() => pick(t.id)}>
            <span className="theme-swatch" aria-hidden="true" style={{ background: t.swatch[0], borderColor: t.swatch[1] }}>
              <span style={{ background: t.swatch[1] }} />
              <span style={{ background: t.swatch[2] }} />
              <span style={{ background: t.swatch[3] }} />
              <span style={{ background: t.swatch[4] }} />
            </span>
            <span className="theme-name">{t.name}</span>
            <span className="tiny muted">
              {t.dark ? "Dark" : "Light"} · {t.note}
            </span>
          </button>
        ))}
      </div>
      <label className="row small" style={{ gap: 8 }}>
        <input type="checkbox" checked={theme === "system"} onChange={(e) => pick(e.target.checked ? "system" : "light")} />
        Match my computer (RecallSpring White or RecallSpring Dark)
      </label>
      <p className="tiny muted" style={{ margin: 0 }}>
        Saved on this device. Solarized, Nord, Dracula and Gruvbox are open-source colour schemes, adapted so text stays
        easy to read.
      </p>
    </div>
  );
}

/** Username, session, what Home calls you and time zone. */
function ProfileForm() {
  const qc = useQueryClient();
  const session = useSession();
  const user = session.data?.user;
  const [timezone, setTimezone] = useState(user?.timezone ?? "UTC");
  const [name, setName] = useState(user?.greeting_name ?? "");
  const [saved, setSaved] = useState(false);
  const save = useSaveProfile();
  if (!user) return null;
  const nameChanged = name.trim() !== (user.greeting_name ?? "");
  const changed = timezone !== user.timezone || nameChanged;
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(
      { timezone, greeting_name: name.trim() || null },
      {
        onSuccess: () => {
          setSaved(true);
          // "Today", plans and due dates are computed in the time zone.
          void qc.invalidateQueries();
        },
      },
    );
  }
  return (
    <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
      <dl className="kv">
        <dt>Username</dt>
        <dd>{user.username}</dd>
        <dt>Session ends</dt>
        <dd>{session.data ? dateTime(session.data.expires_at) : ""}</dd>
      </dl>
      <label className="field">
        What should Home call you?
        <input
          type="text"
          value={name}
          maxLength={40}
          autoComplete="nickname"
          placeholder="No name"
          onChange={(e) => {
            setName(e.target.value);
            setSaved(false);
          }}
        />
        <span className="hint">
          {name.trim() ? "" : "Empty: "}Home says “{greeting(new Date().getHours(), name)}”.
        </span>
      </label>
      <label className="field">
        Time zone
        <TimeZoneSelect
          value={timezone}
          onChange={(z) => {
            setTimezone(z);
            setSaved(false);
          }}
        />
        <span className="hint">“Today”, plans, reviews and dates use it.</span>
      </label>
      {save.error && <ErrorNote error={save.error} />}
      <div className="row">
        <button type="submit" className="btn primary" disabled={!changed || save.isPending}>
          {save.isPending ? "Saving…" : "Save profile"}
        </button>
        {saved && !changed && (
          <span className="small muted" role="status">
            Saved.
          </span>
        )}
      </div>
    </form>
  );
}

/** Sign out (moved here from the menu, 2026-11-27): the menu keeps only the six areas, Settings and Help. */
/** The five parts of Settings, in page order (the contents beside the page link to them). */
export const SECTIONS = [
  { id: "study", title: "Study", sub: "How much you study and how RecallSpring plans your time." },
  { id: "assistants", title: "Assistants", sub: "Who helps you: Claude Desktop, Codex, Antigravity and ChatGPT." },
  { id: "data", title: "Data & backups", sub: "Where your data is kept and how you get it back." },
  { id: "appearance", title: "Appearance", sub: "How RecallSpring looks on this device." },
  { id: "account", title: "Account & system", sub: "Your sign-in, time zone and RecallSpring running in the background." },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

/** Old links name a card (/settings#chatgpt); they open the section that holds it (2026-11-27). */
const CARD_SECTION: Record<string, SectionId> = {
  pace: "study",
  chatgpt: "assistants",
  connector: "assistants",
  backups: "data",
  "cloud-copy": "data",
  "backup-encryption": "data",
  history: "data",
  profile: "account",
  "sign-in": "account",
  service: "account",
};

function sectionOf(hash: string): SectionId {
  const id = hash.replace(/^#/, "");
  return SECTIONS.find((x) => x.id === id)?.id ?? CARD_SECTION[id] ?? "study";
}

function Section({ id, children }: { id: SectionId; children: ReactNode }) {
  const s = SECTIONS.find((x) => x.id === id)!;
  return (
    <section id={id} className="settings-section" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <div className="settings-section-head">
        <h2 id={`${id}-title`}>{s.title}</h2>
        <p className="small muted">{s.sub}</p>
      </div>
      {children}
    </section>
  );
}

export function SettingsPage() {
  const study = useStudySettings();
  const connector = useConnector();
  const assistants = useAssistants();
  const backup = useBackup();
  const { hash } = useLocation();
  const current = sectionOf(hash);
  useEffect(() => {
    // A link to a card (/settings#chatgpt) opens its section and scrolls to the card.
    const id = hash.slice(1);
    if (id && !SECTIONS.some((x) => x.id === id)) document.getElementById(id)?.scrollIntoView?.({ block: "start" });
  }, [hash]);
  return (
    <div className="page settings-page">
      <div className="settings-layout">
        <nav className="settings-toc" aria-label="Settings sections">
          <h1 className="settings-h1">Settings</h1>
          <ol>
            {SECTIONS.map((x) => (
              <li key={x.id}>
                <Link to={{ hash: x.id }} replace aria-current={current === x.id ? "page" : undefined}>
                  {x.title}
                </Link>
              </li>
            ))}
          </ol>
          <p className="tiny muted settings-guide">
            Guide: the <Link to="/guide">?</Link> button. Every change is recorded in History.
          </p>
        </nav>
        <div className="settings-body">
          {current === "study" && (
            <Section id="study">
              <div className="grid cols-2" style={{ alignItems: "start" }}>
                <Card title="Study time" level={3}>
                  <Async q={study}>{(s) => <StudyForm initial={s} />}</Async>
                </Card>
                <Card title="Study preferences" level={3}>
                  <PreferencesEditor />
                </Card>
                <Card title="Explanation pace" id="pace" level={3}>
                  <ExplanationPaceDefault />
                </Card>
              </div>
            </Section>
          )}
          {current === "assistants" && (
            <Section id="assistants">
              <div className="settings-rows" id="connector">
                <Async q={assistants}>{(s) => <AssistantsPanel s={s} c={connector.data} />}</Async>
              </div>
            </Section>
          )}
          {current === "data" && (
            <Section id="data">
              <div className="settings-rows">
                <div id="backups">
                  <h3 className="sr-only">Backups</h3>
                  <Async q={backup}>{(b) => <BackupPanel b={b} />}</Async>
                </div>
                {backup.data && (
                  <div id="backup-schedule">
                    <BackupSchedule b={backup.data} />
                  </div>
                )}
                {backup.data && (
                  <div id="backup-folder">
                    <BackupFolder b={backup.data} />
                  </div>
                )}
                {backup.data && <CloudCopyRow b={backup.data} />}
                {backup.data && (
                  <div id="backup-encryption">
                    <BackupEncryption b={backup.data} />
                  </div>
                )}
                {backup.data && <GettingItBack b={backup.data} />}
                <RecentlyDeletedRow />
                <div className="settings-row" id="history">
                  <span>
                    <h3 className="settings-row-title">History</h3>
                    <span className="small muted">Everything that changed your learning records and settings, who made it and when</span>
                  </span>
                  <Link to="/history" className="btn small">
                    Open history
                  </Link>
                </div>
              </div>
              {backup.data && <BackupDetails b={backup.data} />}
            </Section>
          )}
          {current === "appearance" && (
            <Section id="appearance">
              <Card title="Theme" level={3}>
                <ThemePicker />
              </Card>
            </Section>
          )}
          {current === "account" && (
            <Section id="account">
              <div className="grid cols-2" style={{ alignItems: "start" }}>
                <Card title="Profile" id="profile" level={3}>
                  <ProfileForm />
                </Card>
                <Card title="Sign-in" id="sign-in" level={3}>
                  <SignInRows />
                </Card>
                <Card title="Running in the background" id="service" level={3}>
                  <ServiceStatus />
                </Card>
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
