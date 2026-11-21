import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, get, request } from "../api";
import { ChatGptSignIn, STATUS_KEY, useChatGptStatus } from "../components/ChatGpt";
import { Markdown } from "../components/Markdown";
import { Confirm, ErrorNote, Loading, PageHead } from "../components/ui";
import { dateTime, plural } from "../format";

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
  totals: Totals;
  older_turns_not_sent: boolean;
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

function remembered(): string {
  try {
    return localStorage.getItem(MODEL_STORE) ?? "";
  } catch {
    return "";
  }
}

function remember(slug: string): void {
  try {
    localStorage.setItem(MODEL_STORE, slug);
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

function Thread({ conv, names, pending }: { conv: Conversation | null; names: Map<string, string>; pending: string | null }) {
  const box = useRef<HTMLOListElement>(null);
  const count = conv?.messages.length ?? 0;
  useEffect(() => {
    // Keep the newest message in view inside the thread (never scrolls the page itself).
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [count, pending, conv?.id]);
  const messages = conv?.messages ?? [];
  if (!messages.length && !pending) {
    return (
      <div className="chat-empty muted">
        <p>Ask ChatGPT anything. It can't see your courses here; Claude stays your tutor.</p>
      </div>
    );
  }
  return (
    <ol ref={box} className="chat-thread" aria-label="Messages" aria-live="polite">
      {messages.map((m) => (
        <li key={m.id} className={m.role === "user" ? "chat-msg you" : "chat-msg ai"}>
          {m.role === "user" ? (
            <>
              <div className="chat-bubble pre">{m.text}</div>
              <div className="tiny muted" title={exactTime(m.created_at)}>
                {shortTime(m.created_at)}
                {m.model_requested && ` · to ${names.get(m.model_requested) ?? m.model_requested}`}
              </div>
              {m.error_code && (
                <div className="tiny chat-error">
                  Not answered: {NOT_ANSWERED[m.error_code] ?? m.error_code}. Saved; not sent again.
                </div>
              )}
            </>
          ) : (
            <>
              <Markdown text={m.text} />
              <ReplyMeta m={m} names={names} />
            </>
          )}
        </li>
      ))}
      {pending && (
        <li className="chat-msg you">
          <div className="chat-bubble pre">{pending}</div>
          <div className="tiny muted">Saved · waiting for ChatGPT…</div>
        </li>
      )}
    </ol>
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
        <ul className="chat-list" aria-label="Conversations">
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
          <h2 className="chat-title">{conv.title}</h2>
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

function Composer({
  canSend,
  models,
  model,
  onModel,
  busy,
  onSend,
  placeholder,
}: {
  canSend: boolean;
  models: Model[];
  model: string;
  onModel: (slug: string) => void;
  busy: boolean;
  onSend: (text: string) => Promise<unknown>;
  placeholder: string;
}) {
  const [text, setText] = useState("");
  async function submit() {
    const value = text.trim();
    if (!value || !model || busy) return;
    try {
      await onSend(value);
      setText("");
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
  return (
    <form
      className="chat-composer"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className="field">
        <span className="sr-only">Message to ChatGPT</span>
        <textarea rows={3} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} placeholder={placeholder} disabled={!canSend} />
      </label>
      <div className="row" style={{ gap: 8, justifyContent: "space-between", flexWrap: "wrap" }}>
        {models.length > 0 ? (
          <label className="row small" style={{ gap: 6 }}>
            <span className="muted">Model</span>
            <select value={model} onChange={(e) => onModel(e.target.value)} aria-label="Model">
              {models.map((m) => (
                <option key={m.slug} value={m.slug}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="tiny muted">{canSend ? "Loading models…" : ""}</span>
        )}
        <span className="row" style={{ gap: 8 }}>
          <span className="tiny muted hide-narrow">Enter sends · Shift+Enter new line</span>
          <button type="submit" className="btn primary" disabled={!canSend || !text.trim() || !model || busy}>
            {busy ? "Waiting…" : "Send"}
          </button>
        </span>
      </div>
    </form>
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
  });
  const [model, setModel] = useState(remembered);
  const [sideOpen, setSideOpen] = useState(false);
  const available = models.data ?? [];
  const names = new Map(available.map((m) => [m.slug, m.display_name]));
  const chosen = available.some((m) => m.slug === model) ? model : (available[0]?.slug ?? "");

  const send = useMutation({
    mutationFn: (text: string) =>
      request<Conversation>("/ai/chatgpt/messages", { json: { conversation_id: currentId, model: chosen, message: text } }),
    onSuccess: (c) => {
      qc.setQueryData([...LIST_KEY, c.id], c);
      void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
      if (c.id !== currentId) navigate(`/chat/${c.id}`, { replace: isNew });
    },
    onError: (err) => {
      const id = err instanceof ApiError ? err.details?.conversation_id : undefined;
      if (typeof id === "string") {
        void qc.invalidateQueries({ queryKey: [...LIST_KEY, id] });
        void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
        if (id !== currentId) navigate(`/chat/${id}`, { replace: isNew });
      }
    },
  });

  function pick(id: string) {
    setSideOpen(false);
    send.reset();
    navigate(`/chat/${id}`);
  }

  const usage = list.data?.usage;
  const current = currentId ? (conv.data ?? null) : null;

  return (
    <div className="page chat-page">
      <PageHead
        title="Chat"
        sub={
          s?.connected
            ? `ChatGPT on your own plan${s.email ? ` (${s.email})` : ""}. Saved here; Claude stays your tutor.`
            : "ChatGPT on your own plan. Your conversations are saved here."
        }
      >
        {usage && (
          <span className="small muted" title="As ChatGPT reports it. Your plan's remaining limit: chatgpt.com/settings/usage">
            Last 24 h: {totalsLine(usage.last_24_hours)} · 30 days: {totalsLine(usage.last_30_days)}
          </span>
        )}
      </PageHead>

      {status.error && <ErrorNote error={status.error} />}
      {s && !canSend && (
        <div className="notice small chat-signin">
          {s.connected
            ? "This sign-in does not allow RecallSpring to use your ChatGPT plan. Sign in again and allow it."
            : "Sign in with ChatGPT to send messages. Your conversations stay readable."}{" "}
          <ChatGptSignIn status={s} compact />
        </div>
      )}

      <button type="button" className="btn ghost chat-side-toggle" aria-expanded={sideOpen} onClick={() => setSideOpen(!sideOpen)}>
        {sideOpen ? "Hide conversations" : `Conversations (${list.data?.conversations.length ?? 0})`}
      </button>

      <div className="chat-layout">
        <aside className={sideOpen ? "chat-side open" : "chat-side"} aria-label="Conversation list">
          {list.data ? (
            <ConversationSide
              list={list.data}
              currentId={currentId}
              onPick={pick}
              onNew={() => {
                setSideOpen(false);
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

        <section className="card chat-main">
          {current && <TitleBar key={current.id} conv={current} busy={send.isPending} />}
          {currentId && conv.isPending ? (
            <Loading lines={4} />
          ) : conv.error && currentId ? (
            <ErrorNote error={conv.error} />
          ) : (
            <Thread conv={current} names={names} pending={send.isPending ? (send.variables ?? null) : null} />
          )}
          {current?.older_turns_not_sent && (
            <div className="notice small">Long conversation: only the newest messages are sent to ChatGPT. Start a new one for a new topic.</div>
          )}
          {current && current.totals.replies > 0 && (
            <p className="tiny muted" style={{ margin: 0 }}>
              This conversation: {totalsLine(current.totals)} ({number(current.totals.input_tokens)} in,{" "}
              {number(current.totals.output_tokens)} out).
            </p>
          )}
          {send.error && <ErrorNote error={send.error} />}
          {models.error && <ErrorNote error={models.error} />}
          <Composer
            canSend={canSend}
            models={available}
            model={chosen}
            onModel={(slug) => {
              setModel(slug);
              remember(slug);
            }}
            busy={send.isPending}
            onSend={(text) => send.mutateAsync(text)}
            placeholder={canSend ? (current ? "Write a message" : "Start a new conversation") : "Sign in with ChatGPT to write"}
          />
        </section>
      </div>
      <p className="tiny muted" style={{ margin: 0 }}>
        Sign-in and privacy: <Link to="/settings#chatgpt">Settings → ChatGPT</Link>.
      </p>
    </div>
  );
}
