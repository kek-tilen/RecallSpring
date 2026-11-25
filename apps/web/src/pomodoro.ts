/**
 * Pomodoro timer logic (docs/06 → Focus). Pure functions over a small state that is kept in this browser, so the
 * timer survives reloads and moving between pages. Times are wall-clock timestamps (ms), never counted ticks, so a
 * throttled background tab still ends a phase at the right moment.
 *
 * A finished focus block, or one stopped after at least a minute, becomes a `FocusLog` the app saves to RecallSpring
 * as study time. Breaks are not saved. A block stopped while paused ends at its pause, so a reset the next day
 * counts the time on the day it was focused (owner 2026-11-25).
 */

export type Phase = "focus" | "short" | "long";
export type Face = "default" | "flip" | "bar" | "dots" | "pie" | "ring";
export type BackgroundId = "theme" | "night" | "forest" | "dusk" | "ocean" | "sand" | "image";

export interface PomodoroSettings {
  focus: number; // minutes
  short: number;
  long: number;
  rounds: number; // focus blocks before the long break
  autoStart: boolean;
  sound: boolean;
  notify: boolean;
  face: Face;
  background: BackgroundId;
  dim: number; // % darkening over a background image
}

export interface RunState {
  phase: Phase;
  round: number; // which focus block of the cycle (1…rounds); during a break, the block just finished
  status: "idle" | "running" | "paused";
  totalMs: number;
  endsAt: number | null; // while running
  remainingMs: number; // while idle or paused
  blockId: string | null; // the focus block's client_session_id, set when it first starts
  blockStartedAt: number | null;
  focusedMs: number; // focus time before the current running stretch
  runningSince: number | null;
  pausedAt: number | null; // while paused: when the pause began
  courseId: string | null;
}

export interface FocusLog {
  client_session_id: string;
  course_id: string | null;
  started_at: string;
  ended_at: string;
  planned_minutes: number;
  focused_seconds: number;
  completed: boolean;
}

export const DEFAULT_SETTINGS: PomodoroSettings = {
  focus: 45,
  short: 10,
  long: 15,
  rounds: 4,
  autoStart: false,
  sound: true,
  notify: false,
  face: "default",
  background: "theme",
  dim: 40,
};

export const LIMITS = { focus: [1, 180], short: [1, 60], long: [1, 90], rounds: [1, 12], dim: [0, 80] } as const;

export const FACES: { id: Face; name: string }[] = [
  { id: "default", name: "Default" },
  { id: "flip", name: "Flip Clock" },
  { id: "bar", name: "Progress Bar" },
  { id: "dots", name: "Dot Matrix" },
  { id: "pie", name: "Pie" },
  { id: "ring", name: "Ring" },
];

export const PHASE_LABEL: Record<Phase, string> = { focus: "Focus", short: "Short break", long: "Long break" };

const MIN_LOGGED_MS = 60_000;
const SETTINGS_KEY = "rs-pomodoro";
const RUN_KEY = "rs-pomodoro-run";

const FACE_IDS = new Set<string>(FACES.map((f) => f.id));
const BACKGROUND_IDS = new Set<string>(["theme", "night", "forest", "dusk", "ocean", "sand", "image"]);

function clamp(value: unknown, [lo, hi]: readonly [number, number], fallback: number): number {
  const n = typeof value === "number" && Number.isFinite(value) ? Math.round(value) : fallback;
  return Math.min(hi, Math.max(lo, n));
}

export function cleanSettings(raw: unknown): PomodoroSettings {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const d = DEFAULT_SETTINGS;
  return {
    focus: clamp(r.focus, LIMITS.focus, d.focus),
    short: clamp(r.short, LIMITS.short, d.short),
    long: clamp(r.long, LIMITS.long, d.long),
    rounds: clamp(r.rounds, LIMITS.rounds, d.rounds),
    autoStart: typeof r.autoStart === "boolean" ? r.autoStart : d.autoStart,
    sound: typeof r.sound === "boolean" ? r.sound : d.sound,
    notify: typeof r.notify === "boolean" ? r.notify : d.notify,
    face: typeof r.face === "string" && FACE_IDS.has(r.face) ? (r.face as Face) : d.face,
    background:
      typeof r.background === "string" && BACKGROUND_IDS.has(r.background) ? (r.background as BackgroundId) : d.background,
    dim: clamp(r.dim, LIMITS.dim, d.dim),
  };
}

function readJson(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: kept for this page only */
  }
}

export const readSettings = (): PomodoroSettings => cleanSettings(readJson(SETTINGS_KEY));
export const saveSettings = (s: PomodoroSettings): void => writeJson(SETTINGS_KEY, s);

export function phaseMs(settings: PomodoroSettings, phase: Phase): number {
  return settings[phase] * 60_000;
}

export function initialRun(settings: PomodoroSettings, courseId: string | null = null): RunState {
  const total = phaseMs(settings, "focus");
  return {
    phase: "focus",
    round: 1,
    status: "idle",
    totalMs: total,
    endsAt: null,
    remainingMs: total,
    blockId: null,
    blockStartedAt: null,
    focusedMs: 0,
    runningSince: null,
    pausedAt: null,
    courseId,
  };
}

/** A stored run, or a fresh one when nothing valid is stored. */
export function readRun(settings: PomodoroSettings): RunState {
  const r = readJson(RUN_KEY) as Partial<RunState> | null;
  const ok =
    r &&
    (r.phase === "focus" || r.phase === "short" || r.phase === "long") &&
    (r.status === "idle" || r.status === "running" || r.status === "paused") &&
    typeof r.totalMs === "number" &&
    typeof r.remainingMs === "number" &&
    (r.status !== "running" || typeof r.endsAt === "number");
  return ok ? ({ ...initialRun(settings), ...r } as RunState) : initialRun(settings);
}

export const saveRun = (run: RunState): void => writeJson(RUN_KEY, run);
export const RUN_STORAGE_KEY = RUN_KEY;

export function remaining(run: RunState, now: number): number {
  if (run.status === "running" && run.endsAt !== null) return Math.max(0, run.endsAt - now);
  return run.remainingMs;
}

export function focusedSoFar(run: RunState, now: number): number {
  if (run.phase !== "focus") return 0;
  return run.focusedMs + (run.status === "running" && run.runningSince !== null ? now - run.runningSince : 0);
}

export function start(run: RunState, now: number, newId: () => string): RunState {
  if (run.status === "running") return run;
  const firstStart = run.phase === "focus" && run.blockId === null;
  return {
    ...run,
    status: "running",
    endsAt: now + run.remainingMs,
    runningSince: now,
    pausedAt: null,
    blockId: firstStart ? newId() : run.blockId,
    blockStartedAt: firstStart ? now : run.blockStartedAt,
  };
}

export function pause(run: RunState, now: number): RunState {
  if (run.status !== "running") return run;
  return {
    ...run,
    status: "paused",
    remainingMs: remaining(run, now),
    endsAt: null,
    focusedMs: focusedSoFar(run, now),
    runningSince: null,
    pausedAt: now,
  };
}

function logFor(run: RunState, at: number, completed: boolean): FocusLog | null {
  if (run.phase !== "focus" || run.blockId === null || run.blockStartedAt === null) return null;
  // Stopped while paused: the block ended when the pause began, not when it was reset or skipped.
  const now = run.status === "paused" && run.pausedAt !== null ? Math.min(at, Math.max(run.pausedAt, run.blockStartedAt)) : at;
  const focused = Math.min(focusedSoFar(run, now), now - run.blockStartedAt);
  if (focused < MIN_LOGGED_MS) return null;
  return {
    client_session_id: run.blockId,
    course_id: run.courseId,
    started_at: new Date(run.blockStartedAt).toISOString(),
    ended_at: new Date(now).toISOString(),
    planned_minutes: Math.min(240, Math.max(1, Math.round(run.totalMs / 60_000))),
    focused_seconds: Math.min(14_400, Math.floor(focused / 1000)),
    completed,
  };
}

function phaseAfter(run: RunState, settings: PomodoroSettings): { phase: Phase; round: number } {
  if (run.phase === "focus") return { phase: run.round >= settings.rounds ? "long" : "short", round: run.round };
  return { phase: "focus", round: run.phase === "long" ? 1 : Math.min(run.round + 1, settings.rounds) };
}

function enter(run: RunState, settings: PomodoroSettings, next: { phase: Phase; round: number }): RunState {
  const total = phaseMs(settings, next.phase);
  return {
    ...run,
    ...next,
    status: "idle",
    totalMs: total,
    remainingMs: total,
    endsAt: null,
    runningSince: null,
    pausedAt: null,
    blockId: null,
    blockStartedAt: null,
    focusedMs: 0,
  };
}

export interface Transition {
  run: RunState;
  log: FocusLog | null;
  from: Phase;
}

/**
 * Move to the next phase: `completed` when time ran out, otherwise skipped by the learner. A focus block is logged
 * either way once it has a minute of focus. With auto-start the next phase runs at once (from `now`).
 */
export function advance(
  run: RunState,
  settings: PomodoroSettings,
  now: number,
  completed: boolean,
  newId: () => string,
): Transition {
  const endedAt = completed && run.endsAt !== null ? Math.min(now, run.endsAt) : now;
  const log = logFor(run, endedAt, completed);
  let next = enter(run, settings, phaseAfter(run, settings));
  if (completed && settings.autoStart) next = start(next, now, newId);
  return { run: next, log, from: run.phase };
}

/**
 * "Start focus" from the plan on Today: a focus block for this course, now. A break is ended early (breaks are never
 * saved); a focus block already under way continues and counts for this course.
 */
export function focusOn(
  run: RunState,
  settings: PomodoroSettings,
  now: number,
  courseId: string,
  newId: () => string,
): RunState {
  const inFocus = run.phase === "focus" ? run : advance(run, settings, now, false, newId).run;
  const next = { ...inFocus, courseId };
  return next.status === "running" ? next : start(next, now, newId);
}

/** Back to the first focus block of a cycle. A focus block with a minute of focus is kept as stopped early. */
export function reset(run: RunState, settings: PomodoroSettings, now: number): Transition {
  return { run: initialRun(settings, run.courseId), log: logFor(run, now, false), from: run.phase };
}

/** New lengths apply at once to a phase that has not started; a running or paused phase keeps its length. */
export function withSettings(run: RunState, settings: PomodoroSettings): RunState {
  if (run.status !== "idle" || run.remainingMs !== run.totalMs) return run;
  const total = phaseMs(settings, run.phase);
  return { ...run, totalMs: total, remainingMs: total, round: Math.min(run.round, settings.rounds) };
}

export function clockText(ms: number): string {
  const s = Math.ceil(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h > 0 ? `${h}:${String(m).padStart(2, "0")}` : String(m).padStart(2, "0");
  return `${mm}:${String(sec).padStart(2, "0")}`;
}

export function phaseEndMessage(from: Phase, settings: PomodoroSettings, next: RunState): { title: string; body: string } {
  if (from === "focus") {
    const breakMin = settings[next.phase === "long" ? "long" : "short"];
    return {
      title: "Focus block done",
      body: `Time for a ${breakMin}-minute ${next.phase === "long" ? "long break" : "break"}.`,
    };
  }
  return { title: "Break over", body: `Ready for focus block ${next.round} of ${settings.rounds}?` };
}

// ---------------------------------------------------------------- saving focus blocks (retried when offline)

const QUEUE_KEY = "rs-focus-queue";

export function readQueue(): FocusLog[] {
  const q = readJson(QUEUE_KEY);
  return Array.isArray(q) ? (q as FocusLog[]).filter((l) => l && typeof l.client_session_id === "string") : [];
}

export function saveQueue(q: FocusLog[]): void {
  try {
    if (q.length === 0) localStorage.removeItem(QUEUE_KEY);
    else localStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-50)));
  } catch {
    /* storage unavailable */
  }
}
