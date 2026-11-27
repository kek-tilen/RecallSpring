import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { get, request } from "../api";
import { ASSISTANTS } from "../assistant";
import { dateTime } from "../format";
import { AssistantNextSteps, choiceBody, TILE, useSaveProfile } from "../pages/Welcome";
import { keys, useSession } from "../queries";
import type { AssistantClient, AssistantKey, AssistantsStatus, ConnectorSettings, ConnectorToken } from "../types";
import { ChatGptPanel, STATUS_KEY } from "./ChatGpt";
import { CopyButton } from "./Copy";
import { Confirm, ErrorNote, Modal } from "./ui";

/**
 * Settings › Assistants as rows (2026-11-27): the welcome page's tick boxes on top, one row per ticked (or still
 * connected) assistant with Set up / Manage / Sign in opening in place, and the daily request limit. Unticking a
 * connected one asks whether to disconnect it too. Set up can also connect an assistant on another computer to this
 * RecallSpring's address (the remote connector at /mcp), when the server settings give one.
 */

const NEEDS: Record<AssistantKey, string> = {
  claude: "Needs Claude Desktop and a paid Claude plan",
  codex: "Needs Codex, signed in with your ChatGPT plan",
  antigravity: "Needs Google Antigravity, signed in with your Google account",
  chatgpt: "Chat inside RecallSpring · your ChatGPT plan, not a paid API",
};

const isClient = (k: AssistantKey): k is AssistantClient => k !== "chatgpt";

function pickedOf(s: AssistantsStatus): AssistantKey[] {
  if (s.chosen === "mix") return s.mix ?? [];
  return s.chosen ? [s.chosen] : [];
}

function lastUsed(at: string | null, connected: boolean): string {
  if (at) return `last used ${dateTime(at)}`;
  return connected ? "not used yet" : "";
}

/** The connector settings, polled while Check connection waits for the assistant's first request. */
function useConnectorPoll(polling: boolean) {
  return useQuery({
    queryKey: keys.connector,
    queryFn: () => get<ConnectorSettings>("/settings/connector"),
    refetchInterval: polling ? 3000 : false,
  });
}

function TokenRow({ t, onRevoke }: { t: ConnectorToken; onRevoke: (t: ConnectorToken) => void }) {
  return (
    <li className="token-item">
      <div className="token-main">
        <strong className="small">{t.label}</strong>
        <span className="tiny muted">
          Made {dateTime(t.created_at)} · {t.last_used_at ? `used ${dateTime(t.last_used_at)}` : "not used yet"}
        </span>
      </div>
      <button type="button" className="btn small danger" onClick={() => onRevoke(t)} aria-label={`Revoke ${t.label}`}>
        Revoke
      </button>
    </li>
  );
}

/** A token made here is shown once, with Copy. */
function ShownToken({ token, onHide }: { token: string; onHide: () => void }) {
  return (
    <div className="notice warn stack" role="status" style={{ gap: 6 }}>
      <strong className="small">Copy this token now. It is shown only once.</strong>
      <div className="token-box">{token}</div>
      <div className="row" style={{ gap: 8 }}>
        <CopyButton text={token} label="Copy token" />
        <button type="button" className="btn small ghost" onClick={onHide}>
          Hide
        </button>
      </div>
      <span className="tiny">Never paste it into a chat.</span>
    </div>
  );
}

function useNewToken(client: AssistantClient) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (label?: string) =>
      request<ConnectorToken & { token: string | null }>("/settings/connector/tokens", { json: { client, ...(label ? { label } : {}) } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.connector }),
  });
}

/** Steps for an assistant on another computer: a token, where the assistant keeps it, this RecallSpring's address. */
export function RemoteSteps({ client, c }: { client: AssistantClient; c: ConnectorSettings }) {
  const name = TILE[client].name;
  const make = useNewToken(client);
  const [token, setToken] = useState<string | null>(null);
  const [since, setSince] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const poll = useConnectorPoll(since !== null && !timedOut);
  const url = c.remote_url ?? "";
  // Check connection compares with the tokens' last use when it was pressed (server times, not this device's clock).
  const mine = (poll.data ?? c).tokens.filter((t) => t.client === client && !t.revoked_at);
  const reached = since !== null ? mine.find((t) => t.last_used_at && t.last_used_at > since) : undefined;
  useEffect(() => {
    if (since === null || reached) return;
    const timer = window.setTimeout(() => setTimedOut(true), 120_000);
    return () => window.clearTimeout(timer);
  }, [since, reached]);

  if (client === "claude" && !c.remote_from_internet) {
    return (
      <div className="stack small" style={{ gap: 6 }}>
        <div className="notice small">
          This RecallSpring has no public address, so Claude cannot reach it from another computer. Codex and Antigravity can.
        </div>
        <span className="tiny muted">
          Claude Desktop, claude.ai and the Claude phone app connect from Anthropic&apos;s cloud, not from your computer, so the address must be
          reachable from the internet over HTTPS (port 443). That is a server setting and a step on the proxy (docs/remote-connector.md). Until
          then, Claude works when RecallSpring runs on the same computer.
        </span>
      </div>
    );
  }

  const shown = token ?? "<the token>";
  const codexConfig = `[mcp_servers.recallspring]\nurl = "${url}"\nbearer_token_env_var = "RECALLSPRING_TOKEN"`;
  const antigravityConfig = JSON.stringify(
    { mcpServers: { recallspring: { serverUrl: url, headers: { Authorization: `Bearer ${shown}` } } } },
    null,
    2,
  );
  return (
    <ol className="stack small remote-steps" style={{ gap: 8, paddingLeft: 20, margin: 0 }}>
      <li className="stack" style={{ gap: 6 }}>
        <span>Make a token for {name}. It is shown once.</span>
        {token ? (
          <ShownToken token={token} onHide={() => setToken(null)} />
        ) : (
          <div>
            <button
              type="button"
              className="btn small"
              disabled={make.isPending}
              onClick={() => make.mutate(`${name} · another computer`, { onSuccess: (t) => setToken(t.token) })}
            >
              Make a token for {name}
            </button>
          </div>
        )}
        {make.error && <ErrorNote error={make.error} />}
      </li>
      {client === "codex" && (
        <>
          <li className="stack" style={{ gap: 4 }}>
            <span>In PowerShell on the computer you study on, keep it for Codex (only your Windows account can read it):</span>
            <code className="welcome-command">setx RECALLSPRING_TOKEN &quot;{shown}&quot;</code>
            {token && (
              <div>
                <CopyButton text={`setx RECALLSPRING_TOKEN "${token}"`} label="Copy command" />
              </div>
            )}
          </li>
          <li className="stack" style={{ gap: 4 }}>
            <span>
              Add this to <code>~/.codex/config.toml</code>, then restart Codex:
            </span>
            <code className="welcome-command" style={{ whiteSpace: "pre-wrap" }}>
              {codexConfig}
            </code>
            <div>
              <CopyButton text={codexConfig} label="Copy settings" />
            </div>
          </li>
        </>
      )}
      {client === "antigravity" && (
        <li className="stack" style={{ gap: 4 }}>
          <span>
            Add this to Antigravity&apos;s <code>~/.gemini/config/mcp_config.json</code> (keep any other servers in it), then restart Antigravity.
            Antigravity keeps the token in that file.
          </span>
          <code className="welcome-command" style={{ whiteSpace: "pre-wrap" }}>
            {antigravityConfig}
          </code>
          {token && (
            <div>
              <CopyButton text={antigravityConfig} label="Copy settings" />
            </div>
          )}
        </li>
      )}
      {client === "claude" && (
        <li className="stack" style={{ gap: 4 }}>
          <span>In Claude: Settings › Connectors › Add custom connector.</span>
          <dl className="kv small">
            <dt>URL</dt>
            <dd>
              <code>{url}</code> <CopyButton text={url} label="Copy address" />
            </dd>
            <dt>Authentication</dt>
            <dd>No sign in</dd>
            <dt>Request header</dt>
            <dd>
              <code>Authorization</code>: <code>Bearer {shown}</code>
            </dd>
          </dl>
          <span className="tiny muted">Works in Claude on your phone too. A free Claude plan allows one custom connector.</span>
        </li>
      )}
      <li className="stack" style={{ gap: 4 }}>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn small"
            disabled={since !== null && !reached && !timedOut}
            onClick={() => {
              setTimedOut(false);
              setSince(mine.reduce((m, t) => (t.last_used_at && t.last_used_at > m ? t.last_used_at : m), ""));
            }}
          >
            Check connection
          </button>
          <span className="small" role="status">
            {reached
              ? `Connected: ${name} reached RecallSpring at ${dateTime(reached.last_used_at!)}.`
              : timedOut
                ? `No request from ${name} yet. Check the address and the token, and that ${name} was restarted.`
                : since !== null
                  ? `Waiting for ${name}… Start it or open a new session.`
                  : ""}
          </span>
        </div>
        {since === null && <span className="tiny muted">Check connection waits for {name}&apos;s first request and then says Connected.</span>}
      </li>
    </ol>
  );
}

/** Set up: this computer (the welcome page's steps) or another computer (the remote connector), when it has an address. */
function SetUp({ client, c, username }: { client: AssistantClient; c: ConnectorSettings | undefined; username: string }) {
  const [where, setWhere] = useState<"here" | "remote">("here");
  if (!c?.remote_url) {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <AssistantNextSteps assistant={client} username={username} />
        <span className="tiny muted">
          From another computer: RecallSpring needs an address other computers can reach (a server setting, docs/remote-connector.md).
        </span>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="seg" role="group" aria-label={`Where ${TILE[client].name} runs`}>
        <button type="button" aria-pressed={where === "here"} onClick={() => setWhere("here")}>
          On this computer
        </button>
        <button type="button" aria-pressed={where === "remote"} onClick={() => setWhere("remote")}>
          From another computer
        </button>
      </div>
      {where === "here" ? <AssistantNextSteps assistant={client} username={username} /> : <RemoteSteps client={client} c={c} />}
    </div>
  );
}

/** Manage a connected app: its tokens, a new token, setting up another computer, and Disconnect. */
function Manage({ client, c, username }: { client: AssistantClient; c: ConnectorSettings | undefined; username: string }) {
  const qc = useQueryClient();
  const name = TILE[client].name;
  const make = useNewToken(client);
  const [token, setToken] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ConnectorToken | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: keys.connector });
  const revoke = useMutation({
    mutationFn: (t: ConnectorToken) => request<ConnectorToken>(`/settings/connector/tokens/${t.id}/revoke`, { method: "POST", json: {} }),
    onSuccess: () => {
      setRevoking(null);
      refresh();
    },
  });
  const disconnect = useDisconnect(client, () => setDisconnecting(false));
  const tokens = (c?.tokens ?? []).filter((t) => t.client === client && !t.revoked_at);
  return (
    <div className="stack" style={{ gap: 10 }}>
      <h4 className="small" style={{ margin: 0 }}>
        Tokens
      </h4>
      {tokens.length > 0 ? (
        <ul className="token-list" aria-label={`${name} tokens`}>
          {tokens.map((t) => (
            <TokenRow key={t.id} t={t} onRevoke={setRevoking} />
          ))}
        </ul>
      ) : (
        <p className="small muted">No active tokens.</p>
      )}
      {token && <ShownToken token={token} onHide={() => setToken(null)} />}
      {make.error && <ErrorNote error={make.error} />}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn small" disabled={make.isPending} onClick={() => make.mutate(undefined, { onSuccess: (t) => setToken(t.token) })}>
          New token
        </button>
        <button type="button" className="btn small danger" onClick={() => setDisconnecting(true)}>
          Disconnect {name}
        </button>
      </div>
      <span className="tiny muted">
        {client === "codex"
          ? "On this computer the Codex script makes its own token; a new one here is for another computer or a manual setup (docs/codex-setup.md)."
          : client === "antigravity"
            ? "On this computer the Antigravity script makes its own token; a new one here is for another computer or a manual setup (docs/antigravity-setup.md)."
            : "On this computer the installer script reads the token from the connector's token file (docs/connector-setup.md)."}
      </span>
      <details className="settings-details">
        <summary>Set up {name} again or on another computer</summary>
        <SetUp client={client} c={c} username={username} />
      </details>
      <Confirm
        open={revoking !== null}
        title="Revoke this token?"
        confirmLabel="Revoke token"
        danger
        busy={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
        onClose={() => setRevoking(null)}
      >
        {name} using “{revoking?.label}” loses access to RecallSpring immediately. Your study records stay as they are. This cannot be undone; make a
        new token to reconnect.
        {revoke.error && <ErrorNote error={revoke.error} />}
      </Confirm>
      <Confirm
        open={disconnecting}
        title={`Disconnect ${name}?`}
        confirmLabel="Disconnect"
        danger
        busy={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
        onClose={() => setDisconnecting(false)}
      >
        All {tokens.length === 1 ? "of its tokens (1)" : `${tokens.length} of its tokens`} stop working at once. Its grades and your records stay as they
        are; a new token connects it again. Recorded in History.
        {disconnect.error && <ErrorNote error={disconnect.error} />}
      </Confirm>
    </div>
  );
}

/** Disconnect one assistant: revoke all its tokens, or sign out of ChatGPT. */
function useDisconnect(key: AssistantKey, done?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      key === "chatgpt"
        ? request<unknown>("/ai/chatgpt/disconnect", { method: "POST" })
        : request<unknown>(`/settings/connector/clients/${key}/disconnect`, { method: "POST", json: {} }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.connector });
      if (key === "chatgpt") void qc.invalidateQueries({ queryKey: STATUS_KEY });
      done?.();
    },
  });
}

function LimitRow({ c }: { c: ConnectorSettings }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [percent, setPercent] = useState(c.limit_percent);
  useEffect(() => setPercent(c.limit_percent), [c.limit_percent]);
  const save = useMutation({
    mutationFn: () => request<ConnectorSettings>("/settings/connector", { method: "PUT", json: { limit_percent: percent } }),
    onSuccess: (v) => {
      qc.setQueryData(keys.connector, v);
      setOpen(false);
    },
  });
  const projected = Math.max(1, Math.round((c.daily_default * percent) / 100));
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="settings-row">
        <span>
          <h3 className="settings-row-title">Daily request limit</h3>
          <span className="small muted">
            {c.limit_percent} % · {c.daily_limit} requests a day for all assistants together · {c.used_today} used today
          </span>
        </span>
        <button type="button" className="btn small" aria-expanded={open} aria-label="Change the daily request limit" onClick={() => setOpen(!open)}>
          {open ? "Close" : "Change"}
        </button>
      </div>
      {open && (
        <form
          className="stack assistant-steps"
          aria-label="Daily request limit"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <label className="field">
            {percent} % ({projected} requests a day)
            <span className="hint">Caps how many connector calls your assistants make per day together, to protect your plans&apos; usage.</span>
            <input type="range" min={1} max={100} value={percent} onChange={(e) => setPercent(Number(e.target.value))} />
          </label>
          {save.error && <ErrorNote error={save.error} />}
          <div>
            <button type="submit" className="btn small primary" disabled={percent === c.limit_percent || save.isPending}>
              Save limit
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

export function AssistantsPanel({ s, c }: { s: AssistantsStatus; c?: ConnectorSettings }) {
  const qc = useQueryClient();
  const { hash } = useLocation();
  const [params] = useSearchParams();
  const username = useSession().data?.user.username ?? "";
  const label = (key: AssistantKey) => TILE[key].name;
  const [picked, setPicked] = useState<AssistantKey[]>(() => pickedOf(s));
  useEffect(() => setPicked(pickedOf(s)), [s.chosen, s.mix?.join()]);
  const [open, setOpen] = useState<AssistantKey | null>(hash === "#chatgpt" || params.has("chatgpt") ? "chatgpt" : null);
  const [unticking, setUnticking] = useState<AssistantKey | null>(null);
  const save = useSaveProfile();
  const disconnect = useDisconnect(unticking ?? "chatgpt");
  const item = (key: AssistantKey) => s.items.find((i) => i.key === key);
  const order = ASSISTANTS.map((a) => a.key);

  function choose(next: AssistantKey[], then?: () => void) {
    const sorted = order.filter((k) => next.includes(k));
    setPicked(sorted);
    save.mutate(choiceBody(sorted), {
      onSuccess: () => {
        void qc.invalidateQueries({ queryKey: keys.assistants });
        then?.();
      },
    });
  }

  function toggle(key: AssistantKey, on: boolean) {
    if (on) {
      choose([...picked, key]);
      if (!item(key)?.connected) setOpen(key);
    } else if (item(key)?.connected) {
      setUnticking(key);
    } else {
      choose(picked.filter((k) => k !== key));
      if (open === key) setOpen(null);
    }
  }

  const rows = order.filter((k) => picked.includes(k) || item(k)?.connected);
  const connected = s.items.filter((i) => i.connected);
  const leaving = unticking ? item(unticking) : undefined;
  return (
    <>
      <fieldset className="welcome-pick assistant-pick-tiles">
        <legend className="settings-row-title">Assistants you use</legend>
        <div className="welcome-tiles assistant-tiles">
          {order.map((k) => (
            <label key={k} className="welcome-tile">
              <input type="checkbox" checked={picked.includes(k)} disabled={save.isPending} onChange={(e) => toggle(k, e.target.checked)} />
              <span>{label(k)}</span>
            </label>
          ))}
        </div>
        {save.error && <ErrorNote error={save.error} />}
      </fieldset>
      {rows.length === 0 && <p className="small muted">None chosen. RecallSpring works without one: material, notes, reviews and plans.</p>}
      {rows.map((k) => {
        const i = item(k);
        const on = Boolean(i?.connected);
        const verb = k === "chatgpt" ? (on ? "Manage" : "Sign in") : on ? "Manage" : "Set up";
        const detail = on
          ? [k === "chatgpt" ? NEEDS.chatgpt : "", lastUsed(i?.last_used_at ?? null, true), i && i.tokens > 1 ? `${i.tokens} tokens` : ""]
          : [NEEDS[k]];
        return (
          <div key={k} className="stack" style={{ gap: 10 }} id={k === "chatgpt" ? "chatgpt" : undefined}>
            <div className="settings-row">
              <span>
                <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <h3 className="settings-row-title">{label(k)}</h3>
                  <span className={on ? "chip good" : "chip"}>{k === "chatgpt" ? (on ? "Signed in" : "Not signed in") : on ? "Connected" : "Not connected"}</span>
                  {!picked.includes(k) && <span className="chip">Not in your list</span>}
                </span>
                <span className="small muted">{detail.filter(Boolean).join(" · ")}</span>
              </span>
              <button
                type="button"
                className="btn small"
                aria-expanded={open === k}
                aria-label={`${verb} ${label(k)}`}
                onClick={() => setOpen(open === k ? null : k)}
              >
                {open === k ? "Close" : verb}
              </button>
            </div>
            {open === k && (
              <div className="assistant-steps">
                {k === "chatgpt" ? (
                  <ChatGptPanel />
                ) : on ? (
                  <Manage client={k} c={c} username={username} />
                ) : isClient(k) ? (
                  <SetUp client={k} c={c} username={username} />
                ) : null}
              </div>
            )}
          </div>
        );
      })}
      {c && <LimitRow c={c} />}
      <p className="hint small muted" style={{ margin: 0 }}>
        {connected.length > 1
          ? "Several are connected, so RecallSpring says “your assistant”. "
          : connected.length === 1
            ? `RecallSpring names ${label(connected[0]!.key)} in its tips. `
            : ""}
        Every connected assistant works at the same time; grades are labelled with the one that gave them. Every change is recorded in{" "}
        <Link to="/history">History</Link>.
      </p>
      <Modal open={unticking !== null} title={unticking ? `Stop using ${label(unticking)}?` : ""} onClose={() => setUnticking(null)}>
        {unticking && (
          <>
            <p className="small">
              {unticking === "chatgpt"
                ? "You are still signed in with ChatGPT. Your conversations stay in Chat."
                : `${label(unticking)} is still connected (${leaving?.tokens === 1 ? "1 token" : `${leaving?.tokens ?? 0} tokens`}). Its grades stay as they are.`}
            </p>
            {disconnect.error && <ErrorNote error={disconnect.error} />}
            <div className="row" style={{ justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="btn" onClick={() => setUnticking(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={disconnect.isPending}
                onClick={() =>
                  disconnect.mutate(undefined, {
                    onSuccess: () => {
                      const key = unticking;
                      choose(
                        picked.filter((k) => k !== key),
                        () => void qc.invalidateQueries({ queryKey: keys.connector }),
                      );
                      setOpen(null);
                      setUnticking(null);
                    },
                  })
                }
              >
                Also disconnect
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  const key = unticking;
                  choose(picked.filter((k) => k !== key));
                  setUnticking(null);
                }}
              >
                Keep it connected
              </button>
            </div>
            <p className="tiny muted" style={{ margin: 0 }}>
              {unticking === "chatgpt" ? "Signing out ends the ChatGPT sign-in on this computer." : "Disconnect revokes its tokens at once."} Recorded in
              History.
            </p>
          </>
        )}
      </Modal>
    </>
  );
}
