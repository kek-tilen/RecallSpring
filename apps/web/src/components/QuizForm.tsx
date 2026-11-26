import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { newKey, request } from "../api";
import { AnswerClock, questionOfTarget, watchActivity } from "../answerClock";
import { UNSURE_HINT, plural } from "../format";
import type { QuizView } from "../types";
import { CopyButton } from "./Copy";
import { useAssistant } from "../assistant";
import { MathText } from "./Markdown";
import { Confirm, ErrorNote } from "./ui";

type Answer = {
  option?: string | null;
  text?: string | null;
  dont_know?: boolean;
  guessing?: boolean;
  unsure?: boolean; // an open answer the learner marked as unsure (2026-11-26)
  answer_seconds?: number | null; // ADR-014 §3: time on the question, saved with the draft
};

/** Every answer with the time spent on its question, also questions only read so far (their time is kept). */
function withTime(answers: Record<string, Answer>, clock: AnswerClock) {
  const seconds = clock.all();
  const ids = new Set([...Object.keys(answers), ...Object.keys(seconds)]);
  return [...ids].map((question_id) => ({ question_id, ...answers[question_id], answer_seconds: seconds[question_id] ?? null }));
}

export function gradingPrompt(quiz: { title: string; quiz_id: string }): string {
  return `I solved the simulation "${quiz.title}" in RecallSpring (ID ${quiz.quiz_id}). Please grade my open answers and tell me what to repeat.`;
}

/** Shown on a submitted simulation whose open answers still wait for the assistant's grade. */
export function AwaitingGrade({ quiz }: { quiz: { title: string; quiz_id: string; pending_items?: number } }) {
  const a = useAssistant();
  return (
    <div className="notice stack" role="status" style={{ gap: 8 }}>
      <strong>{plural(quiz.pending_items ?? 0, "open answer")} waiting for a grade.</strong>
      <span className="small">
        {a.key === "chatgpt"
          ? "Paste this into Chat with this course picked under Study. Your answers are already saved."
          : `Paste this into a chat of this course, or just tell ${a.name} “check my simulation”. Your answers are already saved.`}
      </span>
      <div className="answer small">{gradingPrompt(quiz)}</div>
      <div className="row">
        <CopyButton text={gradingPrompt(quiz)} label={`Copy message for ${a.name}`} className="btn small primary" />
        <CopyButton text={quiz.quiz_id} label="Copy ID" />
      </div>
    </div>
  );
}

function remaining(deadline: string | null | undefined, now: number): string | null {
  if (!deadline) return null;
  const ms = Date.parse(deadline) - now;
  if (ms <= 0) return "Time is up";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}:${String(s).padStart(2, "0")} left`;
}

/** The simulation form in the web app: the same questions the assistant's form shows, saved as a draft while you work. */
export function QuizForm({ quiz }: { quiz: QuizView }) {
  const qc = useQueryClient();
  const [view, setView] = useState(quiz);
  const [answers, setAnswers] = useState<Record<string, Answer>>(quiz.draft ?? {});
  const [saved, setSaved] = useState<string | null>(quiz.draft_saved_at ?? null);
  const [confirm, setConfirm] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const timer = useRef<number | undefined>(undefined);
  const submitKey = useRef(newKey());
  const [clock] = useState(
    () => new AnswerClock(Object.fromEntries(Object.entries(quiz.draft ?? {}).map(([id, a]) => [id, (a as Answer).answer_seconds]))),
  );
  const started = Boolean(view.opened_at);
  const needsStart = Boolean(view.time_limit_minutes) && !started;

  const open = useMutation({
    mutationFn: () => request<QuizView>(`/quizzes/${quiz.quiz_id}/open`, { method: "POST" }),
    onSuccess: (form) => {
      setView(form);
      if (form.draft) setAnswers((a) => ({ ...form.draft, ...a }));
    },
  });
  const draft = useMutation({
    mutationFn: (current: Record<string, Answer>) =>
      request<{ saved_at: string }>(`/quizzes/${quiz.quiz_id}/draft`, {
        method: "POST",
        json: { answers: withTime(current, clock) },
      }),
    onSuccess: (r) => setSaved(r.saved_at),
  });
  const submit = useMutation({
    mutationFn: () =>
      request<QuizView>(`/quizzes/${quiz.quiz_id}/submit`, {
        method: "POST",
        key: submitKey.current,
        json: {
          client_request_id: submitKey.current,
          answers: withTime(answers, clock),
        },
      }),
    onSuccess: (result) => {
      window.clearTimeout(timer.current);
      qc.setQueryData(["quiz", quiz.quiz_id], result);
      void qc.invalidateQueries({ queryKey: ["quizzes"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      void qc.invalidateQueries({ queryKey: ["courses"] });
      setConfirm(false);
    },
  });

  useEffect(() => {
    if (!view.deadline) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [view.deadline]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => watchActivity(clock, document, questionOfTarget), [clock]);

  function change(questionId: string, next: Answer) {
    if (!started && !open.isPending) open.mutate();
    const updated = { ...answers, [questionId]: { ...answers[questionId], ...next } };
    setAnswers(updated);
    setSaved(null);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => draft.mutate(updated), 1200);
  }

  const answered = view.items.filter((i) => {
    const a = answers[i.question_id];
    return a && (a.dont_know || a.option || (a.text ?? "").trim());
  }).length;
  const left = remaining(view.deadline, now);

  if (needsStart) {
    return (
      <div className="card stack">
        <h2>Answer it here</h2>
        <p className="small">
          {plural(view.items.length, "question")} · {view.time_limit_minutes} minutes. The clock starts when you press Start, like in the
          real midterm. Your answers are saved as you type.
        </p>
        {open.error && <ErrorNote error={open.error} />}
        <div>
          <button type="button" className="btn primary" onClick={() => open.mutate()} disabled={open.isPending}>
            Start
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="quiz-form"
      onSubmit={(e) => {
        e.preventDefault();
        setConfirm(true);
      }}
    >
      {view.items.map((item) => {
        const a = answers[item.question_id] ?? {};
        return (
          <div key={item.question_id} className="quiz-q" data-question-id={item.question_id}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
              <strong id={`q-${item.question_id}`}>
                {item.position}. <MathText text={item.prompt} />
              </strong>
              <span className="small muted nowrap">{plural(item.points, "point")}</span>
            </div>
            {item.type === "mcq" && item.options ? (
              <fieldset aria-labelledby={`q-${item.question_id}`}>
                {item.options.map((o) => (
                  <label key={o.key} className="choice">
                    <input
                      type="radio"
                      name={item.question_id}
                      checked={a.option === o.key && !a.dont_know}
                      onChange={() => change(item.question_id, { option: o.key, dont_know: false })}
                    />
                    <span>
                      <strong>{o.key}</strong> <MathText text={o.text} />
                    </span>
                  </label>
                ))}
              </fieldset>
            ) : (
              <label>
                <span className="sr-only">Your answer</span>
                <textarea
                  rows={5}
                  value={a.text ?? ""}
                  aria-labelledby={`q-${item.question_id}`}
                  onChange={(e) => change(item.question_id, { text: e.target.value, dont_know: false })}
                  disabled={a.dont_know}
                />
              </label>
            )}
            <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
              {item.type !== "mcq" && !a.dont_know && (a.text ?? "").trim() ? (
                // an open answer with text: "Unsure" takes the place of "I don't know"
                <button
                  type="button"
                  className="guess-toggle"
                  aria-pressed={Boolean(a.unsure)}
                  title={UNSURE_HINT}
                  onClick={() => change(item.question_id, { unsure: !a.unsure })}
                >
                  Unsure
                </button>
              ) : (
                <label className="row small muted">
                  <input
                    type="checkbox"
                    checked={Boolean(a.dont_know)}
                    onChange={(e) =>
                      change(item.question_id, {
                        dont_know: e.target.checked,
                        ...(e.target.checked ? { option: null, guessing: false, unsure: false } : {}),
                      })
                    }
                  />
                  I don't know
                </label>
              )}
              {item.type === "mcq" && (
                <button
                  type="button"
                  className="guess-toggle"
                  aria-pressed={Boolean(a.guessing)}
                  disabled={a.dont_know}
                  title="A guess never counts as known, even when it is right"
                  onClick={() => change(item.question_id, { guessing: !a.guessing })}
                >
                  I'm guessing
                </button>
              )}
            </div>
          </div>
        );
      })}
      <div className="sticky-bar">
        <span className="small" role="status" aria-live="polite">
          {answered} of {view.items.length} answered ·{" "}
          {draft.isPending ? "Saving…" : saved ? "Draft saved" : answered ? "Unsaved changes" : "Nothing answered yet"}
          {left && <strong style={{ marginLeft: 8 }}>{left}</strong>}
        </span>
        <button type="submit" className="btn primary" disabled={submit.isPending}>
          Submit simulation
        </button>
      </div>
      {draft.error && <ErrorNote error={draft.error} />}
      <Confirm
        open={confirm}
        title="Submit the simulation?"
        confirmLabel="Submit"
        busy={submit.isPending}
        onConfirm={() => submit.mutate()}
        onClose={() => setConfirm(false)}
      >
        {answered < view.items.length
          ? `${plural(view.items.length - answered, "question")} left empty will count as “I don't know”. `
          : ""}
        After submitting you cannot change your answers. Multiple-choice questions are graded right away; your assistant grades the open
        answers when you ask it to.
        {submit.error && <ErrorNote error={submit.error} />}
      </Confirm>
    </form>
  );
}
