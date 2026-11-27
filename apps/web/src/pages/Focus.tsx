import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ChangeEvent } from "react";
import { request } from "../api";
import { Link } from "react-router";
import { BACKGROUNDS, ClockFace, FocusStage, RoundDots, TimerText, useBackgroundImage, usePomodoro } from "../components/Pomodoro";
import { Async, Confirm, ErrorNote, PageHead } from "../components/ui";
import { CourseDot } from "../components/organise";
import { IMAGE_CHANGED, chime, imageProblem, loadImage, removeImage, saveImage } from "../focusMedia";
import { timeOnly, dayHeading } from "../format";
import { DEFAULT_SETTINGS, FACES, LIMITS, PHASE_LABEL, type PomodoroSettings } from "../pomodoro";
import { keys, useCourses, useFocusSummary } from "../queries";
import type { FocusBlock, FocusSummary } from "../types";

export function minutesText(m: number): string {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
const WEEKDAY_LONG = new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone: "UTC" });
const DAY_TIP = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
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
  const course = options.find((c) => c.id === run.courseId);
  const length = run.phase === "focus" ? settings.focus : run.phase === "short" ? settings.short : settings.long;

  /** Start and Resume put the timer over the whole window; Pause stays here. */
  function startOrPause() {
    const starting = p.run.status !== "running";
    p.toggle();
    if (starting) p.setFocusMode(true);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (p.focusMode || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      if (e.key === " ") {
        e.preventDefault();
        startOrPause();
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        p.setFocusMode(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p]);

  return (
    <section className="stack timer-box focus-timer" data-phase={run.phase} aria-label="Timer">
      <p className="small muted focus-line">
        {course && <CourseDot color={course.color} />}
        {course ? course.title : "No course"} · block {Math.min(run.round, settings.rounds)} of {settings.rounds} · {PHASE_LABEL[run.phase].toLowerCase()}{" "}
        {length} min
      </p>
      <FocusStage settings={settings} className="timer-stage">
        <p className="sr-only">Now: {PHASE_LABEL[run.phase]}</p>
        <div className="timer-face">
          <ClockFace face={settings.face} ms={left} total={run.totalMs} />
        </div>
        <TimerText ms={left} phase={run.phase} paused={run.status === "paused"} />
        <RoundDots run={run} rounds={settings.rounds} />
      </FocusStage>
      <div className="row" style={{ justifyContent: "center" }}>
        <button type="button" className="btn primary timer-main" onClick={startOrPause}>
          {label}
        </button>
        <button type="button" className="btn" onClick={p.skip} title="End this phase and go to the next one">
          Skip
        </button>
        <button type="button" className="btn" data-focus-mode-opener onClick={() => p.setFocusMode(true)}>
          Focus mode
        </button>
        <button type="button" className="btn ghost" onClick={p.reset} title="Back to focus block 1">
          Reset
        </button>
      </div>
      <label className="field focus-course-field">
        <span className="small">Course</span>
        <select value={run.courseId ?? ""} onChange={(e) => p.setCourse(e.target.value || null)} aria-describedby="focus-course-hint">
          <option value="">No course</option>
          {options.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <span className="hint" id="focus-course-hint">
          Finished focus blocks count as study time for this course. Breaks are not counted.
        </span>
      </label>
      {p.unsaved > 0 && (
        <p className="notice small" role="status">
          {p.unsaved === 1 ? "1 focus block is" : `${p.unsaved} focus blocks are`} kept in this browser until
          RecallSpring is reachable again.
        </p>
      )}
      <p className="tiny muted" style={{ margin: 0, textAlign: "center" }}>
        Space starts or pauses · F opens focus mode · a block stopped after at least a minute is saved as stopped early.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- focus time

export function FocusTime({ s, compact = false }: { s: FocusSummary; compact?: boolean }) {
  const max = Math.max(1, ...s.days.map((d) => d.minutes));
  const courses = useCourses();
  const colors = new Map((courses.data ?? []).map((c) => [c.id, c.color]));
  return (
    <section className="stack focus-week" style={{ gap: 6 }} aria-labelledby="focus-week-h">
      <div className="focus-week-head">
        <h2 id="focus-week-h">Focus time, last 7 days</h2>
        <span>{minutesText(s.week_minutes)}</span>
      </div>
      <ul className="focus-days slim" aria-label="Focus time on each of the last 7 days">
        {s.days.map((d) => (
          // Hover, or focus with Tab, shows the day's time; screen readers get the same from the hidden text.
          <li key={d.date} tabIndex={0} className={d.date === s.today.date ? "today" : undefined}>
            <span className="focus-tip" aria-hidden="true">
              <strong>{d.date === s.today.date ? "Today" : DAY_TIP.format(dayOf(d.date))}</strong>
              <span>
                {minutesText(d.minutes)}
                {d.sessions > 0 && ` · ${d.sessions} ${d.sessions === 1 ? "block" : "blocks"}`}
              </span>
            </span>
            <span
              className={d.minutes > 0 ? "bar" : "bar none"}
              style={{ height: `${Math.max(2, Math.round((d.minutes / max) * 40))}px` }}
              aria-hidden="true"
            />
            <span className="tiny" aria-hidden="true">
              {WEEKDAY.format(dayOf(d.date)).slice(0, 2)}
            </span>
            <span className="sr-only">
              {WEEKDAY_LONG.format(dayOf(d.date))}: {minutesText(d.minutes)}
            </span>
          </li>
        ))}
      </ul>
      <p className="tiny muted" style={{ margin: 0 }}>
        Today {minutesText(s.today.minutes)} · {s.today.sessions} {s.today.sessions === 1 ? "block" : "blocks"}
      </p>
      {!compact && s.by_course.length > 0 && (
        <ul className="source-rows" aria-label="Focus time by course">
          {s.by_course.map((c) => (
            <li key={c.course_id ?? "none"} className="source-row">
              <span className="focus-course-name">
                {c.course_id ? (
                  <>
                    <CourseDot color={colors.get(c.course_id)} />
                    <Link to={`/courses/${c.course_id}`}>{c.course_title}</Link>
                  </>
                ) : (
                  <span className="muted">No course</span>
                )}
              </span>
              <span className="small" title={`${c.sessions} ${c.sessions === 1 ? "block" : "blocks"}`}>
                {minutesText(c.minutes)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="tiny muted" style={{ margin: 0 }}>
        Finished focus blocks only; breaks are not counted. It shows effort, not what you learned.
      </p>
    </section>
  );
}

function blockLine(b: FocusBlock): string {
  return `${minutesText(b.minutes)} · ${b.course_title ?? "No course"} · ${dayHeading(b.ended_at)}, ${timeOnly(b.ended_at)}`;
}

/** The latest blocks. A wrongly timed one can be removed after confirming, and restored for 30 days. */
export function Recent({ s }: { s: FocusSummary }) {
  const qc = useQueryClient();
  const courses = useCourses();
  const [asked, setAsked] = useState<FocusBlock | null>(null);
  const done = (next: FocusSummary) => {
    qc.setQueryData(keys.focusSummary, next);
    void qc.invalidateQueries({ queryKey: keys.history });
    void qc.invalidateQueries({ queryKey: keys.dashboard });
  };
  const remove = useMutation({
    mutationFn: (id: string) => request<FocusSummary>(`/focus-sessions/${id}`, { method: "DELETE" }),
    onSuccess: (next) => {
      done(next);
      setAsked(null);
    },
  });
  const setCourse = useMutation({
    mutationFn: ({ id, courseId }: { id: string; courseId: string | null }) =>
      request<FocusSummary>(`/focus-sessions/${id}`, { method: "PATCH", json: { course_id: courseId } }),
    onSuccess: done,
  });
  const restore = useMutation({
    mutationFn: (id: string) => request<FocusSummary>(`/focus-sessions/${id}/restore`, { method: "POST" }),
    onSuccess: done,
  });

  return (
    <div className="stack" style={{ gap: 14 }}>
      {s.recent.length === 0 ? (
        <p className="muted small" style={{ margin: 0 }}>
          Finished focus blocks appear here.
        </p>
      ) : (
        <ul className="list">
          {s.recent.map((b) => (
            <li key={b.id} className="focus-block">
              <span>
                <strong>{minutesText(b.minutes)}</strong>
                {!b.completed && <span className="chip warn" style={{ marginLeft: 8 }}>Stopped early</span>}
                <span className="small muted"> · </span>
                <select
                  className="focus-course small"
                  value={b.course_id ?? ""}
                  disabled={setCourse.isPending || !courses.data}
                  aria-label={`Course for the block: ${blockLine(b)}`}
                  title="Change the course this block counts for"
                  onChange={(e) => setCourse.mutate({ id: b.id, courseId: e.target.value || null })}
                >
                  <option value="">No course</option>
                  {b.course_id && !courses.data?.some((c) => c.id === b.course_id) && (
                    <option value={b.course_id}>{b.course_title ?? "Course"}</option>
                  )}
                  {(courses.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </select>
                <span className="tiny muted" style={{ display: "block" }}>
                  {dayHeading(b.ended_at)}, {timeOnly(b.ended_at)}
                </span>
              </span>
              <button
                type="button"
                className="btn small ghost"
                aria-label={`Remove focus block: ${blockLine(b)}`}
                onClick={() => {
                  remove.reset();
                  setAsked(b);
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {setCourse.error && <ErrorNote error={setCourse.error} />}
      {s.removed.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <h3 className="small" style={{ margin: 0 }}>
            Recently removed
          </h3>
          <ul className="list">
            {s.removed.map((b) => (
              <li key={b.id} className="focus-block">
                <span className="small muted">
                  <s>{minutesText(b.minutes)}</s> · {b.course_title ?? "No course"}
                  <span className="tiny" style={{ display: "block" }}>
                    {dayHeading(b.ended_at)}, {timeOnly(b.ended_at)} · removed {dayHeading(b.deleted_at!).toLowerCase()}
                  </span>
                </span>
                <button
                  type="button"
                  className="btn small"
                  disabled={restore.isPending}
                  aria-label={`Restore focus block: ${blockLine(b)}`}
                  onClick={() => restore.mutate(b.id)}
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
          <p className="tiny muted" style={{ margin: 0 }}>
            Removed blocks do not count as focus time. You can restore them for {s.restore_days} days.
          </p>
          {restore.error && <ErrorNote error={restore.error} />}
        </div>
      )}

      <Confirm
        open={asked !== null}
        title="Remove this focus block?"
        confirmLabel="Remove"
        danger
        busy={remove.isPending}
        onConfirm={() => asked && remove.mutate(asked.id)}
        onClose={() => setAsked(null)}
      >
        {asked && (
          <div className="stack" style={{ gap: 8 }}>
            <p style={{ margin: 0 }}>
              <strong>{blockLine(asked)}</strong>
            </p>
            <p style={{ margin: 0 }}>
              It will no longer count as focus time for {asked.course_title ?? "no course"}. You can restore it under
              Recently removed for {s.restore_days} days. History keeps a note that it was removed.
            </p>
            {remove.error && <ErrorNote error={remove.error} />}
          </div>
        )}
      </Confirm>
    </div>
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
    <div className="focus-more-body">
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
    </div>
  );
}

function BackgroundPicker() {
  const p = usePomodoro();
  const s = p.settings;
  const [hasImage, setHasImage] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const image = useBackgroundImage(hasImage);

  useEffect(() => {
    const check = () => void loadImage().then((b) => setHasImage(b !== null));
    check();
    window.addEventListener(IMAGE_CHANGED, check);
    return () => window.removeEventListener(IMAGE_CHANGED, check);
  }, []);

  async function choose(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const why = imageProblem(f);
    setProblem(why);
    if (why) return;
    setBusy(true);
    try {
      await saveImage(f);
      p.setSettings({ ...s, background: "image" });
    } catch {
      setProblem("This browser could not keep the image (private window, blocked site data or storage full).");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    await removeImage();
    if (s.background === "image") p.setSettings({ ...s, background: "theme" });
  }

  return (
    <div className="focus-more-body">
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
          {/* A real file field inside a label: some browsers ignore a script "click" on a hidden file input. */}
          <label className="btn small file-button" aria-busy={busy}>
            {busy ? "Saving…" : hasImage ? "Choose another image…" : "Choose an image…"}
            <input type="file" className="sr-only" accept="image/png,image/jpeg,image/webp,image/avif,image/gif" onChange={(e) => void choose(e)} />
          </label>
          {hasImage && (
            <button type="button" className="btn small ghost" onClick={() => void remove()}>
              Remove my image
            </button>
          )}
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
          The timer above shows your choice. Your image stays in this browser: it is not uploaded to RecallSpring and is not in backups.
        </p>
      </div>
    </div>
  );
}

/** A quiet picker: a small preview of each of the six faces, the chosen one on tint (2026-11-27). */
function FacePicker() {
  const p = usePomodoro();
  const total = p.settings.focus * 60_000;
  const chosen = FACES.find((f) => f.id === p.settings.face);
  return (
    <section className="focus-faces" aria-labelledby="focus-faces-h">
      <div className="focus-week-head">
        <h2 id="focus-faces-h">Clock face</h2>
        <span className="small muted">{chosen?.name}</span>
      </div>
      <div className="face-grid mini" role="radiogroup" aria-labelledby="focus-faces-h">
        {FACES.map((f) => (
          <button
            key={f.id}
            type="button"
            role="radio"
            aria-checked={p.settings.face === f.id}
            className="face-card mini"
            onClick={() => p.setSettings({ ...p.settings, face: f.id })}
          >
            <span className="face-sample" aria-hidden="true">
              <ClockFace face={f.id} ms={total * 0.62} total={total} preview />
            </span>
            <span className="theme-name">{f.name}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

/** Keep screen on while a block runs (Screen Wake Lock); a browser without it says so. */
function KeepAwake() {
  const p = usePomodoro();
  const supported = typeof navigator !== "undefined" && "wakeLock" in navigator;
  return (
    <label className="focus-switch">
      <span>
        Keep screen on
        <span className="small muted" style={{ display: "block" }}>
          {supported ? "While a block runs" : "This browser cannot keep the screen on"}
        </span>
      </span>
      <input
        type="checkbox"
        role="switch"
        className="switch"
        checked={supported && p.settings.keepAwake}
        disabled={!supported}
        onChange={(e) => p.setSettings({ ...p.settings, keepAwake: e.target.checked })}
      />
    </label>
  );
}

// ---------------------------------------------------------------- page

export function FocusPage() {
  const summary = useFocusSummary();
  return (
    <div className="page focus-page">
      <PageHead title="Focus" />
      <div className="focus-layout">
        <Timer />
        <div className="stack" style={{ gap: 18 }}>
          <FacePicker />
          <KeepAwake />
          <Async q={summary}>{(s) => <FocusTime s={s} />}</Async>
          <details className="focus-more">
            <summary>Timer settings</summary>
            <TimerSettings />
          </details>
          <details className="focus-more">
            <summary>Focus mode background</summary>
            <BackgroundPicker />
          </details>
          <details className="focus-more">
            <summary>Latest blocks</summary>
            <Async q={summary}>{(s) => <Recent s={s} />}</Async>
          </details>
        </div>
      </div>
    </div>
  );
}
