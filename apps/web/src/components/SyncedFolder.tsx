import { useMutation } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { request } from "../api";
import type { BackupFolderCheck, FolderSuggestion } from "../types";
import { ErrorNote } from "./ui";

/** A synced folder (2026-11-28): iCloud Drive or any other sync app, through the folder its app keeps on the computer
 * RecallSpring runs on. Shared by Cloud copy and Your cloud folder: type or pick a folder, check it, then use it. A
 * check belongs to the path as it was checked; editing the path asks for a new check. */

function join(folder: string, name: string): string {
  const sep = folder.includes("\\") ? "\\" : "/";
  return folder.endsWith(sep) ? `${folder}${name}` : `${folder}${sep}${name}`;
}

export function FolderChecks({ checked }: { checked: BackupFolderCheck }) {
  return (
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
    </ul>
  );
}

export function SyncedFolderStep({
  id,
  intro,
  checkUrl,
  suggestions,
  name,
  busy,
  error,
  note,
  onUse,
  onCancel,
}: {
  id: string;
  intro: ReactNode;
  checkUrl: string;
  suggestions: FolderSuggestion[];
  /** The folder RecallSpring makes inside a suggestion, e.g. "RecallSpring backups". */
  name: string;
  busy: boolean;
  error: unknown;
  note?: ReactNode;
  onUse: (path: string) => void;
  onCancel: () => void;
}) {
  const [path, setPath] = useState("");
  const check = useMutation({
    mutationFn: (p: string) => request<BackupFolderCheck>(checkUrl, { method: "POST", json: { path: p } }),
  });
  const checked = check.data && check.variables === path.trim() ? check.data : null;
  return (
    <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby={id}>
      <h4 id={id} className="backup-key-title">
        A synced folder
      </h4>
      <p className="small" style={{ margin: 0 }}>
        {intro}
      </p>
      {suggestions.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="tiny muted">Found on this computer</span>
          {suggestions.map((s) => (
            <div key={s.path} className="settings-row" style={{ padding: "6px 0" }}>
              <span style={{ minWidth: 0 }}>
                <span className="small">{s.app}</span>
                <span className="tiny muted backup-path">{s.path}</span>
              </span>
              <button type="button" className="btn small" aria-label={`Use ${s.app}`} onClick={() => setPath(join(s.path, name))}>
                Use
              </button>
            </div>
          ))}
        </div>
      )}
      <form
        className="backup-folder stack"
        aria-label="Synced folder"
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
          <span className="hint">Paste the full path. RecallSpring makes only the last folder; the one above it must be there.</span>
        </label>
      </form>
      {checked && <FolderChecks checked={checked} />}
      {checked?.ok && note}
      {check.error != null && <ErrorNote error={check.error} />}
      {error != null && <ErrorNote error={error} />}
      <div className="row">
        <button
          type="button"
          className="btn primary small"
          disabled={!checked?.ok || !checked.path || busy}
          onClick={() => checked?.path && onUse(checked.path)}
        >
          Use this folder
        </button>
        <button type="button" className="btn small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}
