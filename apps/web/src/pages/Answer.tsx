import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { get, newKey, request } from "../api";
import { Async, Card, ErrorNote, PageHead } from "../components/ui";
import { dateTime } from "../format";
import { keys } from "../queries";
import type { ConceptRow } from "../types";

/**
 * Pages an assistant links to when it cannot show RecallSpring's forms inside its chat (e.g. Codex): answer one
 * question, or summarise what was just taught. The text is saved exactly as typed, before any assistant sees it.
 * A draft stays in this browser until it is saved, so closing the tab loses nothing.
 */

interface QuestionView {
  id: string;
  course_id: string;
  bloom_level: number;
  prompt: string;
  rubric: Record<string, unknown> | null;
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

function useDraft(storeKey: string): [Draft, (text: string) => void, () => void] {
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

function BackToAssistant({ what }: { what: string }) {
  return (
    <div className="notice stack" role="status">
      <strong>{what}</strong>
      <span className="small">Go back to your assistant (Codex or Claude) and tell it you are done. It reads your text from RecallSpring.</span>
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
      <Async q={question}>{(q) => <AnswerForm q={q} sessionId={params.get("session")} />}</Async>
    </div>
  );
}

function AnswerForm({ q, sessionId }: { q: QuestionView; sessionId: string | null }) {
  const qc = useQueryClient();
  const [draft, setText, clearDraft] = useDraft(`rs-answer-draft:${q.id}`);
  const [openNotes, setOpenNotes] = useState(false);
  const [saved, setSaved] = useState<Saved | null>(null);
  const save = useMutation({
    mutationFn: (kind: "answer" | "dont_know") =>
      request<Saved>("/attempts", {
        key: draft.key,
        json: {
          question_id: q.id,
          session_id: sessionId || null,
          client_request_id: draft.key,
          kind,
          answer_text: kind === "answer" ? draft.text : "",
          answer_mode: openNotes ? "open_notes" : "closed_notes",
        },
      }),
    onSuccess: (s) => {
      clearDraft();
      setSaved(s);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });

  if (saved) {
    return (
      <Card title="Saved">
        <div className="stack" style={{ gap: 12 }}>
          <BackToAssistant what={`Your answer was saved at ${dateTime(saved.saved_at)}.`} />
          <p className="small muted" style={{ margin: 0 }}>
            Your assistant gives feedback; you can see it later under the concept in <Link to={`/courses/${q.course_id}`}>the course</Link>.
          </p>
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
          if (draft.text.trim()) save.mutate("answer");
        }}
      >
        <p id="answer-prompt" className="pre" style={{ margin: 0, fontWeight: 600 }}>
          {q.prompt}
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
        <label className="row small">
          <input type="checkbox" checked={openNotes} onChange={(e) => setOpenNotes(e.target.checked)} />I used my notes or the material
        </label>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row">
          <button type="submit" className="btn primary" disabled={!draft.text.trim() || save.isPending}>
            Save answer
          </button>
          <button type="button" className="btn ghost" disabled={save.isPending} onClick={() => save.mutate("dont_know")}>
            I don't know
          </button>
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

function SummaryForm({ courseId, title, covered, concepts }: { courseId: string; title: string; covered: string | null; concepts: ConceptRow[] }) {
  const qc = useQueryClient();
  const [draft, setText, clearDraft] = useDraft(`rs-summary-draft:${courseId}:${title}`);
  const [done, setDone] = useState<SummarySaved | null>(null);
  const save = useMutation({
    mutationFn: () =>
      request<SummarySaved>("/learning", {
        key: draft.key,
        json: { course_id: courseId, concept_ids: concepts.map((c) => c.id), title, text: draft.text, client_request_id: draft.key },
      }),
    onSuccess: (s) => {
      clearDraft();
      setDone(s);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      void qc.invalidateQueries({ queryKey: keys.course(courseId) });
    },
  });

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
            Save summary
          </button>
        </div>
      </form>
    </Card>
  );
}
