import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, request } from "../api";
import { dateLabel } from "../format";
import { useCourses, useSources, useTargets } from "../queries";
import type { ScopeItem, Target } from "../types";
import { useInvalidateOrganisation } from "./organise";
import { Confirm, ErrorNote, Modal } from "./ui";

interface MaterialRow {
  source_id: string;
  from: string;
  to: string;
}

function toRows(scope: ScopeItem[]): MaterialRow[] {
  return scope
    .filter((s) => (s.kind === "source" || s.kind === "pages") && s.source_id)
    .map((s) => ({ source_id: s.source_id!, from: s.pages ? String(s.pages[0]) : "", to: s.pages ? String(s.pages[1]) : "" }));
}

function toScope(rows: MaterialRow[], kept: ScopeItem[]) {
  const material = rows
    .filter((r) => r.source_id)
    .map((r) =>
      r.from && r.to
        ? { kind: "pages", source_id: r.source_id, page_from: Number(r.from), page_to: Number(r.to) }
        : { kind: "source", source_id: r.source_id },
    );
  // Topic and concept entries Claude mapped are kept as they are.
  const others = kept
    .filter((s) => s.kind === "topic" || s.kind === "concept")
    .map((s) => (s.kind === "topic" ? { kind: "topic", topic_id: s.topic_id } : { kind: "concept", concept_id: s.concept_id }));
  return [...material, ...others];
}

/** Create or edit an exam / kolokvij: date, status and result, the scope in the learner's words and its mapping. */
export function TargetDialog({ target, courseId, open, onClose, onDeleted }: {
  target?: Target & { course_id?: string };
  courseId?: string;
  open: boolean;
  onClose: () => void;
  onDeleted?: (target: Target) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const courses = useCourses();
  const [course, setCourse] = useState(target?.course_id ?? courseId ?? "");
  const chosenCourse = course || courses.data?.[0]?.id || "";
  const sources = useSources(chosenCourse || undefined);
  const refresh = useInvalidateOrganisation();
  const [name, setName] = useState(target?.name ?? "1. kolokvij");
  const [kind, setKind] = useState(target?.kind ?? "kolokvij");
  const [due, setDue] = useState(target?.due_date ?? "");
  const [status, setStatus] = useState(target?.status ?? "upcoming");
  const [result, setResult] = useState(target?.result ?? "");
  const [scopeText, setScopeText] = useState(target?.scope_description ?? "");
  const [notes, setNotes] = useState(target?.notes ?? "");
  const [rows, setRows] = useState<MaterialRow[]>(toRows(target?.scope ?? []));
  const textSources = (sources.data ?? []).filter((s) => s.kind !== "image");

  const save = useMutation({
    mutationFn: () => {
      const scope = toScope(rows, target?.scope ?? []);
      if (!target) {
        return request("/targets", {
          json: {
            course_id: chosenCourse,
            kind,
            name: name.trim(),
            due_date: due,
            scope_description: scopeText.trim(),
            notes: notes.trim() || null,
            scope,
          },
        });
      }
      const body: Record<string, unknown> = {};
      if (name.trim() !== target.name) body.name = name.trim();
      if (kind !== target.kind) body.kind = kind;
      if (due !== target.due_date) body.due_date = due;
      if (status !== target.status) body.status = status;
      if ((result.trim() || null) !== (target.result ?? null) && result.trim()) body.result = result.trim();
      if (scopeText.trim() !== target.scope_description) body.scope_description = scopeText.trim();
      if (notes.trim() !== (target.notes ?? "") && notes.trim()) body.notes = notes.trim();
      if (JSON.stringify(rows) !== JSON.stringify(toRows(target.scope))) body.scope = scope;
      if (Object.keys(body).length === 0) return Promise.resolve(null);
      return request(`/targets/${target.id}`, { method: "PATCH", json: body });
    },
    onSuccess: () => {
      refresh();
      onClose();
    },
  });

  const remove = useMutation({
    mutationFn: () => request(`/targets/${target!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      refresh();
      setConfirmDelete(false);
      onDeleted?.(target!);
      onClose();
    },
  });

  // Merging is always available by hand, not only when Exams detects a likely duplicate.
  const allTargets = useTargets();
  const ownCourse = target?.course_id ?? courseId;
  const mergeOptions = target
    ? (allTargets.data ?? []).filter((t) => t.id !== target.id && t.course_id === ownCourse)
    : [];
  const likelyDuplicate = mergeOptions.find((t) => target?.duplicates?.includes(t.id));
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeInto, setMergeInto] = useState("");
  const mergeTarget = mergeOptions.find((t) => t.id === mergeInto);
  const merge = useMutation({
    mutationFn: () => request(`/targets/${target!.id}/merge`, { method: "POST", json: { into_id: mergeInto } }),
    onSuccess: () => {
      refresh();
      setMergeOpen(false);
      onClose();
    },
  });
  function openMerge() {
    setConfirmDelete(false);
    setMergeInto(likelyDuplicate?.id ?? mergeOptions[0]?.id ?? "");
    setMergeOpen(true);
  }

  const existing =
    save.error instanceof ApiError && save.error.code === "target_exists"
      ? (save.error.details?.existing as { name: string; due_date: string } | undefined)
      : undefined;

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Modal open={open} title={target ? `Edit ${target.name}` : "Add an exam or kolokvij"} onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        {!target && (
          <label className="field">
            Course
            <select value={chosenCourse} onChange={(e) => setCourse(e.target.value)} required>
              {courses.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="grid cols-2" style={{ gap: 12 }}>
          <label className="field">
            Name
            <input type="text" value={name} maxLength={120} required onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            Type
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="kolokvij">Kolokvij</option>
              <option value="izpit">Exam</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="field">
            Date
            <input type="date" value={due} required onChange={(e) => setDue(e.target.value)} />
          </label>
          {target && (
            <label className="field">
              Status
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="upcoming">Upcoming</option>
                <option value="passed">Passed</option>
                <option value="failed">Failed (retake)</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
          )}
        </div>
        {target && (status === "passed" || status === "failed") && (
          <label className="field">
            Result
            <span className="hint">Passed material moves to maintenance; new material gets priority.</span>
            <input type="text" value={result} maxLength={120} placeholder="e.g. 78 %" onChange={(e) => setResult(e.target.value)} />
          </label>
        )}
        <label className="field">
          Scope in your words
          <span className="hint">Kept exactly as you write it, e.g. “lectures 1 to 6, without chapter 7”.</span>
          <textarea rows={3} value={scopeText} maxLength={2000} required onChange={(e) => setScopeText(e.target.value)} />
        </label>
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
          <legend className="small" style={{ fontWeight: 600 }}>
            Material it covers
          </legend>
          <span className="small muted">Leave the pages empty to include a whole file. Claude can refine this mapping.</span>
          {rows.map((r, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-end" }}>
              <label className="field" style={{ flex: 2, minWidth: 180 }}>
                <span className="sr-only">Material</span>
                <select value={r.source_id} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, source_id: e.target.value } : x)))}>
                  <option value="">Choose material</option>
                  {textSources.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.filename}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field" style={{ width: 90 }}>
                <span className="small">From page</span>
                <input type="number" min={1} value={r.from} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)))} />
              </label>
              <label className="field" style={{ width: 90 }}>
                <span className="small">To page</span>
                <input type="number" min={1} value={r.to} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))} />
              </label>
              <button type="button" className="btn small ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="Remove this material">
                Remove
              </button>
            </div>
          ))}
          <div>
            <button type="button" className="btn small" onClick={() => setRows([...rows, { source_id: "", from: "", to: "" }])} disabled={!textSources.length}>
              Add material
            </button>
          </div>
        </fieldset>
        <label className="field">
          Type and specifics
          <span className="hint">Written or online, length, multiple-choice or open questions, allowed aids.</span>
          <textarea rows={2} value={notes} maxLength={4000} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {existing ? (
          <div className="notice warn" role="alert">
            This course already has <strong>{existing.name}</strong> on {dateLabel(existing.due_date)}, probably recorded from
            another chat. Close this and edit that one instead (Exams shows it), or use a different date or name if it is
            another exam.
          </div>
        ) : (
          save.error && <ErrorNote error={save.error} />
        )}
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            {target && (
              <button type="button" className="btn danger" onClick={() => setConfirmDelete(true)}>
                Delete
              </button>
            )}
            {target && mergeOptions.length > 0 && (
              <button type="button" className="btn" onClick={openMerge}>
                Merge into…
              </button>
            )}
          </div>
          <div className="row">
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={save.isPending || !due || !scopeText.trim() || !chosenCourse}>
              {target ? "Save" : "Add"}
            </button>
          </div>
        </div>
      </form>
      {target && (
        <Confirm
          open={confirmDelete}
          title={`Delete ${target.name}?`}
          confirmLabel="Delete"
          danger
          busy={remove.isPending}
          onConfirm={() => remove.mutate()}
          onClose={() => setConfirmDelete(false)}
        >
          {target.name} on {dateLabel(target.due_date)} disappears from your plan, the timeline and Claude. Simulations, answers and
          grades stay. You can restore it from Exams → Recently deleted for 30 days.
          {likelyDuplicate && (
            <div className="notice" style={{ marginTop: 10 }}>
              It looks like the same exam as <strong>{likelyDuplicate.name}</strong>. Merge it instead, so its simulations and
              old-paper analysis move there.{" "}
              <button type="button" className="btn small" onClick={openMerge}>
                Merge instead
              </button>
            </div>
          )}
          {remove.error && <ErrorNote error={remove.error} />}
        </Confirm>
      )}
      {target && (
        <Confirm
          open={mergeOpen}
          title={`Merge ${target.name} into another exam?`}
          confirmLabel="Merge"
          busy={merge.isPending || !mergeTarget}
          onConfirm={() => merge.mutate()}
          onClose={() => setMergeOpen(false)}
        >
          <label className="field">
            Keep this exam
            <select value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}>
              {mergeOptions.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {dateLabel(t.due_date)}
                  {t.status !== "upcoming" ? ` · ${t.status}` : ""}
                </option>
              ))}
            </select>
          </label>
          <p>
            The old-paper analysis and simulations of {target.name} move to {mergeTarget?.name ?? "the exam you keep"}; its
            material mapping is used if that one has none, and its description is added to the notes. {target.name} is then
            deleted; you can restore it from Exams → Recently deleted for 30 days.
          </p>
          {merge.error && <ErrorNote error={merge.error} />}
        </Confirm>
      )}
    </Modal>
  );
}
