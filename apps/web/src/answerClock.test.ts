import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerClock, MAX_SECONDS, PAUSE_MS, questionOfTarget, watchActivity } from "./answerClock";

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("answer clock (ADR-014 §3)", () => {
  it("counts the time between moments of activity and skips pauses over five minutes", () => {
    const clock = new AnswerClock({}, 0, "q1");
    clock.touch(null, 60_000); // a minute reading, then typing
    clock.touch(null, 90_000);
    clock.touch(null, 90_000 + PAUSE_MS + 1); // away for more than five minutes: nothing counts
    clock.touch(null, 90_000 + PAUSE_MS + 10_001);
    expect(clock.seconds("q1", 90_000 + PAUSE_MS + 10_001)).toBe(100);
  });

  it("does not count while the page is hidden", () => {
    const clock = new AnswerClock({}, 0, "q1");
    clock.hide(20_000);
    clock.show(200_000);
    clock.show(210_000); // visible twice in a row: the 10 s since the first still count
    expect(clock.seconds("q1", 230_000)).toBe(50);
  });

  it("gives each gap to the question worked on, starts from a draft and caps at two hours", () => {
    const clock = new AnswerClock({ a: 30 }, 0);
    clock.touch("a", 10_000);
    clock.touch("b", 25_000);
    clock.touch(null, 30_000); // still on b
    expect(clock.all(30_000)).toEqual({ a: 40, b: 20 });
    expect(new AnswerClock({}, 0).seconds("a", 500)).toBeNull();
    expect(new AnswerClock({ a: 9000 }, 0).seconds("a", 0)).toBe(MAX_SECONDS);
  });

  it("listens to the page and finds the question of an event", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const card = document.createElement("div");
    card.setAttribute("data-question-id", "q2");
    const box = document.createElement("textarea");
    card.appendChild(box);
    document.body.appendChild(card);
    const clock = new AnswerClock({}, Date.now());
    const stop = watchActivity(clock, document, questionOfTarget);
    vi.setSystemTime(40_000);
    box.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true }));
    expect(clock.seconds("q2")).toBe(40);
    stop();
    vi.setSystemTime(41_000);
    box.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true }));
    vi.setSystemTime(400_000); // no longer listening: only the second from the last call counts
    expect(clock.seconds("q2", 41_000)).toBe(41);
  });
});
