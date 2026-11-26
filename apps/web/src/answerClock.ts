/**
 * Answer timing (ADR-014 §3): how long each question was open and visible in a RecallSpring answer form, without
 * pauses over 5 minutes. The planner learns the learner's pace for its review estimates from it. Like focus
 * sessions it records time spent, never learning or mastery.
 *
 * Used by the web app's answer forms and, built as clock.js (npm run build:mcp-clock), by the MCP forms.
 */

export const PAUSE_MS = 5 * 60_000;
export const MAX_SECONDS = 7200;

/**
 * Time counts between two moments of activity (typing, clicking, scrolling, moving the pointer) while the page is
 * visible, when they are at most PAUSE_MS apart; a longer gap is a pause and counts nothing. Each gap goes to the
 * question the later moment belongs to, else to the last question worked on.
 */
export class AnswerClock {
  private readonly ms = new Map<string, number>();
  private last: number | null;
  private current: string | null;

  /** start: seconds already spent per question (e.g. from a saved draft). */
  constructor(start: Record<string, number | null | undefined> = {}, now = Date.now(), current: string | null = null) {
    for (const [id, seconds] of Object.entries(start)) {
      if (typeof seconds === "number" && seconds > 0) this.ms.set(id, Math.min(seconds, MAX_SECONDS) * 1000);
    }
    this.last = now;
    this.current = current;
  }

  /** Activity on a question (or on the page, when question is null). */
  touch(question: string | null = null, now = Date.now()): void {
    const owner = question ?? this.current;
    if (this.last !== null && owner !== null) {
      const gap = now - this.last;
      if (gap > 0 && gap <= PAUSE_MS) this.ms.set(owner, (this.ms.get(owner) ?? 0) + gap);
    }
    this.last = now;
    if (question !== null) this.current = question;
  }

  /** The page was hidden: the time up to now counts, the time while hidden does not. */
  hide(now = Date.now()): void {
    this.touch(null, now);
    this.last = null;
  }

  /** The page is visible again (a repeated "visible" keeps the time since the last activity). */
  show(now = Date.now()): void {
    if (this.last === null) this.last = now;
  }

  /** Whole seconds spent on a question (1 to MAX_SECONDS), or null when there was none. */
  seconds(question: string, now = Date.now()): number | null {
    if (this.last !== null) this.touch(null, now);
    const s = Math.round((this.ms.get(question) ?? 0) / 1000);
    return s >= 1 ? Math.min(s, MAX_SECONDS) : null;
  }

  /** Seconds per question for every question with time on it. */
  all(now = Date.now()): Record<string, number> {
    if (this.last !== null) this.touch(null, now);
    const out: Record<string, number> = {};
    for (const id of this.ms.keys()) {
      const s = this.seconds(id, now);
      if (s !== null) out[id] = s;
    }
    return out;
  }
}

const ACTIVITY = ["keydown", "input", "pointerdown", "pointermove", "wheel", "scroll", "focusin", "change"] as const;

/**
 * Wires a clock to a document: activity anywhere counts, attributed by questionOf (e.g. the nearest
 * [data-question-id]); hiding the page pauses the clock. Returns a function that removes the listeners.
 */
export function watchActivity(
  clock: AnswerClock,
  doc: Document,
  questionOf: (target: EventTarget | null) => string | null = () => null,
): () => void {
  const onActivity = (e: Event) => {
    if (doc.visibilityState === "hidden") return;
    clock.touch(questionOf(e.target));
  };
  const onVisibility = () => (doc.visibilityState === "hidden" ? clock.hide() : clock.show());
  ACTIVITY.forEach((type) => doc.addEventListener(type, onActivity, { capture: true, passive: true }));
  doc.addEventListener("visibilitychange", onVisibility);
  if (doc.visibilityState === "hidden") clock.hide();
  return () => {
    ACTIVITY.forEach((type) => doc.removeEventListener(type, onActivity, { capture: true }));
    doc.removeEventListener("visibilitychange", onVisibility);
  };
}

/** The question an event belongs to: the nearest element with data-question-id. */
export function questionOfTarget(target: EventTarget | null): string | null {
  const el = target instanceof Element ? target.closest("[data-question-id]") : null;
  return el?.getAttribute("data-question-id") ?? null;
}
