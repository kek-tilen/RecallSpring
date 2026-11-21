import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { get, request } from "../api";
import { dateTime } from "../format";
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

interface Turn {
  role: "user" | "assistant";
  text: string;
}

const STATUS_KEY = ["ai", "chatgpt"] as const;

const OUTCOME: Record<string, { text: string; warn?: boolean }> = {
  connected: { text: "Signed in with ChatGPT. Try a message below." },
  no_plan_usage: {
    text: "Signed in, but using your ChatGPT plan was not allowed. Sign in again and allow it to send messages.",
    warn: true,
  },
  declined: { text: "Sign-in was cancelled. Nothing was saved.", warn: true },
  expired: { text: "That sign-in had expired or was already used. Start it again.", warn: true },
  error: { text: "The sign-in did not work. Try again; if it keeps failing, check History for details.", warn: true },
};

function TestChat() {
  const models = useQuery({ queryKey: [...STATUS_KEY, "models"], queryFn: () => get<{ slug: string; display_name: string }[]>("/ai/chatgpt/models") });
  const [model, setModel] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const chosen = model || models.data?.[0]?.slug || "";
  const send = useMutation({
    mutationFn: (text: string) =>
      request<{ reply: string; model: string }>("/ai/chatgpt/test", { json: { model: chosen, message: text, history: turns } }),
    onSuccess: (r, text) => {
      setTurns((t) => [...t, { role: "user", text }, { role: "assistant", text: r.reply }]);
      setMessage("");
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (message.trim() && chosen) send.mutate(message.trim());
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
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
      {turns.length > 0 && (
        <ol className="list small" aria-label="Test conversation" style={{ listStyle: "none", paddingLeft: 0 }}>
          {turns.map((t, i) => (
            <li key={i}>
              <div className="tiny muted">{t.role === "user" ? "You" : "ChatGPT"}</div>
              <div className="pre">{t.text}</div>
            </li>
          ))}
        </ol>
      )}
      <form className="stack" style={{ gap: 8 }} onSubmit={submit}>
        <label className="field">
          <span className="sr-only">Test message</span>
          <textarea rows={2} value={message} maxLength={4000} onChange={(e) => setMessage(e.target.value)} placeholder="Say hello" />
        </label>
        <div className="row" style={{ gap: 8, justifyContent: "space-between", flexWrap: "wrap" }}>
          <span className="tiny muted">A connection test: not saved, and Claude stays your tutor.</span>
          <span className="row" style={{ gap: 8 }}>
            <button type="button" className="btn small ghost" onClick={() => setTurns([])} disabled={!turns.length || send.isPending}>
              Clear
            </button>
            <button type="submit" className="btn small primary" disabled={!message.trim() || !chosen || send.isPending}>
              {send.isPending ? "Waiting for ChatGPT…" : "Send"}
            </button>
          </span>
        </div>
      </form>
      {send.error && <ErrorNote error={send.error} />}
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
                {s.plan_usage && <TestChat />}
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
                  <li>Preview: for now you can test the connection. Claude remains your tutor.</li>
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
