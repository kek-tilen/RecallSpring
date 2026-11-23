import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { get, request } from "../api";
import { dateTime, gradedBy, plural } from "../format";
import { BackToAssistant, useDraft } from "../pages/Answer";
import { Async, Confirm, ErrorNote, PageHead } from "./ui";

/** Concept-to-Clarity (ADR-010): the learner's own explanation of a concept, in versions, with feedback per version. */

export interface ExplanationFeedback {
  id: string;
  grader: { name: string; model: string | null } | null;
  correct: string[];
  missing: string[];
  wrong: string[];
  evidence_refs: string[];
  feedback: string;
  created_at: string;
}

export interface ExplanationVersion {
  id: string;
  number: number;
  text: string;
  words: number;
  source: "learner" | "discuss" | "exam_answer";
  source_attempt_id: string | null;
  word_limit: number | null;
  created_at: string;
  deleted_at: string | null;
  feedback: ExplanationFeedback[];
}

export interface ExplanationView {
  concept: { id: string; term: string; course_id: string };
  versions: ExplanationVersion[];
  deleted: ExplanationVersion[];
}

export const explanationKey = (conceptId: string) => ["explanation", conceptId] as const;

export const C2C_TRAINS = "Trains understanding: your own explanation, clearer with each version. Feedback, not a grade.";

export function useExplanation(conceptId: string) {
  return useQuery({
    queryKey: explanationKey(conceptId),
    queryFn: () => get<ExplanationView>(`/concepts/${conceptId}/explanation`),
    enabled: Boolean(conceptId),
  });
}

export function wordCount(text: string): number {
  const t = text.trim();
  return t ? t.split(/\s+/).length : 0;
}

function sourceLabel(v: ExplanationVersion): string {
  if (v.source === "discuss") return "Written after a discussion";
  if (v.source === "exam_answer") return `From an exam answer${v.word_limit ? `, written with a ${v.word_limit}-word limit` : ""}`;
  return "Written by you";
}

export interface DiffPart {
  text: string;
  kind: "same" | "added" | "removed";
}

/** Words added and removed from one version to the next (longest common subsequence of words). */
export function wordDiff(before: string, after: string): DiffPart[] | null {
  const a = before.split(/(\s+)/).filter(Boolean);
  const b = after.split(/(\s+)/).filter(Boolean);
  if (a.length * b.length > 4_000_000) return null; // very long texts: no comparison rather than a slow page
  const n = a.length;
  const m = b.length;
  const lcs = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i]![j] = a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }
  const out: DiffPart[] = [];
  const push = (text: string, kind: DiffPart["kind"]) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ text, kind });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push(a[i]!, "same");
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) push(a[i++]!, "removed");
    else push(b[j++]!, "added");
  }
  while (i < n) push(a[i++]!, "removed");
  while (j < m) push(b[j++]!, "added");
  return out;
}

function Points({ label, items, tone }: { label: string; items: string[]; tone?: "good" | "warn" | "bad" }) {
  if (!items.length) return null;
  return (
    <div className={`c2c-points${tone ? ` ${tone}` : ""}`}>
      <span className="tiny" style={{ fontWeight: 600 }}>
        {label}
      </span>
      <ul className="small">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

function Feedback({ f }: { f: ExplanationFeedback }) {
  return (
    <div className="c2c-feedback stack" style={{ gap: 8 }}>
      <p className="small" style={{ margin: 0 }}>
        {f.feedback}
      </p>
      <Points label="Correct" items={f.correct} tone="good" />
      <Points label="Missing" items={f.missing} tone="warn" />
      <Points label="Wrong" items={f.wrong} tone="bad" />
      <span className="tiny muted">
        Feedback from {gradedBy("ai", f.grader)} · {dateTime(f.created_at)}
        {f.evidence_refs.length > 0 && ` · cites ${plural(f.evidence_refs.length, "section")} of your material`} · not a grade
      </span>
    </div>
  );
}

function Changes({ before, after }: { before: ExplanationVersion; after: ExplanationVersion }) {
  const parts = wordDiff(before.text, after.text);
  if (!parts) return <p className="tiny muted">These versions are too long to compare here.</p>;
  return (
    <p className="c2c-diff small pre" aria-label={`Changes from version ${before.number} to version ${after.number}`}>
      {parts.map((p, i) =>
        p.kind === "added" ? (
          <ins key={i}>{p.text}</ins>
        ) : p.kind === "removed" ? (
          <del key={i}>{p.text}</del>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </p>
  );
}

function Version({
  v,
  previous,
  onDelete,
  open,
}: {
  v: ExplanationVersion;
  previous: ExplanationVersion | undefined;
  onDelete: (v: ExplanationVersion) => void;
  open: boolean;
}) {
  const [changes, setChanges] = useState(false);
  const body = (
    <div className="stack" style={{ gap: 10 }}>
      <p className="reading pre" style={{ margin: 0 }}>
        {v.text}
      </p>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="tiny muted">
          {sourceLabel(v)} · {dateTime(v.created_at)} · {plural(v.words, "word")}
        </span>
        {previous && (
          <button type="button" className="btn small ghost" aria-expanded={changes} onClick={() => setChanges(!changes)}>
            {changes ? "Hide changes" : `Changes from v${previous.number}`}
          </button>
        )}
        <button type="button" className="btn small ghost" onClick={() => onDelete(v)} aria-label={`Delete version ${v.number}`}>
          Delete
        </button>
      </div>
      {changes && previous && <Changes before={previous} after={v} />}
      {v.feedback.length === 0 ? (
        <p className="tiny muted" style={{ margin: 0 }}>
          No feedback yet. Ask your assistant to check your explanation.
        </p>
      ) : (
        v.feedback.map((f) => <Feedback key={f.id} f={f} />)
      )}
    </div>
  );
  if (open) {
    return (
      <section className="c2c-version" aria-label={`Version ${v.number}`}>
        <h3 className="small" style={{ margin: "0 0 8px" }}>
          Version {v.number} (newest)
        </h3>
        {body}
      </section>
    );
  }
  return (
    <details className="c2c-version">
      <summary className="small">
        Version {v.number} · {dateTime(v.created_at)}
        {v.feedback.length > 0 && " · feedback"}
      </summary>
      <div style={{ marginTop: 8 }}>{body}</div>
    </details>
  );
}

/** Write a new version. Saved exactly as typed; a lost response never saves twice (the same request id on retry). */
export function ExplanationWriter({
  conceptId,
  term,
  source = "learner",
  last,
  onSaved,
  submitLabel = "Save version",
}: {
  conceptId: string;
  term: string;
  source?: "learner" | "discuss";
  last: ExplanationVersion | undefined;
  onSaved?: (view: ExplanationView) => void;
  submitLabel?: string;
}) {
  const qc = useQueryClient();
  const [draft, setText, clearDraft] = useDraft(`rs-c2c-draft:${conceptId}`);
  const box = useRef<HTMLTextAreaElement>(null);
  const [reused, setReused] = useState(0);
  useEffect(() => {
    // after "Start from my last version": keep writing at the end of the copied text
    const el = box.current;
    if (!reused || !el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [reused]);
  const save = useMutation({
    mutationFn: () =>
      request<ExplanationView>(`/concepts/${conceptId}/explanation/versions`, {
        key: draft.key,
        json: { text: draft.text, source, client_request_id: draft.key },
      }),
    onSuccess: (view) => {
      clearDraft();
      qc.setQueryData(explanationKey(conceptId), view);
      onSaved?.(view);
    },
  });
  const words = wordCount(draft.text);
  const same = Boolean(last && draft.text.trim() === last.text.trim());
  const lastFeedback = last?.feedback[last.feedback.length - 1];
  return (
    <form
      className="stack"
      style={{ gap: 10 }}
      onSubmit={(e) => {
        e.preventDefault();
        if (draft.text.trim() && !same) save.mutate();
      }}
    >
      {last && lastFeedback && (lastFeedback.missing.length > 0 || lastFeedback.wrong.length > 0) && (
        <div className="c2c-hints">
          <span className="tiny muted">From the feedback on version {last.number}:</span>
          <Points label="Missing" items={lastFeedback.missing} tone="warn" />
          <Points label="Wrong" items={lastFeedback.wrong} tone="bad" />
        </div>
      )}
      <label className="field">
        Explain {term} in your own words
        <textarea
          ref={box}
          rows={8}
          maxLength={20000}
          value={draft.text}
          onChange={(e) => setText(e.target.value)}
          aria-describedby={`c2c-count-${conceptId}`}
        />
        <span className="hint" id={`c2c-count-${conceptId}`} aria-live="polite">
          {plural(words, "word")} · as if to a classmate. Saved exactly as you write it; the draft stays in this browser
          until you save.
        </span>
      </label>
      {same && last && <p className="tiny muted" style={{ margin: 0 }}>Same as version {last.number}: change it to save a new version.</p>}
      {save.error && <ErrorNote error={save.error} />}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button type="submit" className="btn primary" disabled={save.isPending || !draft.text.trim() || same}>
          {submitLabel}
        </button>
        {last && (
          <button type="button" className="btn ghost" onClick={() => {
              setText(last.text);
              setReused((n) => n + 1);
            }} disabled={save.isPending}>
            Start from my last version
          </button>
        )}
      </div>
    </form>
  );
}

/** The concept page's C2C card: newest version with its feedback, earlier versions, writing a new one. */
export function ClarityPanel({ conceptId }: { conceptId: string }) {
  const qc = useQueryClient();
  const q = useExplanation(conceptId);
  const [writing, setWriting] = useState(false);
  const [deleting, setDeleting] = useState<ExplanationVersion | null>(null);
  const remove = useMutation({
    mutationFn: (v: ExplanationVersion) => request<ExplanationView>(`/explanation-versions/${v.id}`, { method: "DELETE" }),
    onSuccess: (view) => {
      qc.setQueryData(explanationKey(conceptId), view);
      setDeleting(null);
    },
  });
  const restore = useMutation({
    mutationFn: (v: ExplanationVersion) => request<ExplanationView>(`/explanation-versions/${v.id}/restore`, { method: "POST", json: {} }),
    onSuccess: (view) => qc.setQueryData(explanationKey(conceptId), view),
  });
  return (
    <Async q={q}>
      {(view) => {
        const versions = view.versions;
        const newest = versions[versions.length - 1];
        return (
          <div className="stack" style={{ gap: 14 }}>
            <p className="tiny muted" style={{ margin: 0 }}>
              {C2C_TRAINS}
            </p>
            {newest ? (
              <Version v={newest} previous={versions[versions.length - 2]} onDelete={setDeleting} open />
            ) : (
              <p className="small" style={{ margin: 0 }}>
                Explain {view.concept.term} in your own words. Each save is a new version; your assistant tells you what
                is correct, missing or wrong when you ask it.
              </p>
            )}
            {versions.length > 1 && (
              <div className="stack" style={{ gap: 6 }}>
                {versions
                  .slice(0, -1)
                  .reverse()
                  .map((v) => (
                    <Version key={v.id} v={v} previous={versions[versions.indexOf(v) - 1]} onDelete={setDeleting} open={false} />
                  ))}
              </div>
            )}
            {writing || !newest ? (
              <ExplanationWriter conceptId={conceptId} term={view.concept.term} last={newest} onSaved={() => setWriting(false)} />
            ) : (
              <div>
                <button type="button" className="btn" onClick={() => setWriting(true)}>
                  Write a new version
                </button>
              </div>
            )}
            {view.deleted.length > 0 && (
              <details>
                <summary className="tiny">Recently deleted ({view.deleted.length})</summary>
                <ul className="list">
                  {view.deleted.map((v) => (
                    <li key={v.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                      <span className="small">
                        Version {v.number} · deleted {v.deleted_at ? dateTime(v.deleted_at) : ""}
                      </span>
                      <button type="button" className="btn small ghost" onClick={() => restore.mutate(v)} disabled={restore.isPending}>
                        Restore
                      </button>
                    </li>
                  ))}
                </ul>
                {restore.error && <ErrorNote error={restore.error} />}
              </details>
            )}
            <Confirm
              open={deleting !== null}
              title={`Delete version ${deleting?.number ?? ""}?`}
              confirmLabel="Delete version"
              danger
              busy={remove.isPending}
              onConfirm={() => deleting && remove.mutate(deleting)}
              onClose={() => setDeleting(null)}
            >
              It moves to “Recently deleted” with its feedback and can be restored for 30 days. Version numbers are not
              reused.
              {remove.error && <ErrorNote error={remove.error} />}
            </Confirm>
          </div>
        );
      }}
    </Async>
  );
}

/** /explain?concept=…&source=… — the link an assistant gives when its app cannot show the form. */
export function ExplainPage() {
  const [params] = useSearchParams();
  const conceptId = params.get("concept") ?? "";
  const source = params.get("source") === "discuss" ? "discuss" : "learner";
  const q = useExplanation(conceptId);
  const [saved, setSaved] = useState<number | null>(null);
  if (!conceptId) {
    return (
      <div className="page">
        <PageHead title="Concept-to-Clarity" />
        <p className="notice warn">This link is incomplete. Ask your assistant for the explanation link again.</p>
      </div>
    );
  }
  return (
    <div className="page">
      <Async q={q}>
        {(view) => {
          const versions = view.versions;
          const last = versions[versions.length - 1];
          return (
            <>
              <PageHead
                title={`Explain: ${view.concept.term}`}
                sub={C2C_TRAINS}
                crumbs={[{ to: `/concepts/${conceptId}`, label: view.concept.term }]}
              />
              <div className="stack" style={{ gap: 16, maxWidth: 760 }}>
                {saved !== null ? (
                  <>
                    <BackToAssistant what={`Saved as version ${saved}.`} />
                    <Link to={`/concepts/${conceptId}`}>See all versions of your explanation</Link>
                  </>
                ) : (
                  <>
                    {last && (
                      <details>
                        <summary className="small">Your last version (v{last.number})</summary>
                        <p className="reading pre small">{last.text}</p>
                      </details>
                    )}
                    <ExplanationWriter
                      conceptId={conceptId}
                      term={view.concept.term}
                      source={source}
                      last={last}
                      onSaved={(v) => setSaved(v.versions[v.versions.length - 1]?.number ?? null)}
                    />
                  </>
                )}
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}

/** In Chat: the explanation form ChatGPT asked for. */
export function ChatExplanationForm({
  conceptId,
  source,
  onSaved,
}: {
  conceptId: string;
  source: "learner" | "discuss";
  onSaved: (version: number, term: string) => void;
}) {
  const q = useExplanation(conceptId);
  const [saved, setSaved] = useState<number | null>(null);
  return (
    <Async q={q}>
      {(view) => {
        const versions = view.versions;
        if (saved !== null) {
          const v = versions.find((x) => x.number === saved);
          return (
            <div className="stack" style={{ gap: 6 }}>
              <span className="tiny muted">
                Your explanation of {view.concept.term} · version {saved}
              </span>
              {v && (
                <p className="reading pre small" style={{ margin: 0 }}>
                  {v.text}
                </p>
              )}
            </div>
          );
        }
        return (
          <div className="stack" style={{ gap: 8 }}>
            <span className="tiny muted">Concept-to-Clarity · {C2C_TRAINS}</span>
            <ExplanationWriter
              conceptId={conceptId}
              term={view.concept.term}
              source={source}
              last={versions[versions.length - 1]}
              onSaved={(next) => {
                const n = next.versions[next.versions.length - 1]?.number ?? 0;
                setSaved(n);
                onSaved(n, view.concept.term);
              }}
            />
          </div>
        );
      }}
    </Async>
  );
}
