import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { get, newKey, request } from "../api";
import { GRADE_LABEL, gradeLabel } from "../format";
import { keys } from "../queries";
import type { AssessmentDetail, AttemptDetail } from "../types";
import { Async, ErrorNote } from "./ui";

/**
 * Self-assessment (owner decision 2026-11-22): when no assistant is available, the learner checks their saved
 * answer against the question's expected points. RecallSpring suggests a grade from the marks; the grade is the
 * learner's own, provisional (a short follow-up only, never a longer interval) and an assistant checks it later.
 */

type PointState = "met" | "partial" | "missing";

interface SelfCheckView {
  attempt_id: string;
  available: boolean;
  reason: string | null;
  message: string | null;
  question: { id: string; prompt: string; bloom_level: number };
  expected_points: string[];
  sources: string[];
  self_assessment: { grade: number | null; points: PointState[] | null } | null;
}

const STATES: { value: PointState; label: string }[] = [
  { value: "met", label: "Got it" },
  { value: "partial", label: "Partly" },
  { value: "missing", label: "Missed" },
];

/** The same rule as the server (services/self_assessment.py): all met → 3; at least half → 2; some → 1; none → 0. */
export function suggestedGrade(states: PointState[]): number {
  if (states.length === 0) return 0;
  const met = states.filter((s) => s === "met").length;
  if (met === states.length) return 3;
  const score = (met + 0.5 * states.filter((s) => s === "partial").length) / states.length;
  return score >= 0.5 ? 2 : score > 0 ? 1 : 0;
}

/** A self-assessed grade is marked as the learner's own wherever a grade is shown. */
export function SelfTag({ a }: { a: Pick<AssessmentDetail, "evaluator_kind"> | null | undefined }) {
  if (a?.evaluator_kind !== "self") return null;
  return (
    <span className="chip self-tag" title="You graded this answer yourself; an assistant checks it later.">
      Self-assessed · to be checked
    </span>
  );
}

/** "Your self-assessment was 3/4, the check gave 1/4." when an assistant's check differs by two or more. */
export function SelfCheckNote({ attempt }: { attempt: AttemptDetail }) {
  const own = attempt.assessments.find((s) => s.evaluator_kind === "self");
  const current = attempt.assessments.find((s) => s.id === attempt.effective_assessment_id);
  if (!own || !current || current.evaluator_kind === "self" || own.grade === null || current.grade === null) return null;
  if (Math.abs(own.grade - current.grade) < 2) return null;
  return (
    <p className="notice small" style={{ margin: 0 }}>
      Your self-assessment was {gradeLabel(own.grade)}; the check gave {gradeLabel(current.grade)}. The feedback says which
      expected points decided it.
    </p>
  );
}

/** A button that opens the self-assessment for an answer without a grade. */
export function SelfAssessOffer({ attemptId, intro }: { attemptId: string; intro?: string }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <div className="row small" style={{ gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn small" onClick={() => setOpen(true)}>
          Grade it myself
        </button>
        <span className="muted">{intro ?? "No assistant available? Check your answer against the expected points."}</span>
      </div>
    );
  }
  return <SelfAssess attemptId={attemptId} />;
}

export function SelfAssess({ attemptId, onDone }: { attemptId: string; onDone?: () => void }) {
  const view = useQuery({
    queryKey: ["self-assessment", attemptId],
    queryFn: () => get<SelfCheckView>(`/attempts/${attemptId}/self-assessment`),
  });
  return <Async q={view}>{(v) => <SelfAssessForm v={v} onDone={onDone} />}</Async>;
}

function SelfAssessForm({ v, onDone }: { v: SelfCheckView; onDone?: () => void }) {
  const qc = useQueryClient();
  const [states, setStates] = useState<(PointState | null)[]>(() => v.expected_points.map(() => null));
  const [chosen, setChosen] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [key] = useState(newKey);
  const complete = states.every((s): s is PointState => s !== null);
  const suggested = complete ? suggestedGrade(states as PointState[]) : null;
  const grade = chosen ?? suggested;
  const save = useMutation({
    mutationFn: () =>
      request<AttemptDetail>(`/attempts/${v.attempt_id}/self-assessment`, {
        key,
        json: { points: states, grade, reason: reason.trim() || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["self-assessment", v.attempt_id] });
      void qc.invalidateQueries({ queryKey: ["attempt", v.attempt_id] });
      void qc.invalidateQueries({ queryKey: ["questions", v.question.id] });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      void qc.invalidateQueries({ queryKey: ["attempts"] });
      onDone?.();
    },
  });

  if (v.self_assessment) {
    return (
      <p className="notice small" role="status" style={{ margin: 0 }}>
        You assessed this answer yourself: {gradeLabel(v.self_assessment.grade)} (provisional). An assistant checks it next; its
        grade then replaces yours in your reviews.
      </p>
    );
  }
  if (!v.available) {
    return (
      <p className="small muted" style={{ margin: 0 }}>
        {v.message}
      </p>
    );
  }
  return (
    <form
      className="stack self-assess"
      style={{ gap: 10 }}
      aria-label="Grade your answer yourself"
      onSubmit={(e) => {
        e.preventDefault();
        if (complete && grade !== null) save.mutate();
      }}
    >
      <div>
        <strong className="small">Check your answer against the expected points</strong>
        <p className="tiny muted" style={{ margin: "2px 0 0" }}>
          Your grade is marked as self-assessed and counts only as provisional: your next review is a short follow-up, and an
          assistant checks it later.
          {v.sources.length > 0 && ` Compare with: ${v.sources.join("; ")}.`}
        </p>
      </div>
      <ol className="stack self-points" style={{ gap: 8, margin: 0, padding: 0 }}>
        {v.expected_points.map((point, i) => (
          <li key={i}>
            <fieldset className="self-point">
              <legend className="small">
                {i + 1}. {point}
              </legend>
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                {STATES.map((s) => (
                  <label key={s.value} className="row small" style={{ gap: 4 }}>
                    <input
                      type="radio"
                      name={`point-${v.attempt_id}-${i}`}
                      value={s.value}
                      checked={states[i] === s.value}
                      onChange={() => setStates((all) => all.map((x, j) => (j === i ? s.value : x)))}
                    />
                    {s.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </li>
        ))}
      </ol>
      {complete && (
        <div className="stack" style={{ gap: 8 }}>
          <label className="field">
            Your grade (suggested: {gradeLabel(suggested)})
            <select value={grade ?? 0} onChange={(e) => setChosen(Number(e.target.value))}>
              {GRADE_LABEL.map((label, g) => (
                <option key={g} value={g}>
                  {g}/4 · {label}
                </option>
              ))}
            </select>
          </label>
          {(grade === 4 || (grade !== null && grade !== suggested)) && (
            <label className="field">
              {grade === 4 ? "How does your answer go beyond the expected points?" : "Why this grade? (optional)"}
              <textarea rows={3} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
              {grade === 4 && <span className="hint">4 Transfer needs a reason: a new case, a counterexample or a link the material does not make.</span>}
            </label>
          )}
        </div>
      )}
      {save.error && <ErrorNote error={save.error} />}
      <div>
        <button
          type="submit"
          className="btn primary small"
          disabled={!complete || grade === null || (grade === 4 && !reason.trim()) || save.isPending}
        >
          Save my self-assessment
        </button>
      </div>
    </form>
  );
}
