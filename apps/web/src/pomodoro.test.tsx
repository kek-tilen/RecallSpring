import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ClockFace } from "./components/Pomodoro";
import {
  DEFAULT_SETTINGS,
  FACES,
  advance,
  cleanSettings,
  clockText,
  focusOn,
  initialRun,
  pause,
  readRun,
  readSettings,
  reset,
  saveRun,
  saveSettings,
  start,
  withSettings,
  type PomodoroSettings,
  type RunState,
} from "./pomodoro";

const MIN = 60_000;
let n = 0;
const id = () => `block-${++n}`;

afterEach(() => {
  cleanup();
  localStorage.clear();
});

/** Run the current phase to its end and return the transition. */
function finish(run: RunState, s: PomodoroSettings, at: number) {
  const r = run.status === "running" ? run : start(run, at, id);
  return advance(r, s, r.endsAt!, true, id);
}

describe("Pomodoro timer", () => {
  it("defaults to 45 min focus, 10 min short break, 15 min long break after 4 blocks", () => {
    expect(readSettings()).toEqual(DEFAULT_SETTINGS);
    expect([DEFAULT_SETTINGS.focus, DEFAULT_SETTINGS.short, DEFAULT_SETTINGS.long, DEFAULT_SETTINGS.rounds]).toEqual([45, 10, 15, 4]);
    expect(initialRun(DEFAULT_SETTINGS).totalMs).toBe(45 * MIN);
  });

  it("goes focus, short break … and a long break after the fourth block", () => {
    const s = DEFAULT_SETTINGS;
    let run = initialRun(s);
    let t = 0;
    const seen: string[] = [];
    for (let i = 0; i < 8; i++) {
      const tr = finish(run, s, t);
      t = run.status === "running" ? run.endsAt! : t + run.totalMs;
      seen.push(`${tr.from}${run.round}`);
      if (tr.from === "focus") expect(tr.log?.completed).toBe(true);
      else expect(tr.log).toBeNull(); // breaks are not study time
      run = tr.run;
    }
    expect(seen).toEqual(["focus1", "short1", "focus2", "short2", "focus3", "short3", "focus4", "long4"]);
    expect(run.phase).toBe("focus");
    expect(run.round).toBe(1);
    expect(run.totalMs).toBe(45 * MIN);
  });

  it("does not count paused time and logs what was focused", () => {
    const s = DEFAULT_SETTINGS;
    let run = start(initialRun(s, "course-1"), 0, id);
    run = pause(run, 10 * MIN);
    expect(run.remainingMs).toBe(35 * MIN);
    run = start(run, 30 * MIN, id); // 20 minutes on pause
    expect(run.endsAt).toBe(65 * MIN);
    const tr = advance(run, s, run.endsAt!, true, id);
    expect(tr.log).toMatchObject({
      course_id: "course-1",
      planned_minutes: 45,
      focused_seconds: 45 * 60,
      completed: true,
      started_at: new Date(0).toISOString(),
      ended_at: new Date(65 * MIN).toISOString(),
    });
    expect(tr.log!.client_session_id).toBe(run.blockId);
  });

  it("keeps a stopped block of a minute or more, and drops a shorter one", () => {
    const s = DEFAULT_SETTINGS;
    const run = start(initialRun(s), 0, id);
    expect(advance(run, s, 30_000, false, id).log).toBeNull();
    const skipped = advance(run, s, 12 * MIN, false, id);
    expect(skipped.log).toMatchObject({ focused_seconds: 12 * 60, completed: false });
    expect(skipped.run.phase).toBe("short");
    expect(skipped.run.status).toBe("idle"); // skipping never starts the next phase by itself
    const stopped = reset(run, s, 5 * MIN);
    expect(stopped.log).toMatchObject({ focused_seconds: 5 * 60, completed: false });
    expect(stopped.run).toMatchObject({ phase: "focus", round: 1, status: "idle" });
  });

  it("a block reset while paused counts on the day of the pause, not the reset (owner 2026-11-25)", () => {
    const s = DEFAULT_SETTINGS;
    const day = 24 * 60 * MIN;
    const paused = pause(start(initialRun(s, "course-1"), 0, id), 20 * MIN);
    expect(paused.pausedAt).toBe(20 * MIN);
    const stopped = reset(paused, s, day + 9 * 60 * MIN); // reset the next morning
    expect(stopped.log).toMatchObject({
      started_at: new Date(0).toISOString(),
      ended_at: new Date(20 * MIN).toISOString(),
      focused_seconds: 20 * 60,
      completed: false,
    });
    // skipped while paused: the same
    expect(advance(paused, s, day, false, id).log).toMatchObject({ ended_at: new Date(20 * MIN).toISOString() });
    // resumed later and then reset: the block ends at the reset as before
    const resumed = start(paused, 30 * MIN, id);
    expect(resumed.pausedAt).toBeNull();
    expect(reset(resumed, s, 40 * MIN).log).toMatchObject({ ended_at: new Date(40 * MIN).toISOString(), focused_seconds: 30 * 60 });
    // a run stored before this change (no pausedAt) still ends at the reset
    const legacy = { ...paused, pausedAt: null };
    expect(reset(legacy, s, 50 * MIN).log).toMatchObject({ ended_at: new Date(50 * MIN).toISOString() });
  });

  it("starts the next phase on its own only when asked to", () => {
    const auto = { ...DEFAULT_SETTINGS, autoStart: true };
    const tr = finish(initialRun(auto), auto, 0);
    expect(tr.run.status).toBe("running");
    expect(tr.run.endsAt).toBe(45 * MIN + 10 * MIN);
  });

  it("applies new lengths only to a phase that has not started", () => {
    const short = { ...DEFAULT_SETTINGS, focus: 25 };
    expect(withSettings(initialRun(DEFAULT_SETTINGS), short).totalMs).toBe(25 * MIN);
    const running = start(initialRun(DEFAULT_SETTINGS), 0, id);
    expect(withSettings(running, short)).toBe(running);
  });

  it("cleans stored settings and survives a reload", () => {
    expect(cleanSettings({ focus: 999, short: -3, rounds: 2.4, face: "<b>", background: "image", dim: 95 })).toMatchObject({
      focus: 180,
      short: 1,
      rounds: 2,
      face: "default",
      background: "image",
      dim: 80,
    });
    saveSettings({ ...DEFAULT_SETTINGS, focus: 50, face: "ring" });
    expect(readSettings()).toMatchObject({ focus: 50, face: "ring" });
    const run = start(initialRun(DEFAULT_SETTINGS), 1000, id);
    saveRun(run);
    expect(readRun(DEFAULT_SETTINGS)).toEqual(run);
    localStorage.setItem("rs-pomodoro-run", '{"phase":"nap"}');
    expect(readRun(DEFAULT_SETTINGS)).toEqual(initialRun(DEFAULT_SETTINGS));
  });

  it("starts focus on a course from the plan", () => {
    const s = DEFAULT_SETTINGS;
    // Not started: a focus block for this course, running now.
    const fresh = focusOn(initialRun(s), s, 0, "stats", id);
    expect(fresh).toMatchObject({ phase: "focus", status: "running", courseId: "stats", endsAt: 45 * MIN });
    // Paused focus block: resumed, and it counts for the chosen course.
    const paused = pause(start(initialRun(s, "other"), 0, id), 5 * MIN);
    const resumed = focusOn(paused, s, 10 * MIN, "stats", id);
    expect(resumed).toMatchObject({ status: "running", courseId: "stats", blockId: paused.blockId, endsAt: 50 * MIN });
    // During a break: the break ends early (nothing saved) and focus block 2 starts.
    const brk = finish(initialRun(s), s, 0).run;
    expect(brk.phase).toBe("short");
    const next = focusOn(start(brk, 45 * MIN, id), s, 47 * MIN, "stats", id);
    expect(next).toMatchObject({ phase: "focus", round: 2, status: "running", courseId: "stats", endsAt: 92 * MIN });
  });

  it("formats the clock", () => {
    expect(clockText(45 * MIN)).toBe("45:00");
    expect(clockText(61_500)).toBe("01:02");
    expect(clockText(0)).toBe("00:00");
    expect(clockText(125 * MIN)).toBe("2:05:00");
  });
});

describe("Clock faces", () => {
  it("offers six faces, including a ring", () => {
    expect(FACES.map((f) => f.name)).toEqual(["Default", "Flip Clock", "Progress Bar", "Dot Matrix", "Pie", "Ring"]);
  });

  it("are hidden from screen readers and empty as time runs out", () => {
    const total = 45 * MIN;
    for (const f of FACES) {
      const { container } = render(<ClockFace face={f.id} ms={total / 2} total={total} />);
      expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
      cleanup();
    }
    const ring = render(<ClockFace face="ring" ms={total / 4} total={total} />);
    expect(ring.container.querySelector(".face-fill-stroke")?.getAttribute("stroke-dasharray")).toBe("25 100");
    expect(ring.container.querySelector(".face-time")?.textContent).toBe("11:15");
    cleanup();
    const dots = render(<ClockFace face="dots" ms={10 * MIN} total={total} />);
    expect(dots.container.querySelectorAll(".dot-grid > span")).toHaveLength(45);
    expect(dots.container.querySelectorAll(".dot-grid > span.on")).toHaveLength(10);
    cleanup();
    const flip = render(<ClockFace face="flip" ms={25 * MIN} total={total} preview />);
    expect(Array.from(flip.container.querySelectorAll(".flip-card"), (c) => c.textContent)).toEqual(["2", "5"]);
  });
});
