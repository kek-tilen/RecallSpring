import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "../api";
import { useAssistant } from "../assistant";
import { dateLabel, plural } from "../format";
import { keys } from "../queries";
import type { CheckResult, ConceptRow, CourseOverview, PracticeLimit } from "../types";
import { CopyButton } from "./Copy";
import { ErrorNote } from "./ui";

const TONE: Record<CheckResult["result"], string> = { green: "chip good", yellow: "chip warn", red: "chip bad", pending: "chip" };
const SHORT: Record<CheckResult["result"], string> = { green: "Know it", yellow: "Partly", red: "Not yet", pending: "Waiting" };

/** A concept's latest Check first result, only in the course details. */
export function CheckChip({ check }: { check: CheckResult | null | undefined }) {
  if (!check) return <span className="muted small">—</span>;
  const when = check.checked_at ? ` · checked ${dateLabel(check.checked_at)}` : "";
  return (
    <span className={TONE[check.result]} title={`${check.label}: ${check.why}${when}`}>
      {SHORT[check.result]}
    </span>
  );
}

function counts(concepts: ConceptRow[]) {
  const c = { green: 0, yellow: 0, red: 0, pending: 0, unchecked: 0 };
  for (const x of concepts) c[x.check ? x.check.result : "unchecked"] += 1;
  return c;
}

function summary(c: ReturnType<typeof counts>): string {
  const parts = [
    c.green && `${c.green} known`,
    c.yellow && `${c.yellow} partly`,
    c.red && `${c.red} not yet`,
    c.pending && `${c.pending} waiting`,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") + (c.unchecked ? ` · ${c.unchecked} not checked` : "") : "Not checked yet";
}

/** The message the learner gives their assistant; RecallSpring cannot write the questions itself. */
function Ask({ text }: { text: string }) {
  const a = useAssistant();
  return (
    <div className="stack check-ask" style={{ gap: 6 }}>
      <span className="tiny muted">Give this to {a.name}; it writes a short check from your material.</span>
      <div className="answer small">{text}</div>
      <div>
        <CopyButton text={text} label={`Copy message for ${a.name}`} />
      </div>
    </div>
  );
}

/** Check first, offered quietly: per chapter, and a bit of everything for the next exam (or the whole course). */
export function CheckFirstPanel({ o }: { o: CourseOverview }) {
  const [asking, setAsking] = useState<string | null>(null);
  const byId = new Map(o.concepts.map((c) => [c.id, c]));
  const chapters = (o.chapters ?? []).map((ch) => ({
    ...ch,
    concepts: ch.concept_ids.map((id) => byId.get(id)).filter((c): c is ConceptRow => Boolean(c)),
  }));
  if (!chapters.length) return null;
  const active = o.targets.find((t) => t.id === o.active_target_id);
  const scope = active ? active.name : "the whole course";
  const toggle = (key: string) => setAsking(asking === key ? null : key);
  return (
    <details className="check-first">
      <summary>Already know some of this? You can check first</summary>
      <div className="stack" style={{ gap: 10, marginTop: 10 }}>
        <p className="small muted" style={{ margin: 0 }}>
          A short check shows what you already know. Known concepts move to the background with rare reviews; the rest comes first.
          Learning first stays the default, so use it only when it saves you time.
        </p>
        <div className="check-row">
          <span>
            <strong>A bit of everything</strong> <span className="small muted">for {scope}</span>
          </span>
          <button type="button" className="linklike small" aria-expanded={asking === "all"} onClick={() => toggle("all")}>
            Check a bit of everything
          </button>
        </div>
        {asking === "all" && <Ask text={`Check a bit of everything for ${scope} in ${o.course.title} with RecallSpring's Check first.`} />}
        {chapters.map((ch) => (
          <div key={ch.key} className="stack" style={{ gap: 6 }}>
            <div className="check-row">
              <span>
                <strong>{ch.title}</strong>{" "}
                <span className="small muted">
                  {plural(ch.concepts.length, "concept")} · {summary(counts(ch.concepts))}
                </span>
              </span>
              <button type="button" className="linklike small" aria-expanded={asking === ch.key} onClick={() => toggle(ch.key)}>
                Check what I know
              </button>
            </div>
            {asking === ch.key && (
              <Ask text={`Check what I already know in “${ch.title}” of ${o.course.title} with RecallSpring's Check first.`} />
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

const AUTO = "auto";
const LEVELS = [
  { level: 2, label: "2 Understand" },
  { level: 3, label: "3 Apply" },
  { level: 4, label: "4 Analyze" },
  { level: 5, label: "5 Evaluate" },
  { level: 6, label: "6 Create" },
];

/** The learner's practice limit: the highest Bloom level practice, simulations and checks may ask. */
export function PracticeLimitControl({ courseId, limit }: { courseId: string; limit: PracticeLimit }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (body: { level: number | null; keep_despite_exam?: boolean }) =>
      request<PracticeLimit>(`/courses/${courseId}/practice-limit`, { method: "PUT", json: body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.course(courseId) }),
  });
  return (
    <div className="stack" style={{ gap: 8 }}>
      <label className="row small" style={{ gap: 8, flexWrap: "wrap" }}>
        <span>Practise up to</span>
        <select
          style={{ width: "auto" }}
          value={limit.set_by_learner ? limit.level : AUTO}
          disabled={save.isPending}
          onChange={(e) => save.mutate({ level: e.target.value === AUTO ? null : Number(e.target.value) })}
          aria-describedby="practice-limit-hint"
        >
          {/* 2026-11-26: automatic is 5, or 6 Create while an exam paper asks for it */}
          <option value={AUTO}>Automatic ({limit.set_by_learner ? "5 or 6" : `${limit.level} ${limit.label}`})</option>
          {LEVELS.map((l) => (
            <option key={l.level} value={l.level}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <span id="practice-limit-hint" className="tiny muted">
        Bloom level: practice climbs 3 Apply → 4 Analyze → 5 Evaluate (→ 6 Create at a limit of 6), never above your limit.
        {!limit.set_by_learner && limit.automatic ? ` Automatic: ${limit.automatic}` : ""}
      </span>
      {limit.model_tip && (
        <p className="notice small" role="note" style={{ margin: 0 }}>
          {limit.model_tip}
        </p>
      )}
      {limit.warning && (
        <div className="notice warn small stack" style={{ gap: 6 }} role="status">
          <span>{limit.warning}</span>
          <div>
            <button type="button" className="btn small" disabled={save.isPending} onClick={() => save.mutate({ level: limit.level, keep_despite_exam: true })}>
              Keep my limit
            </button>
          </div>
        </div>
      )}
      {save.error && <ErrorNote error={save.error} />}
    </div>
  );
}
