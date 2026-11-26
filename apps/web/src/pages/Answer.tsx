import { ANSWER_FOLDER, AnswerPhotos, SavedPhotos, usePhotos } from "../components/Photos";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AnswerClock, watchActivity } from "../answerClock";
import { Link, useParams, useSearchParams } from "react-router";
import { get, newKey, request } from "../api";
import { SelfAssessOffer, SelfCheckNote, SelfTag } from "../components/SelfAssess";
import { MathText } from "../components/Markdown";
import { Async, Card, ErrorNote, GradeChip, PageHead } from "../components/ui";
import { UNSURE_HINT, dateTime } from "../format";
import { keys } from "../queries";
import type { AttemptDetail, ConceptRow } from "../types";

/**
 * Pages an assistant links to when it cannot show RecallSpring's forms inside its chat (e.g. Codex): answer one
 * question, or summarise what was just taught. The text is saved exactly as typed, before any assistant sees it.
 * A draft stays in this browser until it is saved, so closing the tab loses nothing.
 *
 * The same forms appear inside RecallSpring's Chat when ChatGPT asks for them (ChatAnswerForm, ChatSummaryForm):
 * there, saving also tells ChatGPT (onSaved), so the learner does not have to.
 */

interface QuestionView {
  id: string;
  course_id: string;
  bloom_level: number;
  prompt: string;
  rubric: Record<string, unknown> | null;
  latest_attempt_id?: string | null;
}

interface Draft {
  text: string;
  key: string; // client_request_id: the same one on every retry, so a lost response never saves twice
}

function readDraft(storeKey: string): Draft {
  try {
    const raw = localStorage.getItem(storeKey);
    if (raw) {
      const d = JSON.parse(raw) as Partial<Draft>;
      if (typeof d.text === "string" && typeof d.key === "string") return { text: d.text, key: d.key };
    }
  } catch {
    /* storage unavailable: start empty */
  }
  return { text: "", key: newKey() };
}

export function useDraft(storeKey: string): [Draft, (text: string) => void, () => void] {
  const [draft, setDraft] = useState<Draft>(() => readDraft(storeKey));
  useEffect(() => setDraft(readDraft(storeKey)), [storeKey]);
  const update = (text: string) => {
    const next = { ...draft, text };
    setDraft(next);
    try {
      localStorage.setItem(storeKey, JSON.stringify(next));
    } catch {
      /* storage full or blocked: the text is still on screen */
    }
  };
  const clear = () => {
    try {
      localStorage.removeItem(storeKey);
    } catch {
      /* ignore */
    }
  };
  return [draft, update, clear];
}

export function BackToAssistant({ what }: { what: string }) {
  return (
    <div className="notice stack" role="status">
      <strong>{what}</strong>
      <span className="small">Go back to your assistant and tell it you are done. It reads your text from RecallSpring.</span>
    </div>
  );
}

// ---------------------------------------------------------------- one question

interface Saved {
  attempt_id: string;
  saved_at: string;
}

export function AnswerPage() {
  const { questionId = "" } = useParams();
  const [params] = useSearchParams();
  const question = useQuery({ queryKey: ["questions", questionId], queryFn: () => get<QuestionView>(`/questions/${questionId}`) });
  return (
    <div className="page">
      <PageHead title="Answer a question" sub="Type your answer in your own words. It is saved exactly as you write it, before your assistant grades it." />
      <Async q={question}>{(q) => <AnswerForm key={q.id} q={q} sessionId={params.get("session")} />}</Async>
    </div>
  );
}

/** In Chat: the answer form ChatGPT asked for. ``onSaved`` runs after the answer is saved (then ChatGPT is told). */
export function ChatAnswerForm({
  questionId,
  onSaved,
}: {
  questionId: string;
  onSaved: (kind: AnswerKind, photoIds: string[], unsure: boolean) => void;
}) {
  const question = useQuery({ queryKey: ["questions", questionId], queryFn: () => get<QuestionView>(`/questions/${questionId}`) });
  return <Async q={question}>{(q) => <AnswerForm key={q.id} q={q} sessionId={null} onSaved={onSaved} />}</Async>;
}

export type AnswerKind = "answer" | "dont_know";

/**
 * In Chat, the answer form of an earlier turn: the question with the learner's newest answer to it (and its grade
 * once there is one), so the conversation still shows what was sent. Not answered yet: a link to the form.
 */
export function ChatSentAnswer({ questionId }: { questionId: string }) {
  const question = useQuery({ queryKey: ["questions", questionId], queryFn: () => get<QuestionView>(`/questions/${questionId}`) });
  const attemptId = question.data?.latest_attempt_id ?? null;
  const attempt = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: () => get<AttemptDetail>(`/attempts/${attemptId}`),
    enabled: !!attemptId,
  });
  return (
    <Async q={question} lines={2}>
      {(q) => {
        if (!q.latest_attempt_id) {
          return (
            <p className="tiny muted" style={{ margin: 0 }}>
              <Link to={`/answer/${q.id}`}>Answer form</Link> (not answered yet)
            </p>
          );
        }
        const a = attempt.data;
        const current = a ? (a.assessments.find((s) => s.id === a.effective_assessment_id) ?? a.assessments.at(-1)) : undefined;
        return (
          <div className="stack chat-form-saved" style={{ gap: 8 }}>
            <p className="tiny muted" style={{ margin: 0 }}>
              Question · Bloom {q.bloom_level}
            </p>
            <p className="pre" style={{ margin: 0, fontWeight: 600 }}>
              <MathText text={q.prompt} />
            </p>
            {attempt.error && <ErrorNote error={attempt.error} />}
            {a && (
              <>
                {a.kind === "answer" ? (
                  <div className="chat-form-answer pre" aria-label="Your answer">
                    {a.answer_text || "(photos only)"}
                  </div>
                ) : (
                  <p className="small muted" style={{ margin: 0 }}>
                    You said you don&apos;t know.
                  </p>
                )}
                <SavedPhotos ids={a.photos ?? []} label="Photos saved with your answer" />
                <div className="row tiny muted" style={{ gap: 8, flexWrap: "wrap" }}>
                  {a.kind === "answer" && a.unsure && <span className="chip">Unsure</span>}
                  {current && <GradeChip grade={current.grade} status={current.status} />}
                  <SelfTag a={current} />
                  <span>
                    Saved {dateTime(a.submitted_at)}
                    {!current && " · not graded yet"} · <Link to={`/courses/${q.course_id}?tab=answers`}>All answers</Link>
                  </span>
                </div>
                <SelfCheckNote attempt={a} />
                {!current && a.kind === "answer" && (
                  <SelfAssessOffer attemptId={a.id} intro="ChatGPT not available? Check your answer against the expected points." />
                )}
              </>
            )}
          </div>
        );
      }}
    </Async>
  );
}

/**
 * ADR-014 §3: how long this question is open and visible, without pauses over 5 minutes (time spent, never
 * learning). Kept in this browser with the draft, so a reload does not lose it; cleared once the answer is saved.
 */
function useAnswerClock(questionId: string): { clock: AnswerClock; saved: () => void } {
  const storeKey = `rs-answer-time:${questionId}`;
  const done = useRef(false);
  const [clock] = useState(() => {
    let start: number | null = null;
    try {
      start = Number(localStorage.getItem(storeKey)) || null;
    } catch {
      /* storage unavailable: start at zero */
    }
    return new AnswerClock({ [questionId]: start }, Date.now(), questionId);
  });
  useEffect(() => {
    const keep = () => {
      const seconds = clock.seconds(questionId);
      if (done.current || seconds === null) return;
      try {
        localStorage.setItem(storeKey, String(seconds));
      } catch {
        /* storage full or blocked: the time on screen still counts */
      }
    };
    const stop = watchActivity(clock, document);
    document.addEventListener("visibilitychange", keep);
    window.addEventListener("pagehide", keep);
    return () => {
      keep();
      stop();
      document.removeEventListener("visibilitychange", keep);
      window.removeEventListener("pagehide", keep);
    };
  }, [clock, questionId, storeKey]);
  const saved = () => {
    done.current = true;
    try {
      localStorage.removeItem(storeKey);
    } catch {
      /* ignore */
    }
  };
  return { clock, saved };
}

function AnswerForm({ q, sessionId, onSaved }: {
  q: QuestionView;
  sessionId: string | null;
  onSaved?: (kind: AnswerKind, photoIds: string[], unsure: boolean) => void;
}) {
  const qc = useQueryClient();
  const [draft, setText, clearDraft] = useDraft(`rs-answer-draft:${q.id}`);
  const [openNotes, setOpenNotes] = useState(false);
  // Owner 2026-11-26: "I don't know" while the box is empty; once there is an answer, "Unsure" marks it instead.
  const [unsure, setUnsure] = useState(false);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [savedPhotos, setSavedPhotos] = useState<string[]>([]);
  // In Chat the saved answer stays in the conversation, so the learner still sees what they sent.
  const [savedText, setSavedText] = useState<string | null>(null);
  const photos = usePhotos(q.course_id, ANSWER_FOLDER);
  const timing = useAnswerClock(q.id);
  const hasAnswer = !!draft.text.trim() || photos.ids.length > 0;
  const markedUnsure = hasAnswer && unsure;
  const save = useMutation({
    mutationFn: (kind: AnswerKind) =>
      request<Saved>("/attempts", {
        key: draft.key,
        json: {
          question_id: q.id,
          session_id: sessionId || null,
          client_request_id: draft.key,
          kind,
          answer_text: kind === "answer" ? draft.text : "",
          answer_mode: openNotes ? "open_notes" : "closed_notes",
          photo_ids: kind === "answer" ? photos.ids : [],
          answer_seconds: timing.clock.seconds(q.id),
          unsure: kind === "answer" && markedUnsure,
        },
      }),
    onSuccess: (s, kind) => {
      const sentPhotos = kind === "answer" ? photos.ids : [];
      timing.saved();
      clearDraft();
      photos.clear();
      setSavedPhotos(sentPhotos);
      setSavedText(kind === "answer" ? draft.text : null);
      setSaved(s);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      void qc.invalidateQueries({ queryKey: ["questions", q.id] });
      onSaved?.(kind, sentPhotos, kind === "answer" && markedUnsure);
    },
  });

  if (saved && onSaved) {
    return (
      <div className="stack chat-form-saved" style={{ gap: 8 }}>
        <p className="tiny muted" style={{ margin: 0 }}>
          Question · Bloom {q.bloom_level}
        </p>
        <p className="pre" style={{ margin: 0, fontWeight: 600 }}>
          <MathText text={q.prompt} />
        </p>
        {savedText !== null ? (
          <div className="chat-form-answer pre" aria-label="Your answer">
            {savedText || "(photos only)"}
          </div>
        ) : (
          <p className="small muted" style={{ margin: 0 }}>
            You said you don&apos;t know.
          </p>
        )}
        <p className="notice small" role="status" style={{ margin: 0 }}>
          Your answer was saved at {dateTime(saved.saved_at)}
          {savedText !== null && markedUnsure ? ", marked as unsure," : ""} and ChatGPT was told.
        </p>
        <SavedPhotos ids={savedPhotos.map((id) => ({ id }))} label="Photos saved with your answer" />
      </div>
    );
  }
  if (saved) {
    return (
      <Card title="Saved">
        <div className="stack" style={{ gap: 12 }}>
          <BackToAssistant
            what={`Your answer was saved at ${dateTime(saved.saved_at)}${savedText !== null && markedUnsure ? ", marked as unsure" : ""}.`}
          />
          <SavedPhotos ids={savedPhotos.map((id) => ({ id }))} label="Photos saved with your answer" />
          <p className="small muted" style={{ margin: 0 }}>
            Your assistant gives feedback; you can see it later under the concept in <Link to={`/courses/${q.course_id}`}>the course</Link>.
          </p>
          {savedText !== null && <SelfAssessOffer attemptId={saved.attempt_id} />}
        </div>
      </Card>
    );
  }

  return (
    <Card title={`Question · Bloom ${q.bloom_level}`}>
      <form
        className="stack"
        style={{ gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (hasAnswer && !photos.saving) save.mutate("answer");
        }}
        onPaste={photos.onPaste}
        {...photos.dropProps}
      >
        <p id="answer-prompt" className="pre" style={{ margin: 0, fontWeight: 600 }}>
          <MathText text={q.prompt} />
        </p>
        {q.rubric && (
          <p className="notice small" style={{ margin: 0 }}>
            You already answered this question once. A new answer is saved as another attempt.
          </p>
        )}
        <label className="field">
          Your answer
          <textarea rows={8} maxLength={20000} value={draft.text} aria-describedby="answer-prompt" onChange={(e) => setText(e.target.value)} />
          <span className="hint">The draft stays in this browser until you save it.</span>
        </label>
        <AnswerPhotos photos={photos} />
        <label className="row small">
          <input type="checkbox" checked={openNotes} onChange={(e) => setOpenNotes(e.target.checked)} />I used my notes or the material
        </label>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row">
          <button type="submit" className="btn primary" disabled={!hasAnswer || photos.saving || save.isPending}>
            {onSaved ? "Save and send to ChatGPT" : "Save answer"}
          </button>
          {hasAnswer ? (
            <button
              type="button"
              className="guess-toggle"
              aria-pressed={unsure}
              title={UNSURE_HINT}
              disabled={save.isPending}
              onClick={() => setUnsure(!unsure)}
            >
              Unsure
            </button>
          ) : (
            <button type="button" className="btn ghost" disabled={save.isPending} onClick={() => save.mutate("dont_know")}>
              I don't know
            </button>
          )}
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- summary of what was just taught

interface SummarySaved {
  note_id: string | null;
}

export function SummaryPage() {
  const [params] = useSearchParams();
  const courseId = params.get("course") ?? "";
  const wanted = (params.get("concepts") ?? "").split(",").filter(Boolean);
  const title = (params.get("title") ?? "").slice(0, 200);
  const covered = params.get("covered");
  const concepts = useQuery({
    queryKey: ["courses", courseId, "concepts"],
    queryFn: () => get<ConceptRow[]>(`/courses/${courseId}/concepts`),
    enabled: Boolean(courseId),
  });
  if (!courseId || wanted.length === 0 || !title) {
    return (
      <div className="page">
        <PageHead title="Summarise what you learned" />
        <p className="notice warn">This link is incomplete. Ask your assistant for the summary link again.</p>
      </div>
    );
  }
  return (
    <div className="page">
      <PageHead title="Summarise what you learned" sub="In your own words. It is saved exactly as you write it, as your note, and the topics count as studied." />
      <Async q={concepts}>
        {(rows) => {
          const chosen = rows.filter((c) => wanted.includes(c.id));
          if (chosen.length === 0) return <p className="notice warn">These topics are not in this course. Ask your assistant for the link again.</p>;
          return <SummaryForm courseId={courseId} title={title} covered={covered} concepts={chosen} />;
        }}
      </Async>
    </div>
  );
}

/** In Chat: the summary form ChatGPT asked for after teaching a chunk. */
export function ChatSummaryForm({
  courseId,
  conceptIds,
  title,
  covered,
  onSaved,
}: {
  courseId: string;
  conceptIds: string[];
  title: string;
  covered: string | null;
  onSaved: () => void;
}) {
  const concepts = useQuery({ queryKey: ["courses", courseId, "concepts"], queryFn: () => get<ConceptRow[]>(`/courses/${courseId}/concepts`) });
  return (
    <Async q={concepts}>
      {(rows) => {
        const chosen = rows.filter((c) => conceptIds.includes(c.id));
        if (chosen.length === 0) return <p className="notice warn small">These topics are no longer in the course.</p>;
        return <SummaryForm courseId={courseId} title={title} covered={covered} concepts={chosen} onSaved={onSaved} />;
      }}
    </Async>
  );
}

function SummaryForm({
  courseId,
  title,
  covered,
  concepts,
  onSaved,
}: {
  courseId: string;
  title: string;
  covered: string | null;
  concepts: ConceptRow[];
  onSaved?: () => void;
}) {
  const qc = useQueryClient();
  const [draft, setText, clearDraft] = useDraft(`rs-summary-draft:${courseId}:${title}`);
  const [done, setDone] = useState<SummarySaved | null>(null);
  const [savedText, setSavedText] = useState("");
  const save = useMutation({
    mutationFn: () =>
      request<SummarySaved>("/learning", {
        key: draft.key,
        json: { course_id: courseId, concept_ids: concepts.map((c) => c.id), title, text: draft.text, client_request_id: draft.key },
      }),
    onSuccess: (s) => {
      setSavedText(draft.text);
      clearDraft();
      setDone(s);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      void qc.invalidateQueries({ queryKey: keys.course(courseId) });
      onSaved?.();
    },
  });

  if (done && onSaved) {
    return (
      <div className="stack chat-form-saved" style={{ gap: 8 }}>
        <p className="tiny muted" style={{ margin: 0 }}>
          Summary · {title}
        </p>
        <div className="chat-form-answer pre" aria-label="Your summary">
          {savedText}
        </div>
        <p className="notice small" role="status" style={{ margin: 0 }}>
          {done.note_id ? "Your summary was saved as a note" : "Saved"}; these topics now count as studied. ChatGPT was told.
        </p>
      </div>
    );
  }
  if (done) {
    return (
      <Card title="Saved">
        <BackToAssistant what={done.note_id ? "Your summary was saved as a note; these topics now count as studied." : "These topics now count as studied."} />
      </Card>
    );
  }

  return (
    <Card title={title} meta={covered ?? undefined}>
      <form
        className="stack"
        style={{ gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }} aria-label="Topics">
          {concepts.map((c) => (
            <span key={c.id} className="chip">
              {c.term}
            </span>
          ))}
        </div>
        <label className="field">
          Your summary
          <textarea rows={10} maxLength={200000} value={draft.text} onChange={(e) => setText(e.target.value)} />
          <span className="hint">You may leave it empty; the topics still count as studied. The draft stays in this browser until you save it.</span>
        </label>
        {save.error && <ErrorNote error={save.error} />}
        <div>
          <button type="submit" className="btn primary" disabled={save.isPending}>
            {onSaved ? "Save and send to ChatGPT" : "Save summary"}
          </button>
        </div>
      </form>
    </Card>
  );
}
