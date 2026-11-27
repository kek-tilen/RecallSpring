import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { get, request } from "../api";
import { dateTime } from "../format";
import { Async, Confirm, ErrorNote } from "./ui";

export interface ChatGptStatus {
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

export const STATUS_KEY = ["ai", "chatgpt"] as const;

export function useChatGptStatus() {
  return useQuery({ queryKey: STATUS_KEY, queryFn: () => get<ChatGptStatus>("/ai/chatgpt") });
}

export const OUTCOME: Record<string, { text: string; warn?: boolean }> = {
  connected: { text: "Signed in with ChatGPT." },
  no_plan_usage: {
    text: "Signed in, but using your ChatGPT plan was not allowed. Sign in again and allow it to send messages.",
    warn: true,
  },
  declined: { text: "Sign-in was cancelled. Nothing was saved.", warn: true },
  expired: { text: "That sign-in had expired or was already used. Start it again.", warn: true },
  error: { text: "The sign-in did not work. Try again; if it keeps failing, check History for details.", warn: true },
};

/** The official "Sign in with ChatGPT" button, or why it is not available here. `back`: the page the sign-in returns
 * to (Settings by default); `before`: saved first, since the browser leaves RecallSpring for ChatGPT. */
export function ChatGptSignIn({ status, compact, again, back, before }: {
  status: ChatGptStatus;
  compact?: boolean;
  again?: boolean;
  back?: "welcome";
  before?: () => Promise<unknown>;
}) {
  const connect = useMutation({
    mutationFn: async () => {
      await before?.();
      return request<{ authorize_url: string }>(`/ai/chatgpt/connect${back ? `?back=${back}` : ""}`, { method: "POST" });
    },
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
  if (status.unavailable_reason === "not_local") {
    return (
      <div className="notice small">
        Sign in with ChatGPT works while RecallSpring runs on your own computer (open it at http://127.0.0.1). On a
        server it needs a separate setup that is not available yet.
      </div>
    );
  }
  if (status.unavailable_reason === "disabled") {
    return <div className="notice small">Sign in with ChatGPT is turned off on this RecallSpring.</div>;
  }
  const label = again ? "Sign in again" : "Sign in with ChatGPT";
  return (
    <>
      <button
        type="button"
        className={again ? "btn small ghost" : compact ? "btn small primary" : "btn primary"}
        onClick={() => connect.mutate()}
        disabled={connect.isPending}
      >
        {connect.isPending ? "Opening ChatGPT…" : label}
      </button>
      {connect.error && <ErrorNote error={connect.error} />}
    </>
  );
}

/** Settings → ChatGPT: the connection only. Conversations live on the Chat page. */
export function ChatGptPanel() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const outcome = OUTCOME[params.get("chatgpt") ?? ""];
  const status = useChatGptStatus();
  const [confirming, setConfirming] = useState(false);
  const disconnect = useMutation({
    mutationFn: () => request<ChatGptStatus & { revoked: boolean }>("/ai/chatgpt/disconnect", { method: "POST" }),
    onSuccess: (s) => {
      qc.setQueryData(STATUS_KEY, s);
      void qc.invalidateQueries({ queryKey: ["settings", "connector", "assistants"] });
      setConfirming(false);
    },
  });

  return (
    <div className="stack" id="chatgpt">
      {outcome && (
        <div className={outcome.warn ? "notice warn small" : "notice small"} role="status">
          {outcome.text} {!outcome.warn && <Link to="/chat">Open Chat</Link>}{" "}
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
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <Link className="btn small primary" to="/chat">
                    Open Chat
                  </Link>
                  <ChatGptSignIn status={s} again />
                  <button type="button" className="btn small danger" onClick={() => setConfirming(true)}>
                    Sign out
                  </button>
                </div>
                <p className="tiny muted" style={{ margin: 0 }}>
                  Signing out ends this sign-in on this computer. Your saved conversations stay in Chat.
                </p>
              </>
            ) : (
              <>
                <p className="small" style={{ margin: 0 }}>
                  Use your own ChatGPT Plus or Pro plan inside RecallSpring. Requests count toward your plan's usage limits;
                  RecallSpring has no API key and never switches to paid usage.
                </p>
                <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
                  <li>Only what you send from Chat goes to OpenAI, and only when you press Send.</li>
                  <li>Your sign-in stays protected on this computer (encrypted on Windows), never in the browser or in backups.</li>
                  <li>Preview: each reply is saved here with its model, time and tokens. With a course picked under Study, ChatGPT tutors you from your RecallSpring records.</li>
                </ul>
                <div>
                  <ChatGptSignIn status={s} />
                </div>
                {s.unreadable && (
                  <p className="tiny muted" style={{ margin: 0 }}>
                    A saved sign-in could not be read on this Windows account; signing in again replaces it.
                  </p>
                )}
                <p className="tiny muted" style={{ margin: 0 }}>
                  Earlier conversations stay readable in <Link to="/chat">Chat</Link>.
                </p>
              </>
            )}
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
        <p>RecallSpring asks OpenAI to end this sign-in and deletes it from this computer. Your conversations stay in Chat.</p>
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
