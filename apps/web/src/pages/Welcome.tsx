import { BrandMark } from "../components/BrandMark";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { request } from "../api";
import { ASSISTANTS } from "../assistant";
import { ChatGptSignIn, OUTCOME, useChatGptStatus } from "../components/ChatGpt";
import { CopyButton } from "../components/Copy";
import { ErrorNote } from "../components/ui";
import { keys, useSession } from "../queries";
import type { AssistantChoice, AssistantKey, ExplanationPace, SessionInfo, User } from "../types";

/**
 * A new install (plan-without-claude.md, Phase 3): the first visit creates the account (FirstRunForm, shown on the
 * sign-in page while no account exists), then /welcome (no rail yet, 2026-11-27) asks which assistants the learner
 * studies with and shows one command for those with a connector. Changeable later in Settings › Assistants.
 */

export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function timeZones(current: string): string[] {
  const supported = (Intl as unknown as { supportedValuesOf?: (key: "timeZone") => string[] }).supportedValuesOf;
  const list = supported ? supported("timeZone") : [];
  return [...new Set([...list, current, "UTC"])].sort();
}

export function TimeZoneSelect({ value, onChange, id }: { value: string; onChange: (tz: string) => void; id?: string }) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {timeZones(value).map((z) => (
        <option key={z} value={z}>
          {z.replaceAll("_", " ")}
        </option>
      ))}
    </select>
  );
}

/** The first account of a new install. Only shown (and only accepted by the server) on this computer, or with the
 * code of a setup link (the Docker install prints one), which it sends along. */
export function FirstRunForm({ setupCode = null }: { setupCode?: string | null }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [timezone, setTimezone] = useState(browserZone);
  const mismatch = repeat.length > 0 && repeat !== password;
  const create = useMutation({
    mutationFn: () =>
      request<SessionInfo>("/auth/setup", {
        method: "POST",
        json: setupCode ? { username, password, timezone, setup_code: setupCode } : { username, password, timezone },
      }),
    onSuccess: (session) => {
      qc.setQueryData(keys.session, session);
      navigate("/welcome", { replace: true });
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (password.length >= 12 && password === repeat) create.mutate();
  }
  return (
    <form className="card" onSubmit={submit} aria-labelledby="setup-title">
      <div className="row" style={{ gap: 12 }}>
        <BrandMark size={36} />
        <div>
          <h1 id="setup-title" style={{ fontSize: "1.3rem" }}>
            Welcome to RecallSpring
          </h1>
          <p className="muted small">Create your account. It stays on this computer.</p>
        </div>
      </div>
      <label className="field">
        Username
        <input
          type="text"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          minLength={3}
          maxLength={64}
          pattern="[A-Za-z0-9._@\-]+"
          aria-describedby="setup-username-hint"
          autoFocus
        />
        <span id="setup-username-hint" className="hint">
          Letters, digits and . _ @ - (at least 3).
        </span>
      </label>
      <label className="field">
        Password
        <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={12} aria-describedby="setup-password-hint" />
        <span id="setup-password-hint" className="hint">
          At least 12 characters. There is no reset by e-mail: keep it in your password manager.
        </span>
      </label>
      <label className="field">
        Repeat password
        <input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required aria-invalid={mismatch} />
        {mismatch && <span className="hint chat-error">The passwords do not match.</span>}
      </label>
      <label className="field">
        Time zone
        <TimeZoneSelect value={timezone} onChange={setTimezone} />
        <span className="hint">Used for “today”, plans and dates. Taken from this computer; change it if it is wrong.</span>
      </label>
      {create.error && <ErrorNote error={create.error} />}
      <button type="submit" className="btn primary" disabled={create.isPending || password.length < 12 || password !== repeat}>
        {create.isPending ? "Creating…" : "Create account"}
      </button>
      <p className="muted tiny">This account is RecallSpring&apos;s own. It is separate from Claude, ChatGPT and any AI provider.</p>
    </form>
  );
}

const ABOUT: Record<AssistantKey, { needs: string; summary: string }> = {
  claude: {
    needs: "Claude Desktop and a paid Claude plan.",
    summary: "You study in Claude Desktop. Claude reads your plan and material through RecallSpring's connector and shows question and summary forms in the chat.",
  },
  codex: {
    needs: "Codex (app, CLI or IDE extension), signed in with your ChatGPT plan.",
    summary: "You study in Codex, in one folder per course. Codex uses RecallSpring's connector and shows its question and summary forms in the conversation.",
  },
  antigravity: {
    needs: "Google Antigravity (app or CLI), signed in with your Google account (free, Google AI Plus or Pro).",
    summary: "You study in Antigravity, in one folder per course. Antigravity uses RecallSpring's connector and shows its question and summary forms in the conversation.",
  },
  chatgpt: {
    needs: "A ChatGPT Plus or Pro plan. Works while RecallSpring runs on this computer (preview).",
    summary:
      "You study in RecallSpring's Chat page. A planning conversation sets up your courses and exam dates; a conversation about one course " +
      "teaches from your material and asks questions in forms right in the chat.",
  },
};

/** What to do next for the chosen assistant. */
export function AssistantNextSteps({ assistant, username }: { assistant: AssistantKey; username: string }) {
  if (assistant === "chatgpt") {
    return (
      <ol className="stack small" style={{ gap: 6, paddingLeft: 20, margin: 0 }}>
        <li>
          Open <Link to="/settings#chatgpt">Settings → ChatGPT</Link> and choose <strong>Sign in with ChatGPT</strong> (allow plan usage).
        </li>
        <li>
          Add your material under <Link to="/library">Library</Link>. Then open <Link to="/chat">Chat</Link>: a new conversation with{" "}
          <strong>Planning (all courses)</strong> under Study sets up your courses and midterm and exam dates (“Let&apos;s set up my semester”).
        </li>
        <li>
          To learn, start a new conversation, pick the course under <strong>Study</strong> and write “Start studying”.
        </li>
      </ol>
    );
  }
  // The Claude script reads the token file written by connector-token; the Codex and Antigravity scripts make their own.
  const commands =
    assistant === "claude"
      ? [
          `services\\api\\.venv\\Scripts\\recallspring connector-token --username ${username}`,
          "powershell -ExecutionPolicy Bypass -File scripts\\install-claude-desktop-connector.ps1",
        ]
      : [`powershell -ExecutionPolicy Bypass -File scripts\\install-${assistant}-connector.ps1 -Username ${username}`];
  const app = assistant === "antigravity" ? "Antigravity" : "Codex";
  return (
    <ol className="stack small" style={{ gap: 6, paddingLeft: 20, margin: 0 }}>
      <li>
        {assistant === "claude"
          ? "Install Claude Desktop (Microsoft Store) and sign in."
          : assistant === "antigravity"
            ? "Install Google Antigravity (antigravity.google) and sign in with your Google account."
            : "Install Codex and sign in with ChatGPT."}
      </li>
      <li>
        In PowerShell, in the RecallSpring folder, run{commands.length > 1 ? " one after the other" : ""}:
        {commands.map((command) => (
          <div key={command} className="row" style={{ gap: 8, marginTop: 4, flexWrap: "wrap" }}>
            <code className="mono" style={{ overflowWrap: "anywhere" }}>
              {command}
            </code>
            <CopyButton text={command} label="Copy command" />
          </div>
        ))}
        {assistant === "claude"
          ? " The first makes the connector's token (saved on this computer, never shown). After the second, quit Claude Desktop (tray icon → Quit); the script adds RecallSpring and starts it again."
          : ` It connects ${app} and makes a Planning folder and one study folder per course in Documents\\RecallSpring Study.`}
      </li>
      <li>
        {assistant === "claude"
          ? "In Claude Desktop, write “Start studying” (the Guide has prompts for planning and each course)."
          : assistant === "antigravity"
            ? "Restart Antigravity, open a course folder as the workspace and write “Start studying”. Allow RecallSpring's tools when it asks."
            : "Open a course folder in Codex, trust it when asked, and write “Start studying”."}
      </li>
    </ol>
  );
}

export const MIX_SUMMARY =
  "You study with more than one: for example ChatGPT in Chat for one course and Claude for another. Choose which; " +
  "RecallSpring says \u201cyour assistant\u201d and shows the setup steps for each.";

export function AssistantPicker({ value, mix, onChange, name = "assistant", compact = false }: {
  value: AssistantChoice | null;
  /** The assistants of a mix (used when value is "mix"). */
  mix: AssistantKey[];
  onChange: (a: AssistantChoice | null, mix: AssistantKey[]) => void;
  name?: string;
  /** Settings: a visible legend and no descriptions. */
  compact?: boolean;
}) {
  const toggle = (key: AssistantKey, on: boolean) =>
    onChange("mix", ASSISTANTS.map((a) => a.key).filter((k) => (k === key ? on : mix.includes(k))));
  return (
    <fieldset className="assistant-pick">
      <legend className={compact ? "assistant-legend" : "sr-only"}>Assistant</legend>
      {ASSISTANTS.map((a) => (
        <label key={a.key} className={value === a.key ? "assistant-option chosen" : "assistant-option"}>
          <input type="radio" name={name} value={a.key} checked={value === a.key} onChange={() => onChange(a.key, mix)} />
          <span className="stack" style={{ gap: 2 }}>
            <strong>{a.label}</strong>
            {!compact && <span className="small">{ABOUT[a.key].summary}</span>}
            <span className="tiny muted">Needs: {ABOUT[a.key].needs}</span>
          </span>
        </label>
      ))}
      <div className={value === "mix" ? "assistant-option chosen" : "assistant-option"}>
        <input
          id={`${name}-mix`}
          type="radio"
          name={name}
          value="mix"
          checked={value === "mix"}
          onChange={() => onChange("mix", mix)}
        />
        <span className="stack" style={{ gap: 6 }}>
          <label htmlFor={`${name}-mix`} className="stack" style={{ gap: 2 }}>
            <strong>Mix</strong>
            {!compact && <span className="small">{MIX_SUMMARY}</span>}
          </label>
          {value === "mix" && (
            <span className="row assistant-mix" role="group" aria-label="Assistants in your mix">
              {ASSISTANTS.map((a) => (
                <label key={a.key} className="row small" style={{ gap: 6 }}>
                  <input type="checkbox" checked={mix.includes(a.key)} onChange={(e) => toggle(a.key, e.target.checked)} />
                  {a.label}
                </label>
              ))}
            </span>
          )}
          {value === "mix" && mix.length < 2 && (
            <span className="tiny muted" role="status">
              Choose at least two.
            </span>
          )}
        </span>
      </div>
      <label className={value === null ? "assistant-option chosen" : "assistant-option"}>
        <input type="radio" name={name} value="" checked={value === null} onChange={() => onChange(null, mix)} />
        <span className="stack" style={{ gap: 2 }}>
          <strong>{compact ? "Not chosen" : "Decide later"}</strong>
          {!compact && <span className="small">RecallSpring works without an assistant: material, notes, reviews and plans.</span>}
        </span>
      </label>
    </fieldset>
  );
}

export function useSaveProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      assistant?: AssistantChoice | null;
      assistant_mix?: AssistantKey[];
      timezone?: string;
      greeting_name?: string | null;
      explanation_pace?: ExplanationPace;
    }) =>
      request<User>("/settings/profile", { method: "PUT", json: body }),
    onSuccess: (user) => {
      qc.setQueryData<SessionInfo>(keys.session, (s) => (s ? { ...s, user } : s));
    },
  });
}

/** The welcome page's tiles (UI direction, 2026-11-27): tick any; two or more is a mix, none is "not chosen". */
export const TILE: Record<AssistantKey, { name: string; note: string }> = {
  claude: { name: "Claude Desktop", note: "Connector · one command" },
  codex: { name: "Codex", note: "Connector · one command" },
  antigravity: { name: "Antigravity", note: "Connector · one command" },
  chatgpt: { name: "ChatGPT", note: "Sign in with ChatGPT · Chat inside RecallSpring" },
};

/** The one command that sets up every ticked app with a connector (scripts/install-connectors.ps1), or null. */
export function connectorCommand(picked: AssistantKey[], username: string): string | null {
  const apps = picked.filter((k) => k !== "chatgpt");
  if (apps.length === 0) return null;
  return `powershell -ExecutionPolicy Bypass -File scripts\\install-connectors.ps1 -Assistants ${apps.join(",")} -Username ${username}`;
}

export function choiceBody(picked: AssistantKey[]): { assistant: AssistantChoice | null; assistant_mix?: AssistantKey[] } {
  if (picked.length === 0) return { assistant: null };
  if (picked.length === 1) return { assistant: picked[0] ?? null };
  return { assistant: "mix", assistant_mix: picked };
}

function names(keys: AssistantKey[]): string {
  const n = keys.map((k) => TILE[k].name);
  return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n.at(-1) ?? ""}` : (n[0] ?? "");
}

function ChatGptRow({ save }: { save: () => Promise<unknown> }) {
  const status = useChatGptStatus();
  const [params] = useSearchParams();
  const outcome = OUTCOME[params.get("chatgpt") ?? ""];
  return (
    <section className="welcome-box stack" style={{ gap: 8 }} aria-label="ChatGPT">
      <span>ChatGPT</span>
      {outcome && !status.data?.connected && (
        <div className={outcome.warn ? "notice warn small" : "notice small"} role="status">
          {outcome.text}
        </div>
      )}
      {status.data?.connected ? (
        <span className="small" role="status">
          ✓ Signed in with ChatGPT{status.data.plan_usage ? "" : ", but using your plan was not allowed"}
        </span>
      ) : status.data ? (
        <>
          <div>
            <ChatGptSignIn status={status.data} compact back="welcome" before={save} />
          </div>
          {!status.data.unavailable_reason && (
            <span className="tiny muted">Uses your ChatGPT plan, not a paid API. Skip it and sign in later in Settings › Assistants.</span>
          )}
        </>
      ) : (
        <span className="tiny muted">Checking…</span>
      )}
    </section>
  );
}

export function WelcomePage() {
  const session = useSession();
  const user = session.data?.user;
  const navigate = useNavigate();
  const [picked, setPicked] = useState<AssistantKey[] | null>(null);
  const saved: AssistantKey[] = user?.assistant === "mix" ? (user.assistant_mix ?? []) : user?.assistant ? [user.assistant] : [];
  const chosen = ASSISTANTS.map((a) => a.key).filter((k) => (picked ?? saved).includes(k));
  const save = useSaveProfile();
  const command = user ? connectorCommand(chosen, user.username) : null;
  const apps = chosen.filter((k) => k !== "chatgpt");
  const toggle = (key: AssistantKey, on: boolean) => setPicked(ASSISTANTS.map((a) => a.key).filter((k) => (k === key ? on : chosen.includes(k))));
  return (
    <main className="welcome-page">
      <div className="welcome">
        <BrandMark size={34} />
        <h1 className="welcome-title">Welcome to RecallSpring</h1>
        <p className="welcome-lede">
          You learn with an assistant; RecallSpring keeps your material, answers and review dates. Choose who helps you. You can use more than one.
        </p>
        <fieldset className="welcome-pick">
          <legend className="small">Choose your assistant</legend>
          <div className="welcome-tiles">
            {ASSISTANTS.map((a) => (
              <label key={a.key} className="welcome-tile">
                <input type="checkbox" checked={chosen.includes(a.key)} onChange={(e) => toggle(a.key, e.target.checked)} />
                <span className="stack" style={{ gap: 2 }}>
                  <span>{TILE[a.key].name}</span>
                  <span className="tiny muted">{TILE[a.key].note}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {command && user && (
          <section className="welcome-box stack" style={{ gap: 6 }} aria-label="Connector command">
            <span className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <span>Command for {names(apps)}</span>
              <CopyButton text={command} label="Copy command" />
            </span>
            <code className="welcome-command">{command}</code>
            <span className="tiny muted">
              Install {apps.length > 1 ? "the apps" : "the app"} and sign in first. Run it in PowerShell in the RecallSpring folder: it makes the
              connector&apos;s sign-in on this computer (never shown) and adds RecallSpring to {apps.length > 1 ? "each" : "it"}
              {apps.some((k) => k !== "claude") ? ", with one study folder per course in Documents\\RecallSpring Study" : ""}.
              {apps.includes("claude") ? " For Claude Desktop it waits until you quit Claude Desktop (tray icon → Quit), then starts it again." : ""}
            </span>
            <details className="settings-details">
              <summary>Steps for each</summary>
              <div className="stack" style={{ gap: 10 }}>
                {apps.map((k) => (
                  <section key={k} className="stack" style={{ gap: 4 }} aria-label={`Set up ${TILE[k].name}`}>
                    <strong className="small">{TILE[k].name}</strong>
                    <AssistantNextSteps assistant={k} username={user.username} />
                  </section>
                ))}
              </div>
            </details>
          </section>
        )}
        {chosen.includes("chatgpt") && <ChatGptRow save={() => save.mutateAsync(choiceBody(chosen))} />}
        {chosen.length === 0 && (
          <p className="tiny muted">
            None yet is fine: RecallSpring keeps your material, notes, reviews and plans without one. Choose later in Settings › Assistants.
          </p>
        )}
        {save.error && <ErrorNote error={save.error} />}
        <div className="welcome-foot">
          <span className="small muted">Next: add a course and its material</span>
          <button
            type="button"
            className="btn primary"
            disabled={save.isPending}
            onClick={() => save.mutate(choiceBody(chosen), { onSuccess: () => navigate("/courses", { state: { newCourse: true } }) })}
          >
            {save.isPending ? "Saving…" : "Continue"}
          </button>
        </div>
      </div>
    </main>
  );
}
