import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { ApiError, get, request } from "../api";
import { dateTime, plural } from "../format";
import { Async, Confirm, ErrorNote } from "./ui";

interface ChatGptStatus {
  connected: boolean;
  registered: boolean;
  unreadable: boolean;
  email: string | null;
  name: string | null;
  scopes: string[];
  plan_usage: boolean;
  signed_in_at: number | null;
  unavailable_reason: "disabled" | "not_local" | null;
}

const STATUS_KEY = ["ai", "chatgpt"] as const;

const OUTCOME: Record<string, { text: string; warn?: boolean }> = {
  connected: { text: "Signed in with ChatGPT. Your saved conversations are below." },
  no_plan_usage: {
    text: "Signed in, but using your ChatGPT plan was not allowed. Sign in again and allow it to send messages.",
    warn: true,
  },
  declined: { text: "Sign-in was cancelled. Nothing was saved.", warn: true },
  expired: { text: "That sign-in had expired or was already used. Start it again.", warn: true },
  error: { text: "The sign-in did not work. Try again; if it keeps failing, check History for details.", warn: true },
};

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

function tokenLine(u: Usage): string {
  const parts: string[] = [];
  if (u.input_tokens !== undefined) {
    parts.push(`${number(u.input_tokens)} in${u.cached_tokens ? ` (${number(u.cached_tokens)} cached)` : ""}`);
  }
  if (u.output_tokens !== undefined) {
    parts.push(`${number(u.output_tokens)} out${u.reasoning_tokens ? ` (${number(u.reasoning_tokens)} reasoning)` : ""}`);
  }
  const total = u.total_tokens !== undefined ? `${number(u.total_tokens)} tokens` : "tokens";
  return parts.length ? `${total}: ${parts.join(", ")}` : total;
}

function totalsLine(t: Totals): string {
  return t.replies === 0
    ? "no replies"
    : `${plural(t.replies, "reply", "replies")}, ${number(t.total_tokens)} tokens (${number(t.input_tokens)} in, ${number(t.output_tokens)} out)`;
}

function ReplyDetails({ m, names }: { m: AiMessage; names: Map<string, string> }) {
  const requested = m.model_requested ?? "";
  const name = names.get(requested) ?? requested;
  return (
    <div className="tiny muted" style={{ marginTop: 4 }}>
      <div>
        {[
          m.model ?? name,
          exactTime(m.completed_at ?? m.created_at),
          m.duration_ms !== null ? `${(m.duration_ms / 1000).toFixed(1)} s` : null,
          m.usage ? tokenLine(m.usage) : "tokens not reported",
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
      <details>
        <summary>More</summary>
        <dl className="kv">
          <dt>Model chosen</dt>
          <dd>{name !== requested ? `${name} (${requested})` : requested}</dd>
          <dt>Answered by</dt>
          <dd>{m.model ?? "not reported"}</dd>
          {m.account && (
            <>
              <dt>ChatGPT account</dt>
              <dd>{m.account}</dd>
            </>
          )}
          {m.response_id && (
            <>
              <dt>Response ID</dt>
              <dd>{m.response_id}</dd>
            </>
          )}
        </dl>
      </details>
    </div>
  );
}

function MessageList({ conv, names, pending }: { conv: Conversation | null; names: Map<string, string>; pending: string | null }) {
  const messages = conv?.messages ?? [];
  if (!messages.length && !pending) return null;
  return (
    <ol className="list small" aria-label="Conversation" style={{ listStyle: "none", paddingLeft: 0 }}>
      {messages.map((m) => (
        <li key={m.id}>
          {m.role === "user" ? (
            <>
              <div className="tiny muted">
                You · {exactTime(m.created_at)}
                {m.model_requested && ` · to ${names.get(m.model_requested) ?? m.model_requested}`}
              </div>
              <div className="pre">{m.text}</div>
              {m.error_code && (
                <div className="tiny" style={{ color: "var(--bad, #b42318)" }}>
                  Not answered: {NOT_ANSWERED[m.error_code] ?? m.error_code}. Saved; not sent again.
                </div>
              )}
            </>
          ) : (
            <>
              <div className="tiny muted">ChatGPT · {names.get(m.model_requested ?? "") ?? m.model_requested ?? "model not reported"}</div>
              <div className="pre">{m.text}</div>
              <ReplyDetails m={m} names={names} />
            </>
          )}
        </li>
      ))}
      {pending && (
        <li>
          <div className="tiny muted">You · now</div>
          <div className="pre">{pending}</div>
          <div className="tiny muted">Saved. Waiting for ChatGPT…</div>
        </li>
      )}
    </ol>
  );
}

/** Saved conversations with ChatGPT. Readable while signed out; sending needs a sign-in that allows plan usage. */
function Conversations({ canSend }: { canSend: boolean }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: LIST_KEY, queryFn: () => get<ConversationList>("/ai/chatgpt/conversations") });
  const models = useQuery({
    queryKey: [...STATUS_KEY, "models"],
    queryFn: () => get<Model[]>("/ai/chatgpt/models"),
    enabled: canSend,
  });
  // undefined = the newest conversation, null = a new one
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const currentId = picked === undefined ? (list.data?.conversations[0]?.id ?? null) : picked;
  const conv = useQuery({
    queryKey: [...LIST_KEY, currentId],
    queryFn: () => get<Conversation>(`/ai/chatgpt/conversations/${currentId}`),
    enabled: !!currentId,
  });
  const [model, setModel] = useState("");
  const [message, setMessage] = useState("");
  const [confirming, setConfirming] = useState(false);
  const names = new Map((models.data ?? []).map((m) => [m.slug, m.display_name]));
  const lastModel = [...(conv.data?.messages ?? [])].reverse().find((m) => m.model_requested)?.model_requested;
  const available = models.data ?? [];
  const chosen =
    model || (lastModel && available.some((m) => m.slug === lastModel) ? lastModel : available[0]?.slug) || "";

  const send = useMutation({
    mutationFn: (text: string) =>
      request<Conversation>("/ai/chatgpt/messages", { json: { conversation_id: currentId, model: chosen, message: text } }),
    onSuccess: (c) => {
      qc.setQueryData([...LIST_KEY, c.id], c);
      setPicked(c.id);
      setMessage("");
      void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
    },
    onError: (err) => {
      const id = err instanceof ApiError ? err.details?.conversation_id : undefined;
      if (typeof id === "string") {
        setPicked(id);
        void qc.invalidateQueries({ queryKey: [...LIST_KEY, id] });
        void qc.invalidateQueries({ queryKey: LIST_KEY, exact: true });
      }
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => request<ConversationList>(`/ai/chatgpt/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (l) => {
      qc.setQueryData(LIST_KEY, l);
      setPicked(undefined);
      setConfirming(false);
    },
  });
  const restore = useMutation({
    mutationFn: (id: string) => request<ConversationList>(`/ai/chatgpt/conversations/${id}/restore`, { method: "POST" }),
    onSuccess: (l, id) => {
      qc.setQueryData(LIST_KEY, l);
      setPicked(id);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (message.trim() && chosen && !send.isPending) send.mutate(message.trim());
  }

  const data = list.data;
  if (!data) return list.error ? <ErrorNote error={list.error} /> : null;
  if (!canSend && data.conversations.length === 0 && data.deleted.length === 0) return null;
  const current = currentId ? conv.data ?? null : null;

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
        {data.conversations.length > 0 && (
          <label className="field" style={{ flex: "1 1 220px" }}>
            Conversation
            <select value={currentId ?? ""} onChange={(e) => setPicked(e.target.value || null)}>
              {canSend && <option value="">New conversation</option>}
              {data.conversations.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} · {dateTime(c.updated_at)}
                </option>
              ))}
            </select>
          </label>
        )}
        {canSend && currentId && (
          <button type="button" className="btn small ghost" onClick={() => setPicked(null)} disabled={send.isPending}>
            New conversation
          </button>
        )}
        {currentId && (
          <button type="button" className="btn small ghost" onClick={() => setConfirming(true)} disabled={send.isPending}>
            Delete
          </button>
        )}
      </div>

      {canSend && (
        <Async q={models} lines={1}>
          {(list) =>
            list.length === 0 ? (
              <p className="small muted">ChatGPT lists no models for this account.</p>
            ) : (
              <label className="field">
                Model
                <select value={chosen} onChange={(e) => setModel(e.target.value)}>
                  {list.map((m) => (
                    <option key={m.slug} value={m.slug}>
                      {m.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )
          }
        </Async>
      )}

      {conv.error && <ErrorNote error={conv.error} />}
      <MessageList conv={current} names={names} pending={send.isPending ? (send.variables ?? null) : null} />
      {current && current.totals.replies > 0 && (
        <p className="tiny muted" style={{ margin: 0 }}>
          This conversation: {totalsLine(current.totals)}.
        </p>
      )}
      {current?.older_turns_not_sent && (
        <div className="notice small">
          This conversation is long: only the newest messages are sent to ChatGPT. Start a new conversation for a new topic.
        </div>
      )}

      {canSend ? (
        <form className="stack" style={{ gap: 8 }} onSubmit={submit}>
          <label className="field">
            <span className="sr-only">Message to ChatGPT</span>
            <textarea
              rows={2}
              value={message}
              maxLength={4000}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={currentId ? "Write a message" : "Start a new conversation"}
            />
          </label>
          <div className="row" style={{ gap: 8, justifyContent: "space-between", flexWrap: "wrap" }}>
            <span className="tiny muted">Saved in RecallSpring. ChatGPT can't see your courses here; Claude stays your tutor.</span>
            <button type="submit" className="btn small primary" disabled={!message.trim() || !chosen || send.isPending}>
              {send.isPending ? "Waiting for ChatGPT…" : "Send"}
            </button>
          </div>
        </form>
      ) : (
        <p className="tiny muted" style={{ margin: 0 }}>
          Your conversations are kept. Sign in with ChatGPT to continue them.
        </p>
      )}
      {send.error && <ErrorNote error={send.error} />}

      <p className="tiny muted" style={{ margin: 0 }}>
        Used from RecallSpring: last 24 hours {totalsLine(data.usage.last_24_hours)}; last 30 days{" "}
        {totalsLine(data.usage.last_30_days)}. Token counts are as ChatGPT reports them; your plan's remaining limit is
        shown at chatgpt.com/settings/usage.
      </p>

      {data.deleted.length > 0 && (
        <details>
          <summary className="small">Recently deleted ({data.deleted.length})</summary>
          <ul className="list small" style={{ listStyle: "none", paddingLeft: 0 }}>
            {data.deleted.map((c) => (
              <li key={c.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                <span>
                  {c.title} <span className="tiny muted">· deleted {dateTime(c.deleted_at!)}</span>
                </span>
                <button type="button" className="btn small ghost" onClick={() => restore.mutate(c.id)} disabled={restore.isPending}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
          <p className="tiny muted" style={{ margin: 0 }}>Deleted conversations can be restored for 30 days.</p>
          {restore.error && <ErrorNote error={restore.error} />}
        </details>
      )}

      <Confirm
        open={confirming}
        title="Delete this conversation?"
        confirmLabel="Delete"
        danger
        busy={remove.isPending}
        onConfirm={() => currentId && remove.mutate(currentId)}
        onClose={() => setConfirming(false)}
      >
        <p>
          “{current?.title ?? "This conversation"}” and its {plural(current?.messages.length ?? 0, "message")} are hidden
          and can be restored for 30 days under Recently deleted. Usage already counted stays counted.
        </p>
        {remove.error && <ErrorNote error={remove.error} />}
      </Confirm>
    </div>
  );
}

/** Sign in with ChatGPT (preview): the learner's own ChatGPT plan, on this computer only, never in the background. */
export function ChatGptPanel() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const outcome = OUTCOME[params.get("chatgpt") ?? ""];
  const status = useQuery({ queryKey: STATUS_KEY, queryFn: () => get<ChatGptStatus>("/ai/chatgpt") });
  const [confirming, setConfirming] = useState(false);
  const connect = useMutation({
    mutationFn: () => request<{ authorize_url: string }>("/ai/chatgpt/connect", { method: "POST" }),
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
  const disconnect = useMutation({
    mutationFn: () => request<ChatGptStatus & { revoked: boolean }>("/ai/chatgpt/disconnect", { method: "POST" }),
    onSuccess: (s) => {
      qc.setQueryData(STATUS_KEY, s);
      setConfirming(false);
    },
  });

  return (
    <div className="stack" id="chatgpt">
      {outcome && (
        <div className={outcome.warn ? "notice warn small" : "notice small"} role="status">
          {outcome.text}{" "}
          <button type="button" className="linklike" onClick={() => setParams({})}>
            Dismiss
          </button>
        </div>
      )}
      <Async q={status} lines={2}>
        {(s) => (
          <div className="stack">
            {s.connected ? (
              <>
                <dl className="kv small">
                  <dt>Account</dt>
                  <dd>{s.email ?? s.name ?? "Signed in"}</dd>
                  <dt>Plan usage</dt>
                  <dd>{s.plan_usage ? "Allowed" : "Not allowed: sign in again and allow it"}</dd>
                  {s.signed_in_at && (
                    <>
                      <dt>Since</dt>
                      <dd>{dateTime(new Date(s.signed_in_at * 1000).toISOString())}</dd>
                    </>
                  )}
                </dl>
                <Conversations canSend={s.plan_usage} />
                <div className="row" style={{ gap: 8 }}>
                  <button type="button" className="btn small ghost" onClick={() => connect.mutate()} disabled={connect.isPending || !!s.unavailable_reason}>
                    Sign in again
                  </button>
                  <button type="button" className="btn small danger" onClick={() => setConfirming(true)}>
                    Sign out
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="small" style={{ margin: 0 }}>
                  Use your own ChatGPT Plus or Pro plan inside RecallSpring. Requests count toward your plan's usage limits;
                  RecallSpring has no API key and never switches to paid usage.
                </p>
                <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
                  <li>Only what you send from here goes to OpenAI, and only when you press a button.</li>
                  <li>Your sign-in stays protected on this computer (encrypted on Windows), never in the browser or in backups.</li>
                  <li>Preview: a plain chat with ChatGPT, saved here with the model, time and tokens of each reply. Claude remains your tutor.</li>
                </ul>
                {s.unavailable_reason === "not_local" ? (
                  <div className="notice small">
                    Sign in with ChatGPT works while RecallSpring runs on your own computer (open it at http://127.0.0.1).
                    On a server it needs a separate setup that is not available yet.
                  </div>
                ) : s.unavailable_reason === "disabled" ? (
                  <div className="notice small">Sign in with ChatGPT is turned off on this RecallSpring.</div>
                ) : (
                  <div>
                    <button type="button" className="btn primary" onClick={() => connect.mutate()} disabled={connect.isPending}>
                      {connect.isPending ? "Opening ChatGPT…" : "Sign in with ChatGPT"}
                    </button>
                  </div>
                )}
                {s.unreadable && (
                  <p className="tiny muted" style={{ margin: 0 }}>
                    A saved sign-in could not be read on this Windows account; signing in again replaces it.
                  </p>
                )}
                <Conversations canSend={false} />
              </>
            )}
            {connect.error && <ErrorNote error={connect.error} />}
          </div>
        )}
      </Async>
      <Confirm
        open={confirming}
        title="Sign out of ChatGPT?"
        confirmLabel="Sign out"
        danger
        busy={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
        onClose={() => setConfirming(false)}
      >
        <p>RecallSpring asks OpenAI to end this sign-in and deletes it from this computer. Nothing else changes.</p>
        {disconnect.error && <ErrorNote error={disconnect.error} />}
      </Confirm>
      {disconnect.data && !disconnect.data.revoked && (
        <div className="notice warn small" role="status">
          Removed from this computer, but OpenAI could not be reached to end the sign-in. You can also remove
          RecallSpring in ChatGPT's settings.
        </div>
      )}
    </div>
  );
}
