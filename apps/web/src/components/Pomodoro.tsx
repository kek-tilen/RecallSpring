import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router";
import { ApiError, newKey, request } from "../api";
import { IMAGE_CHANGED, chime, loadImage, primeAudio } from "../focusMedia";
import {
  PHASE_LABEL,
  RUN_STORAGE_KEY,
  advance,
  clockText,
  focusOn,
  pause,
  phaseEndMessage,
  readQueue,
  readRun,
  readSettings,
  remaining,
  reset as resetRun,
  saveQueue,
  saveRun,
  saveSettings,
  start,
  withSettings,
  type BackgroundId,
  type Face,
  type PomodoroSettings,
  type RunState,
  type Transition,
} from "../pomodoro";
import { keys } from "../queries";

// ---------------------------------------------------------------- shared timer state

interface PomodoroApi {
  settings: PomodoroSettings;
  run: RunState;
  now: number;
  left: number;
  unsaved: number; // focus blocks waiting to be saved (offline)
  focusMode: boolean;
  setFocusMode: (on: boolean) => void;
  setSettings: (next: PomodoroSettings) => void;
  toggle: () => void;
  skip: () => void;
  reset: () => void;
  setCourse: (courseId: string | null) => void;
  /** Focus on this course now, with only the timer over the window (the plan's Start focus). */
  startFocus: (courseId: string) => void;
}

const Ctx = createContext<PomodoroApi | null>(null);

export function usePomodoro(): PomodoroApi {
  const api = useContext(Ctx);
  if (!api) throw new Error("usePomodoro outside PomodoroProvider");
  return api;
}

const STALE_ALERT_MS = 60_000; // a phase that ended long ago (tab closed) is finished quietly

/** Holds the timer for the whole signed-in app, so it keeps running while the learner moves between pages. */
export function PomodoroProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [settings, setSettingsState] = useState(readSettings);
  const [run, setRun] = useState(() => readRun(readSettings()));
  const [now, setNow] = useState(Date.now);
  const [focusMode, setFocusMode] = useState(false);
  const [unsaved, setUnsaved] = useState(() => readQueue().length);
  const [announcement, setAnnouncement] = useState("");
  const settingsRef = useRef(settings);
  const runRef = useRef(run);
  const flushing = useRef(false);
  settingsRef.current = settings;
  runRef.current = run;

  // Keep screen on (2026-11-27): while the timer runs, ask the browser to keep the screen awake; released on pause,
  // stop or when the tab is hidden (the browser does that itself) and asked again when it comes back.
  const awake = settings.keepAwake && run.status === "running";
  useEffect(() => {
    const nav = navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> } };
    if (!awake || !nav.wakeLock) return;
    let lock: { release: () => Promise<void> } | null = null;
    let gone = false;
    const ask = () => {
      if (document.visibilityState !== "visible") return;
      nav.wakeLock!
        .request("screen")
        .then((l) => {
          if (gone) void l.release();
          else lock = l;
        })
        .catch(() => {
          /* refused (battery saver, policy): the timer simply runs without it */
        });
    };
    ask();
    document.addEventListener("visibilitychange", ask);
    return () => {
      gone = true;
      document.removeEventListener("visibilitychange", ask);
      if (lock) void lock.release();
    };
  }, [awake]);

  const commit = useCallback((next: RunState) => {
    runRef.current = next;
    setRun(next);
    setNow(Date.now());
    saveRun(next);
  }, []);

  const flush = useCallback(async () => {
    if (flushing.current) return;
    flushing.current = true;
    let saved = false;
    try {
      for (const log of readQueue()) {
        try {
          await request("/focus-sessions", { json: log, key: log.client_session_id });
          saved = true;
        } catch (e) {
          // Offline, signed out or a server problem: keep it for later. Refused (e.g. too old): drop it.
          const refused = e instanceof ApiError && e.status >= 400 && e.status < 500 && ![401, 403, 408, 429].includes(e.status);
          if (!refused) break;
        }
        saveQueue(readQueue().filter((l) => l.client_session_id !== log.client_session_id));
      }
    } finally {
      flushing.current = false;
      setUnsaved(readQueue().length);
      if (saved) {
        void qc.invalidateQueries({ queryKey: ["focus"] });
        void qc.invalidateQueries({ queryKey: keys.history });
        void qc.invalidateQueries({ queryKey: keys.dashboard });
      }
    }
  }, [qc]);

  const apply = useCallback(
    (t: Transition, alert: boolean) => {
      commit(t.run);
      if (t.log) {
        // Kept in this browser first, so a block is never lost when RecallSpring is not reachable.
        saveQueue([...readQueue().filter((l) => l.client_session_id !== t.log!.client_session_id), t.log]);
        setUnsaved(readQueue().length);
        void flush();
      }
      if (!alert) return;
      const s = settingsRef.current;
      const msg = phaseEndMessage(t.from, s, t.run);
      setAnnouncement(`${msg.title}. ${msg.body}`);
      if (s.sound) chime(t.from === "focus" ? "rest" : "focus");
      if (s.notify && typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification(msg.title, { body: msg.body, tag: "recallspring-focus", icon: "/favicon-192x192.png" });
        } catch {
          /* notifications unavailable here */
        }
      }
    },
    [commit, flush],
  );

  const finish = useCallback(() => {
    const cur = runRef.current;
    const t = Date.now();
    if (cur.status !== "running" || cur.endsAt === null || t < cur.endsAt - 25) return;
    apply(advance(cur, settingsRef.current, t, true, newKey), t - cur.endsAt < STALE_ALERT_MS);
  }, [apply]);

  // The phase ends on a single timer set for its end time (not a counted interval), so it fires on time even
  // when the browser slows down timers in a background tab.
  useEffect(() => {
    if (run.status !== "running" || run.endsAt === null) return;
    const id = window.setTimeout(finish, Math.max(0, run.endsAt - Date.now()));
    return () => window.clearTimeout(id);
  }, [run.status, run.endsAt, finish]);

  useEffect(() => {
    if (run.status !== "running") return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [run.status]);

  // Another tab started, paused or finished the timer: follow it.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === RUN_STORAGE_KEY && e.newValue) {
        const next = readRun(settingsRef.current);
        runRef.current = next;
        setRun(next);
        setNow(Date.now());
      }
    }
    function onOnline() {
      void flush();
    }
    window.addEventListener("storage", onStorage);
    window.addEventListener("online", onOnline);
    if (readQueue().length) void flush();
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("online", onOnline);
    };
  }, [flush]);

  const left = remaining(run, now);
  const active = run.status !== "idle";

  useEffect(() => {
    if (!active) return;
    const base = document.title;
    return () => {
      document.title = base;
    };
  }, [active]);

  useEffect(() => {
    if (active) document.title = `${clockText(left)} · ${PHASE_LABEL[run.phase]}${run.status === "paused" ? " (paused)" : ""}`;
  }, [active, left, run.phase, run.status]);

  const api = useMemo<PomodoroApi>(
    () => ({
      settings,
      run,
      now,
      left,
      unsaved,
      focusMode,
      setFocusMode,
      setSettings: (next) => {
        saveSettings(next);
        setSettingsState(next);
        commit(withSettings(runRef.current, next));
      },
      toggle: () => {
        primeAudio();
        const cur = runRef.current;
        commit(cur.status === "running" ? pause(cur, Date.now()) : start(cur, Date.now(), newKey));
      },
      skip: () => apply(advance(runRef.current, settingsRef.current, Date.now(), false, newKey), false),
      reset: () => apply(resetRun(runRef.current, settingsRef.current, Date.now()), false),
      setCourse: (courseId) => commit({ ...runRef.current, courseId }),
      startFocus: (courseId) => {
        primeAudio();
        commit(focusOn(runRef.current, settingsRef.current, Date.now(), courseId, newKey));
        setFocusMode(true);
      },
    }),
    [settings, run, now, left, unsaved, focusMode, commit, apply],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
      {focusMode && <FocusMode onClose={() => setFocusMode(false)} />}
    </Ctx.Provider>
  );
}

// ---------------------------------------------------------------- clock faces

/**
 * One of six faces. Purely visual (aria-hidden): screen readers get the time from `TimerText`. The bright part shows
 * the time left, so every face empties as the phase runs.
 */
export function ClockFace({ face, ms, total, preview = false }: { face: Face; ms: number; total: number; preview?: boolean }) {
  const text = clockText(ms);
  const frac = total > 0 ? Math.min(1, Math.max(0, ms / total)) : 0;
  const cls = `face face-${face}${preview ? " preview" : ""}`;
  if (face === "flip") {
    const shown = preview ? text.split(":")[0]! : text;
    return (
      <div className={cls} aria-hidden="true">
        {shown.split("").map((ch, i) =>
          ch === ":" ? (
            <span key={`c${i}`} className="flip-colon">
              :
            </span>
          ) : (
            <span key={`${i}-${ch}`} className="flip-card">
              {ch}
            </span>
          ),
        )}
      </div>
    );
  }
  if (face === "bar") {
    return (
      <div className={cls} aria-hidden="true">
        <span className="face-time">{text}</span>
        <span className="face-progress">
          <span style={{ width: `${frac * 100}%` }} />
        </span>
      </div>
    );
  }
  if (face === "dots") {
    const n = Math.min(60, Math.max(1, Math.round(total / 60_000)));
    const per = total / n;
    const lit = ms <= 0 ? 0 : Math.min(n, Math.ceil(ms / per - 1e-6));
    const cols = n <= 12 ? n : Math.ceil(Math.sqrt(n * 2.2));
    return (
      <div className={cls} aria-hidden="true">
        <span className="dot-grid" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {Array.from({ length: n }, (_, i) => (
            <span key={i} className={i < lit ? "on" : undefined} />
          ))}
        </span>
        <span className="face-time">{text}</span>
      </div>
    );
  }
  if (face === "pie") {
    return (
      <div className={cls} aria-hidden="true">
        <svg viewBox="0 0 100 100" className="face-svg">
          <circle cx="50" cy="50" r="48" className="face-track-fill" />
          {frac >= 0.9995 ? <circle cx="50" cy="50" r="48" className="face-fill" /> : frac > 0 && <path d={sector(frac)} className="face-fill" />}
        </svg>
        <span className="face-time">{text}</span>
      </div>
    );
  }
  if (face === "ring") {
    return (
      <div className={cls} aria-hidden="true">
        <span className="face-ring">
          <svg viewBox="0 0 100 100" className="face-svg">
            <circle cx="50" cy="50" r="44" className="face-track-stroke" pathLength={100} />
            {frac > 0 && (
              <circle
                cx="50"
                cy="50"
                r="44"
                className="face-fill-stroke"
                pathLength={100}
                strokeDasharray={`${frac * 100} 100`}
                transform="rotate(-90 50 50)"
              />
            )}
          </svg>
          <span className="face-time">{text}</span>
        </span>
      </div>
    );
  }
  return (
    <div className={cls} aria-hidden="true">
      <span className="face-time">{text}</span>
    </div>
  );
}

/** Sector of the time left, clockwise from 12 o'clock. */
function sector(frac: number): string {
  const a = frac * 2 * Math.PI;
  const x = 50 + 48 * Math.sin(a);
  const y = 50 - 48 * Math.cos(a);
  return `M50 50 L50 2 A48 48 0 ${frac > 0.5 ? 1 : 0} 1 ${x.toFixed(3)} ${y.toFixed(3)} Z`;
}

/** The time left for screen readers, in whole minutes so it is not read out every second. */
export function TimerText({ ms, phase, paused }: { ms: number; phase: RunState["phase"]; paused: boolean }) {
  const min = Math.ceil(ms / 60_000);
  return (
    <span className="sr-only" role="timer">
      {PHASE_LABEL[phase]}: {min} {min === 1 ? "minute" : "minutes"} left{paused ? ", paused" : ""}
    </span>
  );
}

// ---------------------------------------------------------------- backgrounds for focus mode

export const BACKGROUNDS: { id: BackgroundId; name: string; tone: "theme" | "dark" | "light"; css: string }[] = [
  { id: "theme", name: "Theme", tone: "theme", css: "var(--bg)" },
  { id: "night", name: "Night", tone: "dark", css: "#0e1116" },
  { id: "forest", name: "Forest", tone: "dark", css: "linear-gradient(160deg, #0f2a24, #24594b)" },
  { id: "dusk", name: "Dusk", tone: "dark", css: "linear-gradient(160deg, #2b1d3f, #7a3b4f)" },
  { id: "ocean", name: "Ocean", tone: "dark", css: "linear-gradient(160deg, #0b2540, #1f5f7a)" },
  { id: "sand", name: "Sand", tone: "light", css: "linear-gradient(160deg, #f6efe0, #e6d6b8)" },
  { id: "image", name: "My image", tone: "dark", css: "#0e1116" },
];

/** An object URL for the learner's stored background image, or null. Revoked when no longer shown; follows a
 * newly chosen image at once. */
export function useBackgroundImage(enabled: boolean): string | null {
  const [url, setUrl] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((v) => v + 1);
    window.addEventListener(IMAGE_CHANGED, bump);
    return () => window.removeEventListener(IMAGE_CHANGED, bump);
  }, []);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let made: string | null = null;
    void loadImage().then((blob) => {
      if (!live || !blob) return;
      made = URL.createObjectURL(blob);
      setUrl(made);
    });
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
      setUrl(null);
    };
  }, [enabled, version]);
  return url;
}

/** The chosen background behind the timer: colours, or the learner's image darkened by `dim`. Used by focus
 * mode and as the live preview on the Focus page, so a choice is visible at once. */
export function FocusStage({ settings, className, children }: { settings: PomodoroSettings; className: string; children: ReactNode }) {
  const bg = BACKGROUNDS.find((b) => b.id === settings.background) ?? BACKGROUNDS[0]!;
  const image = useBackgroundImage(bg.id === "image");
  return (
    <div className={`focus-stage ${className}`} data-tone={bg.tone} style={{ background: bg.css }}>
      {bg.id === "image" && image && <img className="focus-stage-bg" src={image} alt="" />}
      {bg.id === "image" && <div className="focus-stage-scrim" style={{ opacity: settings.dim / 100 }} />}
      <div className="focus-stage-body">{children}</div>
    </div>
  );
}

const FOCUSABLE = 'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function FocusMode({ onClose }: { onClose: () => void }) {
  const p = usePomodoro();
  const box = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    box.current?.querySelector<HTMLElement>(".focus-mode-controls button")?.focus();
    const root = document.documentElement;
    root.classList.add("focus-mode-open");
    return () => {
      root.classList.remove("focus-mode-open");
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
      // Back to what opened focus mode; after the F key with nothing focused, to the Focus mode button.
      const back = opener.current instanceof HTMLElement && opener.current !== document.body ? opener.current : null;
      (back ?? document.querySelector<HTMLElement>("[data-focus-mode-opener]"))?.focus();
    };
  }, []);

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === " " && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault();
      p.toggle();
    } else if (e.key === "Tab" && box.current) {
      const items = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0]!;
      const last = items[items.length - 1]!;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  function fullScreen() {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    else void box.current?.requestFullscreen?.().catch(() => undefined);
  }

  const { run, settings, left } = p;
  return createPortal(
    <div ref={box} className="focus-mode" role="dialog" aria-modal="true" aria-label="Focus mode" onKeyDown={onKey}>
      <FocusStage settings={settings} className="focus-mode-stage">
          <div className="focus-mode-phase">
            {PHASE_LABEL[run.phase]}
            {run.status === "paused" && " · paused"}
          </div>
          <ClockFace face={settings.face} ms={left} total={run.totalMs} />
          <TimerText ms={left} phase={run.phase} paused={run.status === "paused"} />
          <RoundDots run={run} rounds={settings.rounds} />
          <div className="row focus-mode-controls">
            <button type="button" className="btn primary" onClick={p.toggle}>
              {run.status === "running" ? "Pause" : run.status === "paused" ? "Resume" : "Start"}
            </button>
            <button type="button" className="btn" onClick={p.skip}>
              Skip
            </button>
            {typeof document !== "undefined" && document.fullscreenEnabled && (
              <button type="button" className="btn" onClick={fullScreen}>
                Full screen
              </button>
            )}
            <button type="button" className="btn" onClick={onClose}>
              Exit focus mode
            </button>
          </div>
          <p className="tiny focus-mode-hint">Space starts or pauses · Esc exits</p>
      </FocusStage>
    </div>,
    document.body,
  );
}

export function RoundDots({ run, rounds }: { run: RunState; rounds: number }) {
  // Blocks finished in this cycle: during focus the ones before it, during a break the one just done too.
  const done = run.phase === "focus" ? run.round - 1 : run.phase === "long" ? rounds : run.round;
  return (
    <div className="round-dots" aria-label={`Focus block ${Math.min(run.round, rounds)} of ${rounds}`} role="img">
      {Array.from({ length: rounds }, (_, i) => (
        <span key={i} className={i < done ? "done" : i === done && run.phase === "focus" ? "now" : undefined} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- small timer on other pages

function PlayPauseIcon({ running }: { running: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false">
      {running ? (
        <>
          <rect x="3" y="2" width="3" height="10" rx="1" fill="currentColor" />
          <rect x="8" y="2" width="3" height="10" rx="1" fill="currentColor" />
        </>
      ) : (
        <path d="M4 2.5v9l7.5-4.5z" fill="currentColor" />
      )}
    </svg>
  );
}

/** Shown on every page except Focus while a phase is under way: in the menu, or beside Show menu when it is hidden. */
export function FocusPill({ floating = false }: { floating?: boolean }) {
  const p = usePomodoro();
  const location = useLocation();
  const { run } = p;
  const underWay = run.status !== "idle" || run.remainingMs !== run.totalMs || run.phase !== "focus";
  if (!underWay || location.pathname === "/focus" || p.focusMode) return null;
  const running = run.status === "running";
  return (
    <div className={floating ? "focus-pill floating" : "focus-pill"} data-phase={run.phase}>
      <Link to="/focus" className="focus-pill-link">
        <span className="tiny">{PHASE_LABEL[run.phase]}</span>
        <span className="focus-pill-time">{clockText(p.left)}</span>
        <span className="sr-only">Open the Focus timer</span>
      </Link>
      <button
        type="button"
        className="btn small ghost"
        aria-label={running ? "Pause timer" : run.status === "paused" ? "Resume timer" : "Start timer"}
        onClick={p.toggle}
      >
        <PlayPauseIcon running={running} />
      </button>
    </div>
  );
}
