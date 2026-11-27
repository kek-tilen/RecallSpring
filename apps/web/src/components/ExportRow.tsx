import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { API, get, request } from "../api";
import { bytes, dateLabel, dateTime, plural } from "../format";
import type { ExportItem, ExportView } from "../types";
import { ErrorNote } from "./ui";

const KEY = ["exports"] as const;
const ACTIVE = new Set(["queued", "running"]);

const FAILURES: Record<string, string> = {
  not_enough_space: "The server ran out of disk space while making it.",
  export_failed: "Something went wrong while making it. Try again.",
};

function readyNow(c: ExportItem | null): boolean {
  return !!c && c.state === "ready" && !!c.expires_at && Date.parse(c.expires_at) > Date.now();
}

function summary(v: ExportView): string {
  const c = v.current;
  if (c && ACTIVE.has(c.state)) {
    const p = c.progress;
    return p?.total_files ? `Being made · ${p.done_files} of ${p.total_files} items` : "Being made…";
  }
  if (c && readyNow(c)) return `Ready · ${bytes(c.byte_size ?? 0)} · kept until ${dateTime(c.expires_at!)}`;
  if (c?.state === "failed") return `The last export failed · ${FAILURES[c.error ?? ""] ?? "try again"}`;
  if (v.last_export_at) return `Your material, notes and answers as plain files · last export ${dateLabel(v.last_export_at)}`;
  return "Never · your material, notes and answers as a ZIP to download";
}

export function ExportRow() {
  const qc = useQueryClient();
  const view = useQuery({
    queryKey: KEY,
    queryFn: () => get<ExportView>("/exports"),
    refetchInterval: (q) => (q.state.data?.current && ACTIVE.has(q.state.data.current.state) ? 2000 : false),
  });
  const [open, setOpen] = useState(false);
  const [newOne, setNewOne] = useState(false);
  const v = view.data;
  const c = v?.current ?? null;
  const active = !!c && ACTIVE.has(c.state);
  const ready = readyNow(c);
  const panel = open || active;
  const set = (next: ExportView) => qc.setQueryData(KEY, next);

  const stop = useMutation({
    mutationFn: (id: string) => request<ExportView>(`/exports/${id}/cancel`, { method: "POST" }),
    onSuccess: set,
  });

  return (
    <div id="export">
      <div className="settings-row">
        <span style={{ minWidth: 0 }}>
          <h3 className="settings-row-title">Export</h3>
          <span className={`small ${c?.state === "failed" ? "warn-text" : "muted"}`}>{v ? summary(v) : view.error ? "Could not load." : "…"}</span>
        </span>
        {v && !active && (
          <button type="button" className="btn small" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Close" : ready ? "Download" : "Export"}
          </button>
        )}
      </div>
      {panel && v && (
        <div className="assistant-steps stack" style={{ gap: 10 }}>
          {active && c ? (
            <Running c={c} onStop={() => stop.mutate(c.id)} stopping={stop.isPending} />
          ) : ready && c && !newOne ? (
            <Ready c={c} keepHours={v.keep_hours} onNew={() => setNewOne(true)} onRemove={() => stop.mutate(c.id)} />
          ) : (
            <Choose
              v={v}
              onDone={() => setNewOne(false)}
              onCancel={() => {
                setNewOne(false);
                setOpen(false);
              }}
            />
          )}
          {stop.error && <ErrorNote error={stop.error} />}
        </div>
      )}
    </div>
  );
}

function Choose({ v, onDone, onCancel }: { v: ExportView; onDone: () => void; onCancel: () => void }) {
  const qc = useQueryClient();
  const [all, setAll] = useState(true);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(v.courses.map((c) => c.id)));
  const [material, setMaterial] = useState(true);
  const [notes, setNotes] = useState(true);
  const [answers, setAnswers] = useState(true);
  const chosen = all ? v.courses : v.courses.filter((c) => picked.has(c.id));
  const total = {
    bytes: material ? chosen.reduce((n, c) => n + c.bytes, 0) : 0,
    files: material ? chosen.reduce((n, c) => n + c.files, 0) : 0,
    notes: notes ? chosen.reduce((n, c) => n + c.notes, 0) : 0,
    answers: answers ? chosen.reduce((n, c) => n + c.answers, 0) : 0,
  };
  const make = useMutation({
    mutationFn: () =>
      request<ExportView>("/exports", {
        method: "POST",
        json: { course_ids: all ? null : [...picked], material, notes, answers, destination: "download" },
      }),
    onSuccess: (next) => {
      qc.setQueryData(KEY, next);
      onDone();
    },
  });
  if (v.courses.length === 0) {
    return (
      <p className="small" style={{ margin: 0 }}>
        There is nothing to export yet: add a course first.
      </p>
    );
  }
  const toggle = (id: string) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };
  const nothing = (!material && !notes && !answers) || chosen.length === 0;
  return (
    <>
      <fieldset className="plain-fieldset stack" style={{ gap: 6 }}>
        <legend className="small muted">Courses</legend>
        <div className="row" role="radiogroup" aria-label="Which courses">
          <label className="small">
            <input type="radio" name="export-courses" checked={all} onChange={() => setAll(true)} /> All {v.courses.length}
          </label>
          <label className="small">
            <input type="radio" name="export-courses" checked={!all} onChange={() => setAll(false)} /> Choose…
          </label>
        </div>
        {!all && (
          <ul className="export-courses" aria-label="Courses to export">
            {v.courses.map((c) => (
              <li key={c.id}>
                <label className="small">
                  <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)} /> {c.title}
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>
      <fieldset className="plain-fieldset stack" style={{ gap: 4 }}>
        <legend className="small muted">What goes in</legend>
        <label className="small">
          <input type="checkbox" checked={material} onChange={(e) => setMaterial(e.target.checked)} /> Material, by course (as you uploaded it)
        </label>
        <label className="small">
          <input type="checkbox" checked={notes} onChange={(e) => setNotes(e.target.checked)} /> Notes, as Markdown
        </label>
        <label className="small">
          <input type="checkbox" checked={answers} onChange={(e) => setAnswers(e.target.checked)} /> Answers and grades (CSV and JSON)
        </label>
      </fieldset>
      <p className="tiny muted" style={{ margin: 0 }} aria-live="polite">
        About {bytes(total.bytes)} · {plural(total.files, "file")}, {plural(total.notes, "note")}, {plural(total.answers, "answer")}
      </p>
      {make.error && <ErrorNote error={make.error} />}
      <div className="row">
        <button type="button" className="btn primary small" disabled={nothing || make.isPending} onClick={() => make.mutate()}>
          {make.isPending ? "Starting…" : "Make the export"}
        </button>
        <button type="button" className="btn small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </>
  );
}

function Running({ c, onStop, stopping }: { c: ExportItem; onStop: () => void; stopping: boolean }) {
  const p = c.progress;
  const pct = p?.total_files ? Math.round((100 * p.done_files) / p.total_files) : 0;
  return (
    <>
      <p className="small" style={{ margin: 0 }}>
        Putting it together. You can leave this page; Today says when it is ready.
      </p>
      <progress max={100} value={pct} aria-label="Export progress" style={{ width: "100%" }} />
      <p className="tiny muted" role="status" style={{ margin: 0 }}>
        {p?.total_files ? `${p.done_files} of ${p.total_files} items` : "Starting…"}
      </p>
      <div className="row">
        <button type="button" className="btn small" onClick={onStop} disabled={stopping}>
          Stop
        </button>
      </div>
    </>
  );
}

function Ready({ c, keepHours, onNew, onRemove }: { c: ExportItem; keepHours: number; onNew: () => void; onRemove: () => void }) {
  const n = c.counts;
  return (
    <>
      <ul className="folder-checks">
        <li data-level="ok">
          <span aria-hidden="true">✓</span>
          <span>
            {c.file_name} · {bytes(c.byte_size ?? 0)}
          </span>
        </li>
        {n && (
          <li data-level="ok">
            <span aria-hidden="true">✓</span>
            <span>
              {plural(n.files, "file")}, {plural(n.notes, "note")}, {plural(n.answers, "answer")}
            </span>
          </li>
        )}
      </ul>
      <p className="notice small" style={{ margin: 0 }}>
        Kept here for {keepHours} hours, then deleted. It is not encrypted: store it where only you can open it.
      </p>
      <div className="row">
        <a className="btn primary small" href={`${API}/exports/${c.id}/download`} download>
          Download
        </a>
        <button type="button" className="btn small" onClick={onNew}>
          Make a new one
        </button>
        <button type="button" className="btn small" onClick={onRemove}>
          Delete it now
        </button>
      </div>
    </>
  );
}
