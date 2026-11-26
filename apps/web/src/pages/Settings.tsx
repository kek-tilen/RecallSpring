import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AssistantNextSteps, TimeZoneSelect, useSaveProfile } from "./Welcome";
import { greeting } from "./Home";
import { ASSISTANTS } from "../assistant";
import { request } from "../api";
import { Async, Card, Confirm, ErrorNote, PageHead } from "../components/ui";
import { Link } from "react-router";
import { bytes, dateLabel, dateTime, plural } from "../format";
import { keys, useAssistants, useBackup, useConnector, useSession, useStudySettings } from "../queries";
import { PreferencesEditor } from "./Import";
import { ChatGptPanel } from "../components/ChatGpt";
import { ExplanationPaceDefault } from "../components/ExplanationPace";
import { ServiceStatus } from "../components/ServiceStatus";
import { readTheme, saveTheme, THEMES, type ThemeId } from "../theme";
import type { AssistantClient, AssistantKey, AssistantsStatus, BackupStatus, ConnectorSettings, ConnectorToken, StudySettings } from "../types";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function StudyForm({ initial }: { initial: StudySettings }) {
  const qc = useQueryClient();
  const [minutes, setMinutes] = useState(initial.weekly_minutes);
  const [maintenance, setMaintenance] = useState(initial.maintenance_percent);
  const [style, setStyle] = useState(initial.style_percent);
  const [interest, setInterest] = useState(initial.interest_percent);
  const save = useMutation({
    mutationFn: () =>
      request<StudySettings>("/settings/study", {
        method: "PUT",
        json: { weekly_minutes: minutes, maintenance_percent: maintenance, style_percent: style, interest_percent: interest },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.studySettings });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
  const dirty =
    minutes.join() !== initial.weekly_minutes.join() ||
    maintenance !== initial.maintenance_percent ||
    style !== initial.style_percent ||
    interest !== initial.interest_percent;

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <form className="stack" onSubmit={submit}>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="small" style={{ fontWeight: 600, marginBottom: 8 }}>
          Minutes per day
        </legend>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(84px, 1fr))", gap: 8 }}>
          {DAYS.map((d, i) => (
            <label key={d} className="field">
              {d}
              <input
                type="number"
                min={0}
                max={720}
                step={5}
                value={minutes[i]}
                onChange={(e) => setMinutes(minutes.map((m, j) => (j === i ? Math.max(0, Math.min(720, Number(e.target.value) || 0)) : m)))}
              />
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field">
        Maintenance share: {maintenance}%
        <span className="hint">Time kept for material of a passed midterm so it is not forgotten.</span>
        <input type="range" min={0} max={50} value={maintenance} onChange={(e) => setMaintenance(Number(e.target.value))} />
      </label>
      <label className="field">
        Past-paper style: {style}%
        <span className="hint">Share of simulation questions in the style of your old papers; the rest go deeper.</span>
        <input type="range" min={0} max={100} step={5} value={style} onChange={(e) => setStyle(Number(e.target.value))} />
      </label>
      <label className="field">
        Interests: {interest === 0 ? "university first" : `${interest}% of each day`}
        <span className="hint">
          {interest === 0
            ? "Your interests get only the time left after today's course work, and only while every exam is on track."
            : "This share of each day is kept for your interests, even when an exam is tight; exam checks count only the rest."}
        </span>
        <input
          type="range"
          min={0}
          max={50}
          step={5}
          value={interest}
          aria-valuetext={interest === 0 ? "University first" : `${interest} percent`}
          onChange={(e) => setInterest(Number(e.target.value))}
        />
      </label>
      {initial.focus && (
        <div className="notice small">
          Focus: <strong>{initial.focus.course_title}</strong> comes first until {dateLabel(initial.focus.until)}.{" "}
          <Link to={`/courses/${initial.focus.course_id}`}>Open it to end the focus.</Link>
        </div>
      )}
      {save.error && <ErrorNote error={save.error} />}
      <div className="row">
        <button type="submit" className="btn primary" disabled={!dirty || save.isPending}>
          Save study settings
        </button>
        {save.isSuccess && !dirty && <span className="small muted">Saved.</span>}
      </div>
    </form>
  );
}

const ASSISTANT: Record<AssistantClient, string> = { claude: "Claude Desktop", codex: "Codex", antigravity: "Antigravity" };

/** One token as a compact row (no wide table): name and assistant, dates below, Revoke on the right. */
function TokenRow({ t, onRevoke }: { t: ConnectorToken; onRevoke: (t: ConnectorToken) => void }) {
  const assistant = ASSISTANT[t.client] ?? t.client;
  return (
    <li className="token-item">
      <div className="token-main">
        <div className="row" style={{ gap: 8 }}>
          <strong>{t.label}</strong>
          {t.label !== assistant && <span className="chip">{assistant}</span>}
        </div>
        <span className="tiny muted">
          Created {dateTime(t.created_at)} · Last used {t.last_used_at ? dateTime(t.last_used_at) : "never"}
        </span>
      </div>
      {t.revoked_at ? (
        <span className="chip">Revoked {dateTime(t.revoked_at)}</span>
      ) : (
        <button type="button" className="btn small danger" onClick={() => onRevoke(t)} aria-label={`Revoke ${t.label} (${assistant})`}>
          Revoke
        </button>
      )}
    </li>
  );
}

function ConnectorPanel({ c }: { c: ConnectorSettings }) {
  const qc = useQueryClient();
  const [percent, setPercent] = useState(c.limit_percent);
  const [revoking, setRevoking] = useState<ConnectorToken | null>(null);
  const [shown, setShown] = useState<{ token: string; client: AssistantClient } | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => setPercent(c.limit_percent), [c.limit_percent]);
  const refresh = () => void qc.invalidateQueries({ queryKey: keys.connector });

  const limit = useMutation({
    mutationFn: () => request<ConnectorSettings>("/settings/connector", { method: "PUT", json: { limit_percent: percent } }),
    onSuccess: refresh,
  });
  const create = useMutation({
    mutationFn: (client: AssistantClient) => request<ConnectorToken & { token: string | null }>("/settings/connector/tokens", { json: { client } }),
    onSuccess: (t) => {
      setShown(t.token ? { token: t.token, client: t.client } : null);
      setCopied(false);
      refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: (t: ConnectorToken) => request<ConnectorToken>(`/settings/connector/tokens/${t.id}/revoke`, { method: "POST", json: {} }),
    onSuccess: () => {
      setRevoking(null);
      refresh();
    },
  });
  const projected = Math.max(1, Math.round((c.daily_default * percent) / 100));

  return (
    <div className="stack" style={{ gap: 18 }}>
      <p className="small">
        Claude Desktop, Codex or Antigravity uses RecallSpring through the connector, on your own Claude, ChatGPT or Google plan. RecallSpring never sees
        those sign-ins. Each assistant has its own token, and its grades are labelled with its name. Requests today: <strong>{c.used_today}</strong> of <strong>{c.daily_limit}</strong>.
      </p>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          limit.mutate();
        }}
      >
        <label className="field">
          Daily request limit: {percent}% ({projected} requests)
          <span className="hint">Caps how many connector calls your assistants can make per day together, to protect your plan's usage.</span>
          <input type="range" min={1} max={100} value={percent} onChange={(e) => setPercent(Number(e.target.value))} />
        </label>
        {limit.error && <ErrorNote error={limit.error} />}
        <div>
          <button type="submit" className="btn" disabled={percent === c.limit_percent || limit.isPending}>
            Save limit
          </button>
        </div>
      </form>
      <hr className="soft" />
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>Connector tokens</h3>
        <div className="row">
          <button type="button" className="btn small" onClick={() => create.mutate("claude")} disabled={create.isPending}>
            New token for Claude Desktop
          </button>
          <button type="button" className="btn small" onClick={() => create.mutate("codex")} disabled={create.isPending}>
            New token for Codex
          </button>
          <button type="button" className="btn small" onClick={() => create.mutate("antigravity")} disabled={create.isPending}>
            New token for Antigravity
          </button>
        </div>
      </div>
      {create.error && <ErrorNote error={create.error} />}
      {shown && (
        <div className="notice warn stack" role="status">
          <strong>Copy this token now. It is shown only once.</strong>
          <div className="token-box">{shown.token}</div>
          <div className="row">
            <button
              type="button"
              className="btn small"
              onClick={() => {
                void navigator.clipboard.writeText(shown.token).then(() => setCopied(true));
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button type="button" className="btn small ghost" onClick={() => setShown(null)}>
              Hide
            </button>
          </div>
          <span className="tiny">
            {shown.client === "codex"
              ? "Usually you do not need this: scripts/install-codex-connector.ps1 creates its own Codex token; see docs/codex-setup.md."
              : shown.client === "antigravity"
                ? "Usually you do not need this: scripts/install-antigravity-connector.ps1 creates its own token; see docs/antigravity-setup.md."
                : "The installer script writes it to the connector's token file for you; see docs/connector-setup.md."}{" "}
            Never paste it into a chat.
          </span>
        </div>
      )}
      {c.tokens.length > 0 ? (
        <ul className="token-list" aria-label="Connector tokens">
          {c.tokens.map((t) => (
            <TokenRow key={t.id} t={t} onRevoke={setRevoking} />
          ))}
        </ul>
      ) : (
        <p className="small muted">No tokens yet.</p>
      )}
      <Confirm
        open={revoking !== null}
        title="Revoke connector token?"
        confirmLabel="Revoke token"
        danger
        busy={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
        onClose={() => setRevoking(null)}
      >
        {revoking ? ASSISTANT[revoking.client] : "The assistant"} using “{revoking?.label}” loses access to RecallSpring immediately. Your study records stay as they are. This
        cannot be undone; create a new token to reconnect.
        {revoke.error && <ErrorNote error={revoke.error} />}
      </Confirm>
    </div>
  );
}

const CHECK_LABEL: Record<NonNullable<BackupStatus["last"]>["check"], string> = {
  restored: "Restored into a test database; every table matched",
  listed: "Dump read back (no permission for a test restore)",
  none: "Not checked (turned off in the server settings)",
};

function BackupPanel({ b }: { b: BackupStatus }) {
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => request<BackupStatus>("/settings/backup", { method: "POST", json: {} }),
    onSuccess: (v) => {
      qc.setQueryData(keys.backup, v);
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
    onError: () => {
      void qc.invalidateQueries({ queryKey: keys.backup });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
  const last = b.last;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <p className="small">
        A copy of your study records and uploaded files.{" "}
        {b.enabled
          ? `RecallSpring makes one every ${b.interval_hours} hours while it runs and keeps the newest of each of the last ${b.keep_daily} days and ${b.keep_weekly} weeks.`
          : "Automatic backups are turned off in the server settings; you can still back up here."}
      </p>
      {b.last_error && (
        <div className="notice bad" role="alert">
          <strong>The last backup failed{b.last_error.at ? ` (${dateTime(b.last_error.at)})` : ""}.</strong> {b.last_error.message}
        </div>
      )}
      {!b.tools && (
        <div className="notice bad" role="alert">
          pg_dump was not found, so no backup can be made. Install the PostgreSQL client tools or set RS_BACKUP_PG_BIN (docs/08 → Backups).
        </div>
      )}
      <dl className="kv">
        <dt>Last backup</dt>
        <dd>{b.last_success_at ? dateTime(b.last_success_at) : "Never"}</dd>
        {last && (
          <>
            <dt>Records</dt>
            <dd>
              {plural(last.rows, "row")} in {plural(last.tables, "table")} ({bytes(last.dump_bytes)})
            </dd>
            <dt>Uploaded files</dt>
            <dd>
              {plural(last.files, "file")} ({bytes(last.files_bytes)})
              {last.files_missing > 0 && <span className="chip warn"> {last.files_missing} missing from storage</span>}
            </dd>
            <dt>Check</dt>
            <dd>{CHECK_LABEL[last.check]}</dd>
          </>
        )}
        <dt>Next</dt>
        <dd>
          {!b.enabled ? "Only when you back up here" : b.next_due === "now" || !b.next_due ? "As soon as the RecallSpring worker runs" : dateTime(b.next_due)}
        </dd>
        <dt>Kept</dt>
        <dd>
          {plural(b.snapshots.length, "backup")}, {bytes(b.disk_bytes)}
        </dd>
        <dt>Folder</dt>
        <dd className="tiny" style={{ wordBreak: "break-all" }}>
          {b.location}
        </dd>
      </dl>
      {b.same_disk_as_storage && (
        <div className="notice warn small">
          Backups are on the same disk as RecallSpring. They protect against mistakes and a damaged database, not against a broken
          disk or a lost computer. Set RS_BACKUP_DIR to another disk or a synced folder, or copy this folder elsewhere now and then.
        </div>
      )}
      {run.error && <ErrorNote error={run.error} />}
      {run.isSuccess && !run.isPending && (
        <div className="notice small" role="status">
          Backed up and checked.
        </div>
      )}
      <div>
        <button type="button" className="btn" onClick={() => run.mutate()} disabled={run.isPending || !b.tools}>
          {run.isPending ? "Backing up…" : "Back up now"}
        </button>
      </div>
      <p className="tiny muted">
        Restoring never overwrites anything: <code>recallspring backup-restore --database &lt;new name&gt;</code> creates a new database
        from a backup, then you choose to switch (docs/08 → Backups).
      </p>
    </div>
  );
}

function ThemePicker() {
  const [theme, setTheme] = useState<ThemeId>(readTheme);
  function pick(t: ThemeId) {
    setTheme(t);
    saveTheme(t);
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="theme-grid" role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} className="theme-card" onClick={() => pick(t.id)}>
            <span className="theme-swatch" aria-hidden="true" style={{ background: t.swatch[0], borderColor: t.swatch[1] }}>
              <span style={{ background: t.swatch[1] }} />
              <span style={{ background: t.swatch[2] }} />
              <span style={{ background: t.swatch[3] }} />
              <span style={{ background: t.swatch[4] }} />
            </span>
            <span className="theme-name">{t.name}</span>
            <span className="tiny muted">
              {t.dark ? "Dark" : "Light"} · {t.note}
            </span>
          </button>
        ))}
      </div>
      <label className="row small" style={{ gap: 8 }}>
        <input type="checkbox" checked={theme === "system"} onChange={(e) => pick(e.target.checked ? "system" : "light")} />
        Match my computer (RecallSpring White or RecallSpring Dark)
      </label>
      <p className="tiny muted" style={{ margin: 0 }}>
        Saved on this device. Solarized, Nord, Dracula and Gruvbox are open-source colour schemes, adapted so text stays
        easy to read.
      </p>
    </div>
  );
}

const STUDY_IN: Record<AssistantKey, string> = {
  claude: "Claude Desktop, through the connector",
  codex: "Codex (app, CLI or IDE extension), through the connector",
  antigravity: "Google Antigravity (app or CLI), through the connector",
  chatgpt: "RecallSpring's Chat, signed in with ChatGPT (preview)",
};

/** Which assistants are connected, from RecallSpring's own records (tokens, ChatGPT sign-in), with the next step. */
export function AssistantsPanel({ s }: { s: AssistantsStatus }) {
  const label = (key: AssistantKey) => ASSISTANTS.find((a) => a.key === key)?.label ?? key;
  const connected = s.items.filter((i) => i.connected);
  const username = useSession().data?.user.username ?? "";
  const [steps, setSteps] = useState<AssistantKey | null>(null);
  const mix = s.mix ?? [];
  return (
    <div className="stack" style={{ gap: 12 }}>
      <ul className="list assistants-list">
        {s.items.map((i) => (
          <li key={i.key} className="row" style={{ justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <strong>{label(i.key)}</strong>
                <span className={i.connected ? "chip good" : "chip"}>{i.connected ? "Connected" : "Not connected"}</span>
                {i.in_mix && <span className="chip">In your mix</span>}
              </div>
              <div className="small muted">
                {STUDY_IN[i.key]}
                {i.last_used_at ? ` · last used ${dateTime(i.last_used_at)}` : i.connected ? " · not used yet" : ""}
                {i.tokens > 1 ? ` · ${i.tokens} tokens` : ""}
              </div>
            </div>
            <div className="row" style={{ gap: 6, flexShrink: 0 }}>
              {i.key === "chatgpt" ? (
                i.connected ? (
                  <Link className="btn small" to="/chat">
                    Open Chat
                  </Link>
                ) : (
                  <a className="btn small" href="#chatgpt">
                    Sign in
                  </a>
                )
              ) : i.connected ? (
                <a className="btn small" href="#connector" aria-label={`Manage the ${label(i.key)} token`}>
                  Manage
                </a>
              ) : (
                <button
                  type="button"
                  className="btn small"
                  aria-expanded={steps === i.key}
                  aria-label={`Set up ${label(i.key)}`}
                  onClick={() => setSteps(steps === i.key ? null : i.key)}
                >
                  {steps === i.key ? "Hide steps" : "Set up"}
                </button>
              )}
            </div>
            {steps === i.key && !i.connected && i.key !== "chatgpt" && (
              <div className="assistant-steps">
                <AssistantNextSteps assistant={i.key} username={username} />
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="hint small muted" style={{ margin: 0 }}>
        {connected.length > 1
          ? `${connected.map((i) => label(i.key)).join(" and ")} are connected, so RecallSpring says “your assistant”. `
          : connected.length === 1
            ? `RecallSpring names ${label(connected[0]!.key)} in its tips. `
            : s.chosen === "mix"
              ? `Nothing is connected yet; your mix is ${mix.map(label).join(" and ")}, so tips say “your assistant”. `
              : s.chosen
                ? `Nothing is connected yet; tips follow your choice on the welcome page (${label(s.chosen)}). `
                : "Nothing is connected yet. "}
        Every connected assistant works at the same time, and grades are labelled with the one that gave them.{" "}
        <Link to="/welcome">Change your choice</Link>
      </p>
    </div>
  );
}

/** Username, session, what Home calls you and time zone. */
function ProfileForm() {
  const qc = useQueryClient();
  const session = useSession();
  const user = session.data?.user;
  const [timezone, setTimezone] = useState(user?.timezone ?? "UTC");
  const [name, setName] = useState(user?.greeting_name ?? "");
  const [saved, setSaved] = useState(false);
  const save = useSaveProfile();
  if (!user) return null;
  const nameChanged = name.trim() !== (user.greeting_name ?? "");
  const changed = timezone !== user.timezone || nameChanged;
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(
      { timezone, greeting_name: name.trim() || null },
      {
        onSuccess: () => {
          setSaved(true);
          // "Today", plans and due dates are computed in the time zone.
          void qc.invalidateQueries();
        },
      },
    );
  }
  return (
    <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
      <dl className="kv">
        <dt>Username</dt>
        <dd>{user.username}</dd>
        <dt>Session ends</dt>
        <dd>{session.data ? dateTime(session.data.expires_at) : ""}</dd>
      </dl>
      <label className="field">
        What should Home call you?
        <input
          type="text"
          value={name}
          maxLength={40}
          autoComplete="nickname"
          placeholder="No name"
          onChange={(e) => {
            setName(e.target.value);
            setSaved(false);
          }}
        />
        <span className="hint">
          {name.trim() ? "" : "Empty: "}Home says “{greeting(new Date().getHours(), name)}”.
        </span>
      </label>
      <label className="field">
        Time zone
        <TimeZoneSelect
          value={timezone}
          onChange={(z) => {
            setTimezone(z);
            setSaved(false);
          }}
        />
        <span className="hint">“Today”, plans, reviews and dates use it.</span>
      </label>
      {save.error && <ErrorNote error={save.error} />}
      <div className="row">
        <button type="submit" className="btn primary" disabled={!changed || save.isPending}>
          {save.isPending ? "Saving…" : "Save profile"}
        </button>
        {saved && !changed && (
          <span className="small muted" role="status">
            Saved.
          </span>
        )}
      </div>
    </form>
  );
}

/** The five parts of Settings, in page order (the contents beside the page link to them). */
export const SECTIONS = [
  { id: "study", title: "Study", sub: "How much you study and how RecallSpring plans your time." },
  { id: "assistants", title: "Assistants", sub: "Who helps you: Claude Desktop, Codex, Antigravity and ChatGPT." },
  { id: "data", title: "Data & backups", sub: "Where your data is kept and how you get it back." },
  { id: "appearance", title: "Appearance", sub: "How RecallSpring looks on this device." },
  { id: "account", title: "Account & system", sub: "Your sign-in, time zone and RecallSpring running in the background." },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

/** The section being read: the last one whose heading has passed the upper part of the window. */
function useCurrentSection(): SectionId {
  const [current, setCurrent] = useState<SectionId>("study");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const seen = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting);
        const visible = SECTIONS.find((x) => seen.get(x.id));
        if (visible) setCurrent(visible.id);
      },
      { rootMargin: "-15% 0px -55% 0px" },
    );
    for (const x of SECTIONS) {
      const el = document.getElementById(x.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);
  return current;
}

function Section({ id, children }: { id: SectionId; children: ReactNode }) {
  const s = SECTIONS.find((x) => x.id === id)!;
  return (
    <section id={id} className="settings-section" aria-labelledby={`${id}-title`}>
      <div className="settings-section-head">
        <h2 id={`${id}-title`}>{s.title}</h2>
        <p className="small muted">{s.sub}</p>
      </div>
      {children}
    </section>
  );
}

export function SettingsPage() {
  const study = useStudySettings();
  const connector = useConnector();
  const assistants = useAssistants();
  const backup = useBackup();
  const current = useCurrentSection();
  useEffect(() => {
    // Links like /settings#chatgpt (Welcome page) open at that section or card.
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView?.({ block: "start" });
  }, []);
  return (
    <div className="page">
      <PageHead title="Settings" sub="Every change is recorded in History." />
      <div className="settings-layout">
        <nav className="settings-toc" aria-label="Settings sections">
          <ol>
            {SECTIONS.map((x) => (
              <li key={x.id}>
                <a href={`#${x.id}`} aria-current={current === x.id ? "true" : undefined}>
                  {x.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="settings-body">
          <Section id="study">
            <div className="grid cols-2" style={{ alignItems: "start" }}>
              <Card title="Study time" level={3}>
                <Async q={study}>{(s) => <StudyForm initial={s} />}</Async>
              </Card>
              <Card title="Study preferences" level={3}>
                <PreferencesEditor />
              </Card>
              <Card title="Explanation pace" id="pace" level={3}>
                <ExplanationPaceDefault />
              </Card>
            </div>
          </Section>
          <Section id="assistants">
            <Card title="Your assistants" level={3}>
              <Async q={assistants}>{(s) => <AssistantsPanel s={s} />}</Async>
            </Card>
            <div className="grid cols-2" style={{ alignItems: "start" }}>
              <Card title="ChatGPT (preview)" id="chatgpt" level={3}>
                <ChatGptPanel />
              </Card>
              <Card title="Assistant connector" id="connector" level={3}>
                <Async q={connector}>{(c) => <ConnectorPanel c={c} />}</Async>
              </Card>
            </div>
          </Section>
          <Section id="data">
            <div className="grid cols-2" style={{ alignItems: "start" }}>
              <Card title="Backups" id="backups" level={3}>
                <Async q={backup}>{(b) => <BackupPanel b={b} />}</Async>
              </Card>
              <Card title="History" level={3}>
                <p className="small">
                  Every change you or an assistant makes is recorded, with who made it and when. Deleted items stay
                  restorable for 30 days.
                </p>
                <p className="small" style={{ marginTop: 8 }}>
                  <Link to="/history">Open History</Link>
                </p>
              </Card>
            </div>
          </Section>
          <Section id="appearance">
            <Card title="Theme" level={3}>
              <ThemePicker />
            </Card>
          </Section>
          <Section id="account">
            <div className="grid cols-2" style={{ alignItems: "start" }}>
              <Card title="Profile" id="profile" level={3}>
                <ProfileForm />
              </Card>
              <Card title="Running in the background" id="service" level={3}>
                <ServiceStatus />
              </Card>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
