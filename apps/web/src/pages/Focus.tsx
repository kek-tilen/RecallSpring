import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Link } from "react-router";
import { BACKGROUNDS, ClockFace, RoundDots, TimerText, useBackgroundImage, usePomodoro } from "../components/Pomodoro";
import { Async, Card, PageHead } from "../components/ui";
import { chime, imageProblem, loadImage, removeImage, saveImage } from "../focusMedia";
import { timeOnly, dayHeading } from "../format";
import { DEFAULT_SETTINGS, FACES, LIMITS, PHASE_LABEL, type PomodoroSettings } from "../pomodoro";
import { useCourses, useFocusSummary } from "../queries";
import type { FocusSummary } from "../types";

export function minutesText(m: number): string {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
const WEEKDAY_LONG = new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone: "UTC" });
const dayOf = (iso: string) => new Date(`${iso}T00:00:00Z`);

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(target.tagName))
  );
}

// ---------------------------------------------------------------- the timer

function Timer() {
  const p = usePomodoro();
  const courses = useCourses();
  const { run, settings, left } = p;
  const label = run.status === "running" ? "Pause" : run.status === "paused" ? "Resume" : "Start";
  const options = (courses.data ?? []).filter((c) => c.status !== "archived");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (p.focusMode || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      if (e.key === " ") {
        e.preventDefault();
        p.toggle();
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        p.setFocusMode(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p]);

  return (
    <Card title="Timer" meta={`Block ${Math.min(run.round, settings.rounds)} of ${settings.rounds}`}>
      <div className="stack timer-box" data-phase={run.phase}>
        <div className="phase-steps" aria-hidden="true">
          {(["focus", "short", "long"] as const).map((ph) => (
            <span key={ph} className={ph === run.phase ? "on" : undefined}>
              {PHASE_LABEL[ph]}
            </span>
          ))}
        </div>
        <p className="sr-only">Now: {PHASE_LABEL[run.phase]}</p>
        <div className="timer-face">
          <ClockFace face={settings.face} ms={left} total={run.totalMs} />
        </div>
        <TimerText ms={left} phase={run.phase} paused={run.status === "paused"} />
        <RoundDots run={run} rounds={settings.rounds} />
        <div className="row" style={{ justifyContent: "center" }}>
          <button type="button" className="btn primary timer-main" onClick={p.toggle}>
            {label}
          </button>
          <button type="button" className="btn" onClick={p.skip} title="End this phase and go to the next one">
            Skip
          </button>
          <button type="button" className="btn" onClick={p.reset} title="Back to focus block 1">
            Reset
          </button>
          <button type="button" className="btn" data-focus-mode-opener onClick={() => p.setFocusMode(true)}>
            Focus mode
          </button>
        </div>
        <label className="field">
          Course (optional)
          <span className="hint">Finished focus blocks count as study time for this course. Breaks are not counted.</span>
          <select value={run.courseId ?? ""} onChange={(e) => p.setCourse(e.target.value || null)}>
            <option value="">No course</option>
            {options.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
        {p.unsaved > 0 && (
          <p className="notice small" role="status">
            {p.unsaved === 1 ? "1 focus block is" : `${p.unsaved} focus blocks are`} kept in this browser until
            RecallSpring is reachable again.
          </p>
        )}
        <p className="tiny muted" style={{ margin: 0 }}>
          Space starts or pauses · F opens focus mode · a block stopped after at least a minute is saved as stopped early.
        </p>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- focus time

export function FocusTime({ s, compact = false }: { s: FocusSummary; compact?: boolean }) {
  const max = Math.max(1, ...s.days.map((d) => d.minutes));
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="stats">
        <div className="stat">
          <div className="n">{minutesText(s.today.minutes)}</div>
          <div className="l">
            today · {s.today.sessions} {s.today.sessions === 1 ? "block" : "blocks"}
          </div>
        </div>
        <div className="stat">
          <div className="n">{minutesText(s.week_minutes)}</div>
          <div className="l">last 7 days</div>
        </div>
      </div>
      <ul className="focus-days" aria-label="Focus time on each of the last 7 days">
        {s.days.map((d) => (
          <li key={d.date}>
            <span className="bar" style={{ height: `${Math.max(2, Math.round((d.minutes / max) * 64))}px` }} aria-hidden="true" />
            <span className="tiny muted" aria-hidden="true">
              {WEEKDAY.format(dayOf(d.date))}
            </span>
            <span className="sr-only">
              {WEEKDAY_LONG.format(dayOf(d.date))}: {minutesText(d.minutes)}
            </span>
          </li>
        ))}
      </ul>
      {!compact && s.by_course.length > 0 && (
        <ul className="list">
          {s.by_course.map((c) => (
            <li key={c.course_id ?? "none"} className="row" style={{ justifyContent: "space-between" }}>
              {c.course_id ? <Link to={`/courses/${c.course_id}`}>{c.course_title}</Link> : <span className="muted">No course</span>}
              <span className="small muted">
                {minutesText(c.minutes)} · {c.sessions} {c.sessions === 1 ? "block" : "blocks"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="tiny muted" style={{ margin: 0 }}>
        Time you timed yourself. It shows effort, not what you learned.
      </p>
    </div>
  );
}

function Recent({ s }: { s: FocusSummary }) {
  if (s.recent.length === 0) return <p className="muted small">Finished focus blocks appear here.</p>;
  return (
    <ul className="list">
      {s.recent.map((b) => (
        <li key={b.id} className="row" style={{ justifyContent: "space-between" }}>
          <span>
            <strong>{minutesText(b.minutes)}</strong>
            {!b.completed && <span className="chip warn" style={{ marginLeft: 8 }}>Stopped early</span>}
            <span className="small muted"> · {b.course_title ?? "No course"}</span>
          </span>
          <span className="small muted">
            {dayHeading(b.ended_at)}, {timeOnly(b.ended_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- settings

function NumberField({ label, hint, value, limits, onChange }: {
  label: string;
  hint?: string;
  value: number;
  limits: readonly [number, number];
  onChange: (n: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <label className="field">
      {label}
      {hint && <span className="hint">{hint}</span>}
      <input
        type="number"
        min={limits[0]}
        max={limits[1]}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value !== "" && Number.isInteger(n) && n >= limits[0] && n <= limits[1]) onChange(n);
        }}
        onBlur={() => setText(String(value))}
      />
    </label>
  );
}

function TimerSettings() {
  const p = usePomodoro();
  const s = p.settings;
  const set = (patch: Partial<PomodoroSettings>) => p.setSettings({ ...s, ...patch });
  const support = typeof Notification !== "undefined";
  const [permission, setPermission] = useState(support ? Notification.permission : "denied");

  async function toggleNotify(on: boolean) {
    if (on && support && Notification.permission === "default") {
      const answer = await Notification.requestPermission();
      setPermission(answer);
      set({ notify: answer === "granted" });
      return;
    }
    set({ notify: on && permission === "granted" });
  }

  const isDefault =
    s.focus === DEFAULT_SETTINGS.focus &&
    s.short === DEFAULT_SETTINGS.short &&
    s.long === DEFAULT_SETTINGS.long &&
    s.rounds === DEFAULT_SETTINGS.rounds;

  return (
    <Card title="Timer settings">
      <div className="stack">
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10 }}>
          <NumberField label="Focus (min)" value={s.focus} limits={LIMITS.focus} onChange={(n) => set({ focus: n })} />
          <NumberField label="Short break (min)" value={s.short} limits={LIMITS.short} onChange={(n) => set({ short: n })} />
          <NumberField label="Long break (min)" value={s.long} limits={LIMITS.long} onChange={(n) => set({ long: n })} />
          <NumberField label="Blocks per cycle" value={s.rounds} limits={LIMITS.rounds} onChange={(n) => set({ rounds: n })} />
        </div>
        <p className="tiny muted" style={{ margin: 0 }}>
          The long break comes after the last block of a cycle. New lengths apply from the next phase that has not
          started.{" "}
          {!isDefault && (
            <button
              type="button"
              className="link-button"
              onClick={() => set({ focus: DEFAULT_SETTINGS.focus, short: DEFAULT_SETTINGS.short, long: DEFAULT_SETTINGS.long, rounds: DEFAULT_SETTINGS.rounds })}
            >
              Back to 45 / 10 / 15, 4 blocks
            </button>
          )}
        </p>
        <label className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={s.autoStart} onChange={(e) => set({ autoStart: e.target.checked })} />
          Start the next phase automatically
        </label>
        <div className="row small" style={{ gap: 8 }}>
          <label className="row" style={{ gap: 8 }}>
            <input type="checkbox" checked={s.sound} onChange={(e) => set({ sound: e.target.checked })} />
            Play a chime when a phase ends
          </label>
          <button type="button" className="btn small ghost" onClick={() => chime("rest")}>
            Test
          </button>
        </div>
        <label className="row small" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={s.notify && permission === "granted"}
            disabled={!support || permission === "denied"}
            onChange={(e) => void toggleNotify(e.target.checked)}
          />
          Show a notification when a phase ends
        </label>
        {support && permission === "denied" && (
          <p className="tiny muted" style={{ margin: 0 }}>
            Notifications are blocked for RecallSpring in this browser. Allow them in the browser's site settings to
            use this.
          </p>
        )}
        <p className="tiny muted" style={{ margin: 0 }}>
          These settings are saved on this device.
        </p>
      </div>
    </Card>
  );
}

function FacePicker() {
  const p = usePomodoro();
  const total = p.settings.focus * 60_000;
  return (
    <Card title="Clock face">
      <div className="face-grid" role="radiogroup" aria-label="Clock face">
        {FACES.map((f) => (
          <button
            key={f.id}
            type="button"
            role="radio"
            aria-checked={p.settings.face === f.id}
            className="face-card"
            onClick={() => p.setSettings({ ...p.settings, face: f.id })}
          >
            <span className="face-sample">
              <ClockFace face={f.id} ms={total * 0.62} total={total} preview />
            </span>
            <span className="theme-name">{f.name}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

function BackgroundPicker() {
  const p = usePomodoro();
  const s = p.settings;
  const [version, setVersion] = useState(0);
  const [hasImage, setHasImage] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const image = useBackgroundImage(hasImage, version);

  useEffect(() => {
    void loadImage().then((b) => setHasImage(b !== null));
  }, [version]);

  async function choose(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const why = imageProblem(f);
    setProblem(why);
    if (why) return;
    try {
      await saveImage(f);
      setVersion((v) => v + 1);
      p.setSettings({ ...s, background: "image" });
    } catch {
      setProblem("This browser could not keep the image (private window or storage full).");
    }
  }

  async function remove() {
    await removeImage();
    setVersion((v) => v + 1);
    if (s.background === "image") p.setSettings({ ...s, background: "theme" });
  }

  return (
    <Card title="Focus mode background">
      <div className="stack">
        <div className="bg-grid" role="radiogroup" aria-label="Focus mode background">
          {BACKGROUNDS.filter((b) => b.id !== "image" || hasImage).map((b) => (
            <button
              key={b.id}
              type="button"
              role="radio"
              aria-checked={s.background === b.id}
              className="bg-card"
              onClick={() => p.setSettings({ ...s, background: b.id })}
            >
              <span className="bg-sample" style={{ background: b.css }} aria-hidden="true">
                {b.id === "image" && image && <img src={image} alt="" />}
              </span>
              <span className="small">{b.name}</span>
            </button>
          ))}
        </div>
        <div className="row">
          <button type="button" className="btn small" onClick={() => file.current?.click()}>
            {hasImage ? "Choose another image…" : "Choose an image…"}
          </button>
          {hasImage && (
            <button type="button" className="btn small ghost" onClick={() => void remove()}>
              Remove my image
            </button>
          )}
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(e) => void choose(e)} />
        </div>
        {problem && (
          <p className="small" role="alert" style={{ color: "var(--danger)", margin: 0 }}>
            {problem}
          </p>
        )}
        {s.background === "image" && (
          <label className="field">
            Darken the image: {s.dim}%
            <span className="hint">So the timer stays easy to read.</span>
            <input type="range" min={LIMITS.dim[0]} max={LIMITS.dim[1]} step={5} value={s.dim} onChange={(e) => p.setSettings({ ...s, dim: Number(e.target.value) })} />
          </label>
        )}
        <p className="tiny muted" style={{ margin: 0 }}>
          Your image stays in this browser. It is not uploaded to RecallSpring and is not in backups.
        </p>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- page

export function FocusPage() {
  const summary = useFocusSummary();
  return (
    <div className="page">
      <PageHead
        title="Focus"
        sub="A Pomodoro timer: focus blocks with short breaks, and a long break after each cycle. The timer keeps running while you use other pages."
      />
      <div className="split">
        <div className="stack" style={{ gap: 20 }}>
          <Timer />
          <FacePicker />
          <BackgroundPicker />
        </div>
        <div className="stack" style={{ gap: 20 }}>
          <Card title="Focus time">
            <Async q={summary}>{(s) => <FocusTime s={s} />}</Async>
          </Card>
          <TimerSettings />
          <Card title="Latest blocks">
            <Async q={summary}>{(s) => <Recent s={s} />}</Async>
          </Card>
        </div>
      </div>
    </div>
  );
}
