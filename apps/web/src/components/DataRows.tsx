import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { request } from "../api";
import { dateLabel, plural, timeOnly } from "../format";
import type { BackupStatus, DeletedItem, DeletedList } from "../types";
import { CopyButton } from "./Copy";
import { ErrorNote } from "./ui";

/** Settings › Data & backups rows that open in place (2026-11-27): Recently deleted and Getting it back. */

export const deletedKey = ["deleted"] as const;

const KIND: Record<DeletedItem["type"], string> = {
  course: "Course",
  exam: "Exam",
  note: "Note",
  focus: "Focus block",
  chat: "Chat",
};

const RESTORE: Record<DeletedItem["type"], (id: string) => string> = {
  course: (id) => `/courses/${id}/restore`,
  exam: (id) => `/targets/${id}/restore`,
  note: (id) => `/notes/${id}/restore`,
  focus: (id) => `/focus-sessions/${id}/restore`,
  chat: (id) => `/ai/chatgpt/conversations/${id}/restore`,
};

const WHERE: Record<DeletedItem["type"], [string, string]> = {
  course: ["Courses", "/courses"],
  exam: ["Exams", "/exams"],
  note: ["Notes", "/notes"],
  focus: ["Focus", "/focus"],
  chat: ["Chat", "/chat"],
};

const FILTER_FROM = 10;

/** Whole days until an item can no longer be restored (0 on its last day). */
function daysLeft(until: string, now = Date.now()): number {
  return Math.max(0, Math.floor((new Date(until).getTime() - now) / 86_400_000));
}

function leftText(until: string): string {
  const d = daysLeft(until);
  return d === 0 ? "last day" : `${plural(d, "day")} left`;
}

function title(i: DeletedItem): string {
  if (i.type === "focus" && i.started_at && i.ended_at)
    return `${dateLabel(i.started_at)}, ${timeOnly(i.started_at)}–${timeOnly(i.ended_at)}`;
  return i.title;
}

function brings(i: DeletedItem): string | null {
  if (!i.brings) return null;
  const parts = [
    i.brings.notes ? plural(i.brings.notes, "note") : null,
    i.brings.exams ? plural(i.brings.exams, "exam") : null,
    i.brings.materials ? plural(i.brings.materials, "material") : null,
  ].filter(Boolean);
  return parts.length ? `With ${parts.join(", ")}` : null;
}

export function RecentlyDeletedRow() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<DeletedItem["type"] | "all">("all");
  const [restored, setRestored] = useState<DeletedItem | null>(null);
  const q = useQuery({ queryKey: deletedKey, queryFn: () => request<DeletedList>("/deleted") });
  const restore = useMutation({
    mutationFn: (i: DeletedItem) => request(RESTORE[i.type](i.id), { method: "POST" }).then(() => i),
    onSuccess: (i) => {
      setRestored(i);
      void qc.invalidateQueries();
    },
  });
  const items = q.data?.items ?? [];
  const days = q.data?.restorable_days ?? 30;
  const soonest = items.length ? Math.min(...items.map((i) => daysLeft(i.restorable_until))) : null;
  const summary = items.length
    ? `${plural(items.length, "item")} · restorable for ${days} days · the next one goes ${soonest === 0 ? "today" : `in ${plural(soonest ?? 0, "day")}`}`
    : `Nothing deleted in the last ${days} days`;
  const kinds = [...new Set(items.map((i) => i.type))];
  const shown = kind === "all" ? items : items.filter((i) => i.type === kind);
  return (
    <div id="recently-deleted">
      <div className="settings-row">
        <span>
          <h3 className="settings-row-title">Recently deleted</h3>
          <span className="small muted">{q.isLoading ? "Loading…" : q.isError ? "Could not load the list" : summary}</span>
        </span>
        {items.length > 0 || open ? (
          <button
            type="button"
            className="btn small"
            aria-expanded={open}
            aria-label={open ? "Close recently deleted" : "Open recently deleted"}
            onClick={() => {
              setOpen(!open);
              setRestored(null);
            }}
          >
            {open ? "Close" : "Open"}
          </button>
        ) : (
          <span />
        )}
      </div>
      {open && (
        <div className="assistant-steps stack" style={{ gap: 8 }}>
          {items.length > FILTER_FROM && (
            <label className="field small" style={{ maxWidth: 240 }}>
              <span>Show</span>
              <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                <option value="all">All</option>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {WHERE[k][0]}
                  </option>
                ))}
              </select>
            </label>
          )}
          {restored && (
            <div className="notice small" role="status">
              Restored: <strong>{title(restored)}</strong> is back in {WHERE[restored.type][0]}.{" "}
              <Link to={WHERE[restored.type][1]}>Open {WHERE[restored.type][0]}</Link>
            </div>
          )}
          {restore.error && <ErrorNote error={restore.error} />}
          {shown.length === 0 ? (
            <p className="small muted" style={{ margin: 0 }}>
              Nothing deleted in the last {days} days.
            </p>
          ) : (
            <ul className="list deleted-list" aria-label="Recently deleted items">
              {shown.map((i) => {
                const left = daysLeft(i.restorable_until);
                const extra = [i.course_title, brings(i), `deleted ${dateLabel(i.deleted_at)}`].filter(Boolean).join(" · ");
                return (
                  <li key={`${i.type}-${i.id}`} className="row" style={{ justifyContent: "space-between", gap: 10 }}>
                    <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                      <span className="chip">{KIND[i.type]}</span> <strong>{title(i)}</strong>
                      <br />
                      <span className="small muted">
                        {extra} · <span className={left <= 7 ? "warn-text" : undefined}>{leftText(i.restorable_until)}</span>
                      </span>
                    </span>
                    <button
                      type="button"
                      className="btn small"
                      disabled={restore.isPending}
                      onClick={() => restore.mutate(i)}
                      aria-label={`Restore ${KIND[i.type].toLowerCase()} ${title(i)}`}
                    >
                      Restore
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="tiny muted" style={{ margin: 0 }}>
            After {days} days an item can no longer be restored here. Older backups may still hold it (Getting it back).
          </p>
        </div>
      )}
    </div>
  );
}

/** "20261119-030000" (a snapshot's name) → its date. */
function snapshotDate(name: string): string | null {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(name);
  return m ? `${dateLabel(`${m[1]}-${m[2]}-${m[3]}`)}, ${m[4]}:${m[5]}` : null;
}

export function GettingItBack({ b }: { b: BackupStatus }) {
  const [open, setOpen] = useState(false);
  const snaps = [...b.snapshots].sort();
  const newest = snaps.length ? snapshotDate(snaps[snaps.length - 1] ?? "") : null;
  const oldest = snaps.length ? snapshotDate(snaps[0] ?? "") : null;
  const encrypted = b.encryption.on;
  const command = `recallspring backup-restore --database recallspring_restored --storage <an empty folder>${encrypted ? " --key <your recovery key file>" : ""}`;
  return (
    <div id="getting-it-back">
      <div className="settings-row">
        <span>
          <h3 className="settings-row-title">Getting it back</h3>
          <span className="small muted">
            {open && snaps.length
              ? `${plural(snaps.length, "backup")} here${newest ? ` · newest ${newest}` : ""}${oldest && snaps.length > 1 ? ` · oldest ${oldest}` : ""}`
              : "A backup becomes a new database next to this one; nothing is overwritten"}
          </span>
        </span>
        <button
          type="button"
          className="btn small"
          aria-expanded={open}
          aria-label={open ? "Close the restore steps" : "Show the restore steps"}
          onClick={() => setOpen(!open)}
        >
          {open ? "Close" : "Show steps"}
        </button>
      </div>
      {open && (
        <div className="assistant-steps stack" style={{ gap: 8 }}>
          {!b.enabled && <p className="small" style={{ margin: 0 }}>Automatic backups are off in the server settings; these steps work for backups made with Back up now.</p>}
          {snaps.length === 0 ? (
            <p className="small" style={{ margin: 0 }}>
              There is no backup in this folder yet. Back up now first.
            </p>
          ) : (
            <ol className="restore-steps small">
              <li>
                <strong>Choose a backup.</strong> The newest is used unless you name another with <code>--snapshot</code> (names from{" "}
                <code>recallspring backup-status</code>).
              </li>
              <li>
                <strong>Restore it into a new database</strong> on the computer RecallSpring runs on:
                <div className="row" style={{ gap: 8, marginTop: 4, flexWrap: "nowrap" }}>
                  <code className="command-line">{command}</code>
                  <CopyButton text={command} />
                </div>
              </li>
              <li>
                <strong>Switch to it</strong> when it says it is restored and checked: stop RecallSpring, set the new database and folder
                in the server settings (<code>RS_DATABASE_URL</code>, <code>RS_STORAGE_DIR</code>), run <code>alembic upgrade head</code> and start it again. The old ones stay
                until you remove them; switching back is the same change.
              </li>
            </ol>
          )}
          <ul className="folder-checks">
            {encrypted && (
              <li data-level="warn">
                <span aria-hidden="true">!</span>
                <span>
                  Encrypted backups need your recovery key file
                  {b.encryption.key_created_at ? ` (made ${dateLabel(b.encryption.key_created_at)})` : ""}. Without it they cannot be
                  restored.
                </span>
              </li>
            )}
            <li data-level="warn">
              <span aria-hidden="true">!</span>
              <span>
                Backups in a cloud folder or a folder used before: let the sync app download the folder first, then add{" "}
                <code>--from &lt;that folder&gt;</code>.
              </span>
            </li>
          </ul>
          <p className="tiny muted" style={{ margin: 0 }}>
            Restoring a single course or note from a backup is not possible yet; within 30 days use Recently deleted. Details: docs/08 →
            Restore procedure.
          </p>
        </div>
      )}
    </div>
  );
}
