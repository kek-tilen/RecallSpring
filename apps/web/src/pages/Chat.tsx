import { PhotoStrip, SavedPhotos, usePhotos } from "../components/Photos";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, get, request, streamRequest } from "../api";
import { ChatGptSignIn, STATUS_KEY, useChatGptStatus } from "../components/ChatGpt";
import { AttachDialog } from "../components/ChatAttach";
import { MaterialPicker, MAX_FILES, type ChosenFile } from "../components/ChatMaterial";
import { Markdown, VISUAL_LANG, type Cites } from "../components/Markdown";
import type { VisualResult } from "../components/Visual";
import { Confirm, ErrorNote, Loading } from "../components/ui";
import { dateTime, plural } from "../format";
import { keys } from "../queries";
import type { Course } from "../types";
import { ChatExplanationForm } from "../components/Clarity";
import { ChatAnswerForm, ChatSentAnswer, ChatSummaryForm } from "./Answer";

interface Usage {
  input_tokens?: number;
  cached_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
}

interface AiMessage {
  id: string;
  position: number;
  role: "user" | "assistant";
  text: string;
  created_at: string;
  completed_at: string | null;
  model_requested: string | null;
  model: string | null;
  response_id: string | null;
  account: string | null;
  usage: Usage | null;
  duration_ms: number | null;
  error_code: string | null;
  visuals: VisualResult[];
  citations: Cites;
  context: SentExcerpt[];
  tool_calls: ToolStep[];
  photo_ids?: string[];
}

/** A form ChatGPT asked RecallSpring to show (services/chat_tools.py). */
type ToolForm =
  | { kind: "answer"; question_id: string }
  | { kind: "summary"; course_id: string; concept_ids: string[]; title: string; covered: string | null }
  | { kind: "quiz"; quiz_id: string; title: string | null }
  | { kind: "explanation"; concept_id: string; term: string; source: "learner" | "discuss" };

/** What ChatGPT read or saved in RecallSpring while answering a message. */
interface ToolStep {
  call_id: string;
  name: string;
  status: "ok" | "error";
  error_code: string | null;
  summary: string;
  writes: boolean;
  ms: number;
  form?: ToolForm;
}

/** An excerpt of a chosen file that was sent with the learner's message. */
interface SentExcerpt {
  ref: string;
  section_id: string;
  source_id: string;
  filename: string;
  label: string;
  chars: number;
}

interface Totals {
  replies: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  messages: AiMessage[];
  material: ChosenFile[];
  totals: Totals;
  older_turns_not_sent: boolean;
  course: { id: string; title: string } | null;
}

interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  replies: number;
}

interface ConversationList {
  conversations: ConversationSummary[];
  deleted: ConversationSummary[];
  usage: { last_24_hours: Totals; last_30_days: Totals };
}

interface Model {
  slug: string;
  display_name: string;
}

const LIST_KEY = [...STATUS_KEY, "conversations"] as const;
const MODEL_STORE = "rs.chatgpt.model";
const VISUALS_STORE = "rs.chatgpt.visuals";
const TOOLS_STORE = "rs.chatgpt.recallspring";
const FULL_STORE = "rs.chat.fullpage";
const CHAT_FOLDER = "Chat images";

const NOT_ANSWERED: Record<string, string> = {
  usage_limit: "your ChatGPT plan's usage limit was reached",
  not_connected: "not signed in to ChatGPT",
  signed_out: "the ChatGPT sign-in had ended",
  plan_usage_not_enabled: "plan usage was not allowed",
  not_eligible: "this account can't use its plan in other apps",
  not_allowed: "ChatGPT refused the request",
  unavailable: "ChatGPT was not available",
  unsupported: "ChatGPT did not support the request",
  incomplete: "the reply stopped before it was complete",
  interrupted: "the reply was interrupted",
};

const number = (n: number) => n.toLocaleString("en-GB");

function exactTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function shortTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function totalsLine(t: Totals): string {
  return t.replies === 0
    ? "no replies"
    : `${plural(t.replies, "reply", "replies")} · ${number(t.total_tokens)} tokens`;
}

function remembered(key = MODEL_STORE): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function remember(value: string, key = MODEL_STORE): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window: the choice is simply not remembered */
  }
}

/** "GPT-6-Luna" plus the version part of what answered ("gpt-6-luna-2026-10-15" -> "2026-10-15"). */
function modelLabel(m: AiMessage, names: Map<string, string>): string {
  const chosen = m.model_requested ?? "";
  const name = names.get(chosen) ?? chosen;
  if (!m.model) return name || "model not reported";
  if (chosen && m.model.startsWith(`${chosen}-`)) return `${name} · ${m.model.slice(chosen.length + 1)}`;
  return m.model === chosen ? name : `${name} · ${m.model}`;
}

function ReplyMeta({ m, names }: { m: AiMessage; names: Map<string, string> }) {
  const [open, setOpen] = useState(false);
  const u = m.usage;
  const summary = [
    modelLabel(m, names),
    shortTime(m.completed_at ?? m.created_at),
    m.duration_ms !== null ? `${(m.duration_ms / 1000).toFixed(1)} s` : null,
    u?.total_tokens !== undefined ? `${number(u.total_tokens)} tokens` : "tokens not reported",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="chat-meta">
      <button type="button" className="linklike tiny muted" aria-expanded={open} onClick={() => setOpen(!open)}>
        {summary}
      </button>
      {open && (
        <dl className="kv tiny">
          <dt>Model chosen</dt>
          <dd>
            {names.get(m.model_requested ?? "") ?? m.model_requested} <span className="muted">({m.model_requested})</span>
          </dd>
          <dt>Answered by</dt>
          <dd>{m.model ?? "not reported"}</dd>
          <dt>Arrived</dt>
          <dd>{exactTime(m.completed_at ?? m.created_at)}</dd>
          {m.duration_ms !== null && (
            <>
              <dt>Took</dt>
              <dd>{(m.duration_ms / 1000).toFixed(1)} s</dd>
            </>
          )}
          {u && (
            <>
              <dt>Input tokens</dt>
              <dd>
                {number(u.input_tokens ?? 0)}
                {u.cached_tokens ? ` (${number(u.cached_tokens)} cached)` : ""}
              </dd>
              <dt>Output tokens</dt>
              <dd>
                {number(u.output_tokens ?? 0)}
                {u.reasoning_tokens ? ` (${number(u.reasoning_tokens)} reasoning)` : ""}
              </dd>
              <dt>Total</dt>
              <dd>{number(u.total_tokens ?? 0)}</dd>
            </>
          )}
          {m.account && (
            <>
              <dt>Account</dt>
              <dd>{m.account}</dd>
            </>
          )}
          {m.response_id && (
            <>
              <dt>Response ID</dt>
              <dd className="mono">{m.response_id}</dd>
            </>
          )}
        </dl>
      )}
    </div>
  );
}

/** What went to ChatGPT with a message: which excerpts of which chosen files. */
function SentWith({ items }: { items: SentExcerpt[] }) {
  const files = [...new Set(items.map((c) => c.filename))];
  return (
    <details className="chat-sent tiny muted">
      <summary>
        Sent with {plural(items.length, "excerpt")} from {files.length === 1 ? files[0] : plural(files.length, "file")}
      </summary>
      <ul>
        {items.map((c) => (
          <li key={c.ref}>
            <strong>{c.ref}</strong> <Link to={`/library/${c.source_id}`}>{c.filename}</Link> · {c.label}
          </li>
        ))}
      </ul>
    </details>
  );
}

function CitedSources({ cites }: { cites: Cites }) {
  const refs = Object.keys(cites).sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  if (!refs.length) return null;
  return (
    <ul className="chat-cited tiny" aria-label="Sources cited">
      {refs.map((r) => (
        <li key={r}>
          <span className="cite">{r}</span> <Link to={`/library/${cites[r]!.source_id}`}>{cites[r]!.filename}</Link>
          <span className="muted"> · {cites[r]!.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** The steps ChatGPT took in RecallSpring for one message (collapsed; saved steps and problems counted). */
function ToolSteps({ steps }: { steps: ToolStep[] }) {
  const saved = steps.filter((s) => s.writes && s.status === "ok").length;
  const failed = steps.filter((s) => s.status === "error").length;
  return (
    <details className="chat-steps tiny">
      <summary>
        Used RecallSpring: {plural(steps.length, "step")}
        {saved > 0 && ` · ${saved} saved`}
        {failed > 0 && ` · ${failed} not done`}
      </summary>
      <ol>
        {steps.map((s) => (
          <li key={s.call_id} className={s.status === "error" ? "is-error" : s.writes ? "is-saved" : undefined}>
            <span className="chat-step-mark" aria-hidden="true">
              {s.status === "error" ? "!" : s.writes ? "+" : "✓"}
            </span>
            {s.status === "error" ? `Not done: ${s.summary}` : s.summary}
          </li>
        ))}
      </ol>
    </details>
  );
}

const FORM_MESSAGES = {
  answer: (id: string, photos = 0) =>
    `[RecallSpring] I saved my answer to question ${id} in the form${
      photos ? ` with ${photos === 1 ? "a photo" : `${photos} photos`} of my work (attached)` : ""
    }. Please give me feedback.`,
  dont_know: (id: string) => `[RecallSpring] I answered "I don't know" to question ${id} in the form.`,
  summary: (title: string) =>
    `[RecallSpring] I saved my summary of "${title}" in the form. Please check it against the material (what is right, wrong or missing), then continue.`,
  explanation: (version: number, term: string) =>
    `[RecallSpring] I saved version ${version} of my explanation of "${term}" in the form. Please read it and give me feedback (what is correct, missing or wrong).`,
};

function explainLink(f: Extract<ToolForm, { kind: "explanation" }>): string {
  const q = new URLSearchParams({ concept: f.concept_id });
  if (f.source !== "learner") q.set("source", f.source);
  return `/explain?${q.toString()}`;
}

function summaryLink(f: Extract<ToolForm, { kind: "summary" }>): string {
  const q = new URLSearchParams({ course: f.course_id, concepts: f.concept_ids.join(","), title: f.title });
  if (f.covered) q.set("covered", f.covered);
  return `/summary?${q.toString()}`;
}

/** A form inside the chat. Only the newest turn's forms can be filled in here; older ones link to their page. */
function ChatForm({ form, live, onSend }: {
  form: ToolForm;
  live: boolean;
  onSend: ((text: string, photoIds?: string[]) => void) | null;
}) {
  // A form sent from here stays in the conversation in its saved state (question and the learner's own text), even
  // after the turn moves on; forms of earlier turns that were not sent from here become links.
  const [sent, setSent] = useState(false);
  if (form.kind === "quiz") {
    return (
      <div className="chat-form-card row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span className="small">
          <strong>Simulation{form.title ? `: ${form.title}` : ""}</strong>
          <span className="muted"> · the clock starts when you open it</span>
        </span>
        <Link className="btn small primary" to={`/simulations/${form.quiz_id}`}>
          Open the simulation
        </Link>
      </div>
    );
  }
  const send = (text: string, photoIds?: string[]) => {
    setSent(true);
    onSend?.(text, photoIds);
  };
  if (!sent && (!live || !onSend) && form.kind === "answer") {
    return (
      <div className="chat-form-card">
        <ChatSentAnswer questionId={form.question_id} />
      </div>
    );
  }
  if (!sent && (!live || !onSend)) {
    return (
      <p className="tiny muted" style={{ margin: 0 }}>
        {form.kind === "answer" ? (
          <Link to={`/answer/${form.question_id}`}>Answer form</Link>
        ) : form.kind === "explanation" ? (
          <Link to={explainLink(form)}>Explanation form “{form.term}”</Link>
        ) : (
          <Link to={summaryLink(form)}>Summary form “{form.title}”</Link>
        )}{" "}
        (shown earlier)
      </p>
    );
  }
  return (
    <div className="chat-form-card">
      {form.kind === "answer" ? (
        <ChatAnswerForm
          questionId={form.question_id}
          onSaved={(kind, photoIds) =>
            kind === "answer"
              ? send(FORM_MESSAGES.answer(form.question_id, photoIds.length), photoIds)
              : send(FORM_MESSAGES.dont_know(form.question_id))
          }
        />
      ) : form.kind === "explanation" ? (
        <ChatExplanationForm
          conceptId={form.concept_id}
          source={form.source}
          onSaved={(n, term) => send(FORM_MESSAGES.explanation(n, term))}
        />
      ) : (
        <ChatSummaryForm
          courseId={form.course_id}
          conceptIds={form.concept_ids}
          title={form.title}
          covered={form.covered}
          onSaved={() => send(FORM_MESSAGES.summary(form.title))}
        />
      )}
    </div>
  );
}

/** Forms of each turn go under that turn's reply (or under the message when there is no reply). */
function formsByMessage(messages: AiMessage[]): Map<string, { forms: ToolForm[]; live: boolean }> {
  const out = new Map<string, { forms: ToolForm[]; live: boolean }>();
  const lastUser = messages.map((m) => m.role).lastIndexOf("user");
  messages.forEach((m, i) => {
    const forms = (m.tool_calls ?? []).flatMap((s) => (s.status === "ok" && s.form ? [s.form] : []));
    if (m.role !== "user" || forms.length === 0) return;
    const next = messages[i + 1];
    out.set(next?.role === "assistant" ? next.id : m.id, { forms, live: i === lastUser });
  });
  return out;
}

/** The reply so far while ChatGPT writes it, and the RecallSpring steps it already ran. */
export interface LiveReply {
  text: string;
  steps: ToolStep[];
}

const FENCE = "```" + VISUAL_LANG;

/** A reply still being written: a visual is drawn once the reply is complete (it is checked first). */
export function whileWriting(text: string): string {
  let out = "";
  let rest = text;
  for (;;) {
    const at = rest.indexOf(FENCE);
    if (at < 0) return out + rest;
    out += rest.slice(0, at) + "\n\n*Visual: shown when the reply is complete.*\n\n";
    const close = rest.indexOf("\n```", at + FENCE.length);
    if (close < 0) return out;
    rest = rest.slice(close + 4);
  }
}

function Thread({
  conv,
  names,
  pending,
  live,
  onFormSaved,
}: {
  conv: Conversation | null;
  names: Map<string, string>;
  pending: string | null;
  live: LiveReply | null;
  onFormSaved: ((text: string, photoIds?: string[]) => void) | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true);
  const count = conv?.messages.length ?? 0;
  useEffect(() => {
    // Keep the newest message in view inside the thread (never scrolls the page itself).
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [count, pending, conv?.id]);
  const growing = (live?.text.length ?? 0) + (live?.steps.length ?? 0);
  useEffect(() => {
    // While the reply grows, follow it only if the learner has not scrolled up to read.
    if (box.current && atEnd.current) box.current.scrollTop = box.current.scrollHeight;
  }, [growing]);
  const onScroll = () => {
    const b = box.current;
    if (b) atEnd.current = b.scrollHeight - b.scrollTop - b.clientHeight < 80;
  };
  const messages = conv?.messages ?? [];
  const forms = formsByMessage(messages);
  return (
    <div ref={box} className="chat-scroll" onScroll={onScroll}>
      {!messages.length && !pending ? (
        <div className="chat-empty muted">
          <p>
            Ask ChatGPT anything. With <strong>RecallSpring</strong> on, it tutors you from your own courses: it reads your
            plan, material and notes, asks questions in RecallSpring&apos;s forms and saves feedback, which counts like any
            assistant&apos;s. Choose a course above to study it. With <strong>+</strong> you add files whose excerpts it gets
            (cited as S1, S2, …).
          </p>
        </div>
      ) : (
        <ol className="chat-thread" aria-label="Messages" aria-live="polite" aria-busy={live ? true : undefined}>
          {messages.map((m) => (
            <li key={m.id} className={m.role === "user" ? "chat-msg you" : "chat-msg ai"}>
              {m.role === "user" ? (
                <>
                  <div className="chat-bubble pre">{m.text}</div>
                  <SavedPhotos ids={(m.photo_ids ?? []).map((id) => ({ id }))} label="Images sent with this message" />
                  <div className="tiny muted" title={exactTime(m.created_at)}>
                    {shortTime(m.created_at)}
                    {m.model_requested && ` · to ${names.get(m.model_requested) ?? m.model_requested}`}
                  </div>
                  {(m.context?.length ?? 0) > 0 && <SentWith items={m.context} />}
                  {(m.tool_calls?.length ?? 0) > 0 && <ToolSteps steps={m.tool_calls} />}
                  {m.error_code && (
                    <div className="tiny chat-error">
                      Not answered: {NOT_ANSWERED[m.error_code] ?? m.error_code}. Saved; not sent again.
                    </div>
                  )}
                </>
              ) : (
                <>
                  <Markdown text={m.text} visuals={m.visuals ?? []} cites={m.citations ?? {}} source="ChatGPT" />
                  <CitedSources cites={m.citations ?? {}} />
                  <ReplyMeta m={m} names={names} />
                </>
              )}
              {forms.has(m.id) && (
                <div className="chat-forms">
                  {forms.get(m.id)!.forms.map((f, i) => (
                    <ChatForm key={`${f.kind}-${i}`} form={f} live={forms.get(m.id)!.live && !pending} onSend={onFormSaved} />
                  ))}
                </div>
              )}
            </li>
          ))}
          {pending && (
            <li className="chat-msg you">
              <div className="chat-bubble pre">{pending}</div>
              <div className="tiny muted">
                {live?.text ? "Saved" : "Saved · waiting for ChatGPT (it may read or save in RecallSpring)…"}
              </div>
              {(live?.steps.length ?? 0) > 0 && <ToolSteps steps={live!.steps} />}
            </li>
          )}
          {pending && live?.text && (
            <li className="chat-msg ai chat-live">
              <Markdown text={whileWriting(live.text)} source="ChatGPT" />
              <div className="tiny muted chat-writing">ChatGPT is writing…</div>
            </li>
          )}
        </ol>
      )}
    </div>
  );
}

function ConversationSide({
  list,
  currentId,
  onPick,
  onNew,
  canSend,
}: {
  list: ConversationList;
  currentId: string | null;
  onPick: (id: string) => void;
  onNew: () => void;
  canSend: boolean;
}) {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const restore = useMutation({
    mutationFn: (id: string) => request<ConversationList>(`/ai/chatgpt/conversations/${id}/restore`, { method: "POST" }),
    onSuccess: (l, id) => {
      qc.setQueryData(LIST_KEY, l);
      onPick(id);
    },
  });
  const q = query.trim().toLocaleLowerCase();
  const shown = q ? list.conversations.filter((c) => c.title.toLocaleLowerCase().includes(q)) : list.conversations;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {canSend && (
        <button type="button" className="btn primary" onClick={onNew}>
          New conversation
        </button>
      )}
      {list.conversations.length > 4 && (
        <label className="field">
          <span className="sr-only">Search conversations</span>
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search conversations" />
        </label>
      )}
      {list.conversations.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>No conversations yet.</p>
      ) : (
        <ul className="chat-convs" aria-label="Conversations">
          {shown.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={c.id === currentId ? "chat-item active" : "chat-item"}
                aria-current={c.id === currentId ? "true" : undefined}
                onClick={() => onPick(c.id)}
              >
                <span className="chat-item-title">{c.title}</span>
                <span className="tiny muted">
                  {dateTime(c.updated_at)} · {plural(c.replies, "reply", "replies")}
                </span>
              </button>
            </li>
          ))}
          {shown.length === 0 && <li className="small muted">No conversation matches.</li>}
        </ul>
      )}
      {list.deleted.length > 0 && (
        <details>
          <summary className="small">Recently deleted ({list.deleted.length})</summary>
          <ul className="list small" style={{ listStyle: "none", paddingLeft: 0 }}>
            {list.deleted.map((c) => (
              <li key={c.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                  {c.title}
                  <span className="tiny muted"> · deleted {dateTime(c.deleted_at!)}</span>
                </span>
                <button type="button" className="btn small ghost" onClick={() => restore.mutate(c.id)} disabled={restore.isPending}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
          <p className="tiny muted" style={{ margin: 0 }}>Restorable for 30 days.</p>
          {restore.error && <ErrorNote error={restore.error} />}
        </details>
      )}
    </div>
  );
}

function TitleBar({ conv, busy }: { conv: Conversation; busy: boolean }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conv.title);
  const [confirming, setConfirming] = useState(false);
  const rename = useMutation({
    mutationFn: (t: string) => request<Conversation>(`/ai/chatgpt/conversations/${conv.id}`, { method: "PATCH", json: { title: t } }),
    onSuccess: (c) => {
      qc.setQueryData([...LIST_KEY, c.id], c);
      void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => request<ConversationList>(`/ai/chatgpt/conversations/${conv.id}`, { method: "DELETE" }),
    onSuccess: (l) => {
      qc.setQueryData(LIST_KEY, l);
      setConfirming(false);
      navigate("/chat");
    },
  });
  function save(e: FormEvent) {
    e.preventDefault();
    if (title.trim()) rename.mutate(title.trim());
  }
  return (
    <div className="chat-head">
      {editing ? (
        <form className="row" style={{ gap: 8, flex: 1, flexWrap: "wrap" }} onSubmit={save}>
          <label className="field" style={{ flex: "1 1 200px" }}>
            <span className="sr-only">Conversation name</span>
            <input type="text" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} autoFocus />
          </label>
          <button type="submit" className="btn small primary" disabled={!title.trim() || rename.isPending}>
            Save
          </button>
          <button type="button" className="btn small ghost" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <>
          <div style={{ minWidth: 0 }}>
            <h2 className="chat-title">{conv.title}</h2>
            {conv.course && (
              <span className="tiny">
                Studying <Link to={`/courses/${conv.course.id}`}>{conv.course.title}</Link>
                {conv.totals.replies > 0 ? " · " : ""}
              </span>
            )}
            {conv.totals.replies > 0 && (
              <span className="tiny muted">
                {totalsLine(conv.totals)} ({number(conv.totals.input_tokens)} in, {number(conv.totals.output_tokens)} out)
              </span>
            )}
          </div>
          <span className="row" style={{ gap: 4 }}>
            <button
              type="button"
              className="btn small ghost"
              onClick={() => {
                setTitle(conv.title);
                setEditing(true);
              }}
              disabled={busy}
            >
              Rename
            </button>
            <button type="button" className="btn small ghost" onClick={() => setConfirming(true)} disabled={busy}>
              Delete
            </button>
          </span>
        </>
      )}
      {rename.error && <ErrorNote error={rename.error} />}
      <Confirm
        open={confirming}
        title="Delete this conversation?"
        confirmLabel="Delete"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onClose={() => setConfirming(false)}
      >
        <p>
          “{conv.title}” and its {plural(conv.messages.length, "message")} are hidden and can be restored for 30 days under
          Recently deleted. Usage already counted stays counted.
        </p>
        {remove.error && <ErrorNote error={remove.error} />}
      </Confirm>
    </div>
  );
}

const ICON = { width: 18, height: 18, viewBox: "0 0 18 18", "aria-hidden": true, focusable: false } as const;

function PlusIcon() {
  return (
    <svg {...ICON}>
      <path d="M9 3.5v11M3.5 9h11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg {...ICON}>
      <path d="M9 14.5v-11M4.5 8 9 3.5 13.5 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg {...ICON} width={16} height={16}>
      <path d="M3 14.5V9.5M7 14.5V4M11 14.5V7.5M15 14.5V11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg {...ICON} width={16} height={16}>
      <path
        d="M2.5 4h4.2c1.3 0 2.3 1 2.3 2.2v8c0-.9-.8-1.7-1.8-1.7H2.5zM15.5 4h-4.2C10 4 9 5 9 6.2v8c0-.9.8-1.7 1.8-1.7h4.7z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function ClipIcon() {
  return (
    <svg {...ICON}>
      <path
        d="M14.5 8.5l-5.6 5.6a3.4 3.4 0 0 1-4.8-4.8l6-6a2.3 2.3 0 0 1 3.2 3.2l-6 6a1.1 1.1 0 0 1-1.6-1.6l5.5-5.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg {...ICON} width={14} height={14}>
      <path d="M5 2.5h5l3.5 3.5v9.5H5z M10 2.5V6h3.5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

/** The message box: grows with the text (up to ~40 % of the window), tools in one row underneath. */
function Composer({
  canSend,
  models,
  model,
  onModel,
  busy,
  onSend,
  placeholder,
  visuals,
  onVisuals,
  tools,
  onTools,
  material,
  onMaterial,
  onAttach,
  photoCourse,
}: {
  canSend: boolean;
  models: Model[];
  model: string;
  onModel: (slug: string) => void;
  busy: boolean;
  onSend: (text: string, photoIds: string[]) => Promise<unknown>;
  placeholder: string;
  visuals: boolean;
  onVisuals: (on: boolean) => void;
  tools: boolean;
  onTools: (on: boolean) => void;
  material: { filename: string; reading?: boolean }[];
  onMaterial: () => void;
  onAttach: () => void;
  /** The course pasted or dropped images are saved in (null: a planning chat, images need a course). */
  photoCourse: string | null;
}) {
  const [text, setText] = useState("");
  const photos = usePhotos(photoCourse, CHAT_FOLDER);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.4))}px`;
  }, [text]);
  async function submit() {
    const value = text.trim() || (photos.ids.length ? "Please look at the attached image." : "");
    if (!value || !model || busy || photos.saving) return;
    try {
      await onSend(value, photos.ids);
      setText("");
      photos.clear();
    } catch {
      /* the message stays in the box; the error is shown above */
    }
  }
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }
  const names = material.map((f) => f.filename);
  // Files RecallSpring is still reading (reported for an existing conversation).
  const reading = material.filter((f) => f.reading).map((f) => f.filename);
  const ready = canSend && (!!text.trim() || photos.ids.length > 0) && !photos.saving && !!model && !busy;
  return (
    <div className="composer-wrap">
      <form
        className={`chat-composer${canSend ? "" : " is-off"}`}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget) box.current?.focus();
        }}
        {...photos.dropProps}
      >
        {reading.length > 0 && (
          <div className="tiny muted" role="status">
            RecallSpring is still reading {reading.join(", ")}; ChatGPT can use {reading.length === 1 ? "it" : "them"} in a moment.
          </div>
        )}
        {names.length > 0 && (
          <div className="composer-files" aria-label="Material ChatGPT may use">
            {names.slice(0, 3).map((n) => (
              <span key={n} className="composer-file" title={reading.includes(n) ? `${n} (RecallSpring is still reading it)` : n}>
                <FileIcon />
                <span className="composer-file-name">{n}</span>
                {reading.includes(n) && <span className="tiny muted">reading…</span>}
              </span>
            ))}
            {names.length > 3 && (
              <button type="button" className="composer-file more" onClick={onMaterial}>
                +{names.length - 3} more
              </button>
            )}
          </div>
        )}
        <PhotoStrip photos={photos.photos} onRemove={photos.remove} />
        {photos.notice && (
          <div className="tiny muted" role="status">
            {photos.notice}
          </div>
        )}
        <label className="composer-input">
          <span className="sr-only">Message to ChatGPT</span>
          <textarea
            ref={box}
            rows={1}
            value={text}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            onPaste={photos.onPaste}
            placeholder={placeholder}
            disabled={!canSend}
            aria-describedby="composer-hint"
          />
        </label>
        <div className="composer-bar">
          <button
            type="button"
            className="composer-icon"
            onClick={onMaterial}
            aria-haspopup="dialog"
            aria-label={names.length ? `Material: ${plural(names.length, "file")} chosen` : "Choose material"}
            title={names.join("\n") || "Choose files ChatGPT may use"}
          >
            <PlusIcon />
            {names.length > 0 && <span className="composer-count">{names.length}</span>}
          </button>
          <button
            type="button"
            className="composer-icon"
            onClick={onAttach}
            aria-haspopup="dialog"
            aria-label="Upload files"
            title="Upload files from this computer into your Library and this conversation"
          >
            <ClipIcon />
          </button>
          <button
            type="button"
            className="composer-pill"
            aria-pressed={tools}
            onClick={() => onTools(!tools)}
            title="Lets ChatGPT read your courses, material, notes and plan, and save questions and feedback in RecallSpring. It cannot delete anything or change settings."
          >
            <BookIcon />
            RecallSpring
          </button>
          <button
            type="button"
            className="composer-pill"
            aria-pressed={visuals}
            onClick={() => onVisuals(!visuals)}
            title="Lets ChatGPT add diagrams, charts or a slider, drawn by RecallSpring from checked data. Nothing it writes is run."
          >
            <ChartIcon />
            Visuals
          </button>
          <span className="composer-end">
            {models.length > 0 ? (
              <select value={model} onChange={(e) => onModel(e.target.value)} aria-label="Model" className="composer-model">
                {models.map((m) => (
                  <option key={m.slug} value={m.slug}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="tiny muted">{canSend ? "Loading models…" : ""}</span>
            )}
            <button type="submit" className={`composer-send${busy ? " is-busy" : ""}`} disabled={!ready} aria-label={busy ? "Waiting for the reply" : "Send message"}>
              {busy ? <span className="composer-spinner" aria-hidden="true" /> : <SendIcon />}
            </button>
          </span>
        </div>
      </form>
      <p id="composer-hint" className="composer-hint">
        Enter sends · Shift+Enter new line
      </p>
    </div>
  );
}

export function ChatPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const status = useChatGptStatus();
  const s = status.data;
  const canSend = !!s?.connected && !!s.plan_usage;
  const list = useQuery({ queryKey: LIST_KEY, queryFn: () => get<ConversationList>("/ai/chatgpt/conversations") });
  const models = useQuery({ queryKey: [...STATUS_KEY, "models"], queryFn: () => get<Model[]>("/ai/chatgpt/models"), enabled: canSend });
  const isNew = conversationId === "new";
  const currentId = isNew ? null : (conversationId ?? list.data?.conversations[0]?.id ?? null);
  const conv = useQuery({
    queryKey: [...LIST_KEY, currentId],
    queryFn: () => get<Conversation>(`/ai/chatgpt/conversations/${currentId}`),
    enabled: !!currentId,
    // While an attached file is still being read, check again so the composer shows when it is ready.
    refetchInterval: (q) =>
      q.state.data?.material.some((f) => f.reading) && q.state.dataUpdateCount < 100 ? 3000 : false,
  });
  const [model, setModel] = useState(() => remembered());
  const [visuals, setVisuals] = useState(() => remembered(VISUALS_STORE) !== "off");
  const [tools, setTools] = useState(() => remembered(TOOLS_STORE) !== "off");
  // Study mode for a new conversation: the course ChatGPT starts from ("" = a planning conversation).
  const [studyCourse, setStudyCourse] = useState("");
  const courses = useQuery({ queryKey: keys.courses, queryFn: () => get<Course[]>("/courses"), enabled: tools && !currentId });
  const [sideOpen, setSideOpen] = useState(false);
  // Full page: no menu and no list beside the thread; the conversations open as a drawer (owner 2026-11-22).
  const [full, setFull] = useState(() => remembered(FULL_STORE) === "on");
  function toggleFull() {
    setFull(!full);
    setSideOpen(false);
    remember(full ? "off" : "on", FULL_STORE);
  }
  useEffect(() => {
    if (!full || !sideOpen) return;
    const close = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setSideOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [full, sideOpen]);
  const [picking, setPicking] = useState(false);
  const [attaching, setAttaching] = useState(false);
  // Files chosen before a new conversation's first message (an existing one keeps them on the server).
  const [draft, setDraft] = useState<{ id: string; filename: string }[]>([]);
  const available = models.data ?? [];
  const names = new Map(available.map((m) => [m.slug, m.display_name]));
  const chosen = available.some((m) => m.slug === model) ? model : (available[0]?.slug ?? "");
  const current = currentId ? (conv.data ?? null) : null;
  const material = current ? current.material : currentId ? [] : draft;

  const [live, setLive] = useState<LiveReply | null>(null);
  const send = useMutation({
    mutationFn: (input: string | { text: string; photoIds: string[] }) => {
      const { text, photoIds } = typeof input === "string" ? { text: input, photoIds: [] } : input;
      setLive({ text: "", steps: [] });
      const body = {
        conversation_id: currentId,
        model: chosen,
        message: text,
        photo_ids: photoIds,
        visuals,
        recallspring: tools,
        ...(currentId ? {} : { source_ids: draft.map((f) => f.id), course_id: tools && studyCourse ? studyCourse : null }),
      };
      // The reply is shown as it arrives; the saved conversation replaces it when it is complete.
      return streamRequest<Conversation>("/ai/chatgpt/messages/stream", body, (e) => {
        if (e.type === "text") setLive((l) => ({ text: (l?.text ?? "") + e.text, steps: l?.steps ?? [] }));
        else if (e.type === "step") setLive((l) => ({ text: l?.text ?? "", steps: [...(l?.steps ?? []), e.step as ToolStep] }));
      });
    },
    onSettled: () => setLive(null),
    onSuccess: (c) => {
      qc.setQueryData([...LIST_KEY, c.id], c);
      void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
      if (tools) void qc.invalidateQueries({ queryKey: keys.dashboard });
      if (c.id !== currentId) {
        setDraft([]);
        setStudyCourse("");
        navigate(`/chat/${c.id}`, { replace: isNew });
      }
    },
    onError: (err) => {
      const id = err instanceof ApiError ? err.details?.conversation_id : undefined;
      if (typeof id === "string") {
        void qc.invalidateQueries({ queryKey: [...LIST_KEY, id] });
        void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
        if (id !== currentId) {
          setDraft([]);
          navigate(`/chat/${id}`, { replace: isNew });
        }
      }
    },
  });
  const saveMaterial = useMutation({
    mutationFn: (ids: string[]) =>
      request<Conversation>(`/ai/chatgpt/conversations/${currentId}/material`, { method: "PUT", json: { source_ids: ids } }),
    onSuccess: (c) => {
      qc.setQueryData([...LIST_KEY, c.id], c);
      setPicking(false);
    },
  });

  /** Files uploaded from the composer join the conversation's material (up to MAX_FILES). */
  function attach(files: { id: string; filename: string }[]) {
    if (currentId) {
      const ids = [...new Set([...material.map((f) => f.id), ...files.map((f) => f.id)])].slice(0, MAX_FILES);
      saveMaterial.mutate(ids);
    } else {
      const seen = new Set(draft.map((f) => f.id));
      setDraft([...draft, ...files.filter((f) => !seen.has(f.id)).map((f) => ({ id: f.id, filename: f.filename }))].slice(0, MAX_FILES));
    }
  }

  function pick(id: string) {
    setSideOpen(false);
    send.reset();
    navigate(`/chat/${id}`);
  }

  const usage = list.data?.usage;

  return (
    <div className={full ? "chat-page full" : "chat-page"}>
      <header className="chat-top">
        <button
          type="button"
          className="btn ghost small chat-side-toggle"
          aria-expanded={sideOpen}
          aria-controls="chat-side"
          onClick={() => setSideOpen(!sideOpen)}
        >
          {sideOpen ? "Hide conversations" : `Conversations (${list.data?.conversations.length ?? 0})`}
        </button>
        <div style={{ minWidth: 0 }} className="chat-top-text">
          <h1>Chat</h1>
          <p className="tiny muted" style={{ margin: 0 }}>
            ChatGPT on your own plan{s?.connected && s.email ? ` (${s.email})` : ""}. Conversations are saved here ·{" "}
            <Link to="/settings#chatgpt">Sign-in and privacy</Link>
          </p>
        </div>
        {usage && (
          <span className="tiny muted" title="As ChatGPT reports it. Your plan's remaining limit: chatgpt.com/settings/usage">
            Last 24 h: {totalsLine(usage.last_24_hours)} · 30 days: {totalsLine(usage.last_30_days)}
          </span>
        )}
        <button
          type="button"
          className="btn ghost small chat-full-toggle"
          aria-pressed={full}
          title={full ? "Show the menu and the conversation list again" : "Use the whole window for the conversation"}
          onClick={toggleFull}
        >
          {full ? "Exit full page" : "Full page"}
        </button>
      </header>

      {status.error && <ErrorNote error={status.error} />}
      {s && !canSend && (
        <div className="notice small chat-signin">
          {s.connected
            ? "This sign-in does not allow RecallSpring to use your ChatGPT plan. Sign in again and allow it."
            : "Sign in with ChatGPT to send messages. Your conversations stay readable."}{" "}
          <ChatGptSignIn status={s} compact />
        </div>
      )}

      <div className="chat-layout">
        {full && sideOpen && (
          <button type="button" className="chat-scrim" aria-label="Close the conversation list" onClick={() => setSideOpen(false)} />
        )}
        <aside id="chat-side" className={sideOpen ? "chat-side open" : "chat-side"} aria-label="Conversation list">
          {list.data ? (
            <ConversationSide
              list={list.data}
              currentId={currentId}
              onPick={pick}
              onNew={() => {
                setSideOpen(false);
                setDraft([]);
                send.reset();
                navigate("/chat/new");
              }}
              canSend={canSend}
            />
          ) : list.error ? (
            <ErrorNote error={list.error} />
          ) : (
            <Loading lines={3} />
          )}
        </aside>

        <section className="chat-main" aria-label="Conversation">
          {current ? (
            <TitleBar key={current.id} conv={current} busy={send.isPending} />
          ) : (
            <div className="chat-head">
              <h2 className="chat-title">New conversation</h2>
              {tools && (courses.data?.length ?? 0) > 0 && (
                <label className="chat-study small">
                  Study
                  <select value={studyCourse} onChange={(e) => setStudyCourse(e.target.value)}>
                    <option value="">Planning (all courses)</option>
                    {courses.data!.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          )}
          {currentId && conv.isPending ? (
            <div className="chat-scroll">
              <Loading lines={4} />
            </div>
          ) : conv.error && currentId ? (
            <div className="chat-scroll">
              <ErrorNote error={conv.error} />
            </div>
          ) : (
            <Thread
              conv={current}
              names={names}
              pending={send.isPending && send.variables !== undefined ? (typeof send.variables === "string" ? send.variables : send.variables.text) : null}
              live={send.isPending ? live : null}
              onFormSaved={canSend && chosen ? (text, photoIds) => send.mutate({ text, photoIds: photoIds ?? [] }) : null}
            />
          )}
          <div className="chat-foot">
            {current?.older_turns_not_sent && (
              <div className="notice small">Long conversation: only the newest messages are sent to ChatGPT. Start a new one for a new topic.</div>
            )}
            {send.error && <ErrorNote error={send.error} />}
            {models.error && <ErrorNote error={models.error} />}
            {!picking && saveMaterial.error && <ErrorNote error={saveMaterial.error} />}
            <Composer
              canSend={canSend}
              models={available}
              model={chosen}
              onModel={(slug) => {
                setModel(slug);
                remember(slug);
              }}
              busy={send.isPending}
              onSend={(text, photoIds) => send.mutateAsync({ text, photoIds })}
              photoCourse={current?.course?.id ?? (studyCourse || null)}
              visuals={visuals}
              onVisuals={(on) => {
                setVisuals(on);
                remember(on ? "on" : "off", VISUALS_STORE);
              }}
              tools={tools}
              onTools={(on) => {
                setTools(on);
                remember(on ? "on" : "off", TOOLS_STORE);
              }}
              material={material}
              onMaterial={() => {
                saveMaterial.reset();
                setPicking(true);
              }}
              onAttach={() => {
                saveMaterial.reset();
                setAttaching(true);
              }}
              placeholder={
                !canSend
                  ? "Sign in with ChatGPT to write"
                  : current
                    ? "Write a message"
                    : studyCourse && tools
                      ? "Write e.g. “Start studying”"
                      : "Start a new conversation"
              }
            />
          </div>
        </section>
      </div>
      <AttachDialog
        open={attaching}
        courseId={current ? (current.course?.id ?? null) : tools && studyCourse ? studyCourse : null}
        onClose={() => setAttaching(false)}
        onAttached={attach}
      />
      <MaterialPicker
        open={picking}
        chosen={material.map((f) => f.id)}
        busy={saveMaterial.isPending}
        error={saveMaterial.error}
        onClose={() => setPicking(false)}
        onSave={(ids, files) => {
          if (currentId) saveMaterial.mutate(ids);
          else {
            setDraft(files.map((f) => ({ id: f.id, filename: f.filename })));
            setPicking(false);
          }
        }}
      />
    </div>
  );
}
