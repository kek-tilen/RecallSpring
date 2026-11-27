import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { assistantWords, useAssistant, type AssistantWords } from "../assistant";
import { EventList } from "./History";
import { StudyIn } from "../components/StudyIn";
import { Upload } from "../components/Upload";
import { WaitingForGrade } from "../components/WaitingForGrade";
import { Async, Card, Empty, StudyChip } from "../components/ui";
import { longToday, nextDays, plural, shortDay } from "../format";
import { useCourses, useDashboard, useDueCount, useFocusSummary, useSession } from "../queries";
import { CourseDot, cc } from "../components/organise";
import { usePomodoro } from "../components/Pomodoro";
import type { AttentionItem, Dashboard, FocusSummary, PlanItem, TargetCapacity } from "../types";

// Home (ADR-012, owner 2026-11-23: variants A1 + A2): a calm two-column top (greeting, one sentence, one next step,
// the week) and "Today in detail" below, open by default. No streaks or other pressure counters.

const CATEGORY_TONE: Record<PlanItem["category"], string> = {
  "Learn next": "chip solid",
  "Review due": "chip warn",
  Relearn: "chip warn",
  Strengthen: "chip warn",
  Practice: "chip good",
  Maintain: "chip",
};

const CAPACITY: Record<TargetCapacity["status"], { tone: string; label: string }> = {
  ok: { tone: "chip good", label: "On track" },
  tight: { tone: "chip warn", label: "Tight" },
  at_risk: { tone: "chip bad", label: "At risk" },
};

function attentionLink(a: AttentionItem): string {
  if (a.kind === "source" && a.id) return `/library/${a.id}`;
  if (a.kind === "quiz" && a.id) return `/simulations/${a.id}`;
  if (a.kind === "duplicates") return "/exams";
  if (a.kind === "backup") return "/settings#backups";
  if (a.kind === "cloud") return "/settings#cloud-copy";
  if (a.kind === "export") return "/settings#export";
  if (a.kind === "drive") return "/settings#drive";
  return "/history";
}

/** How to start, for the assistant chosen in Settings → Profile. */
function firstCourseHint(a: AssistantWords): ReactNode {
  switch (a.key) {
    case "claude":
      return (
        <>
          Start with a planning chat in Claude: tell it your courses, midterm and exam dates, scope and material. The{" "}
          <Link to="/guide">Guide</Link> has prompts to copy. Everything Claude saves appears here.
        </>
      );
    case "codex":
    case "antigravity":
      return (
        <>
          Open the Planning folder (Documents\RecallSpring Study) in {a.name} and tell it your courses, midterm and exam dates, scope and
          material. The <Link to="/guide">Guide</Link> has prompts to copy. Everything {a.name} saves appears here.
        </>
      );
    case "chatgpt":
      return (
        <>
          Add your material under <Link to="/library">Library</Link>, then start a <strong>Planning</strong> conversation in{" "}
          <Link to="/chat">Chat</Link> and tell ChatGPT your courses, midterm and exam dates, scope and material. The <Link to="/guide">Guide</Link>{" "}
          has prompts to copy.
        </>
      );
    default:
      return (
        <>
          <Link to="/welcome">Choose your assistant</Link> to see how to start: it sets up your courses and midterm and exam dates with you.
          Your material goes under <Link to="/library">Library</Link>.
        </>
      );
  }
}

function continueHint(a: AssistantWords, course: string): ReactNode {
  switch (a.key) {
    case "claude":
      return (
        <>
          Open the <strong>{course}</strong> project in Claude and say “Start studying”.
        </>
      );
    case "codex":
    case "antigravity":
      return (
        <>
          Open the <strong>{course}</strong> folder in {a.name} and say “Start studying”.
        </>
      );
    case "chatgpt":
      return (
        <>
          In <Link to="/chat">Chat</Link>, pick <strong>{course}</strong> under Study and say “Start studying”.
        </>
      );
    default:
      return (
        <>
          Study <strong>{course}</strong> with your assistant: say “Start studying”.
        </>
      );
  }
}

/** Good morning / afternoon / evening by the learner's clock, with the name they chose in Settings (if any). */
export function greeting(hour: number, name?: string | null): string {
  const base = hour >= 5 && hour < 12 ? "Good morning" : hour >= 12 && hour < 18 ? "Good afternoon" : "Good evening";
  return name?.trim() ? `${base}, ${name.trim()}` : base;
}

function inDays(n: number): string {
  if (n <= 0) return "today";
  if (n === 1) return "tomorrow";
  return `in ${n} days`;
}

/** "today", "tomorrow" or "Mon 30 Nov". */
function when(t: TargetCapacity): string {
  return t.days_left <= 1 ? inDays(t.days_left) : shortDay(t.due_date);
}

/** One sentence about today: the nearest exam or midterm and today's work. */
export function todaySentence(d: Dashboard): string {
  const next = [...d.plan.targets].filter((t) => t.days_left >= 0).sort((x, y) => x.days_left - y.days_left)[0];
  const exam = next ? `${next.target} in ${next.course_title} is ${inDays(next.days_left)}.` : "";
  const work =
    d.plan.items.length === 0
      ? "Nothing is planned for today, so you're free to explore."
      : `Today's plan is about ${d.plan.planned_minutes} minutes.`;
  return exam ? `${exam} ${work}` : work;
}

const SHORT_TAG: Record<PlanItem["category"], string> = {
  "Learn next": "Learn",
  "Review due": "Review",
  Relearn: "Try again",
  Strengthen: "Strengthen",
  Practice: "Practise",
  Maintain: "Keep fresh",
};

/** Due reviews, including a weak concept's next try before its exam (ADR-014). */
export function isReview(item: PlanItem): boolean {
  return item.category === "Review due" || item.category === "Relearn";
}

/** ADR-013 §4: the exam a plan item works towards, for a quiet "Why?" link to Why this plan on its Readiness page. */
export function examFor(d: Dashboard, item: PlanItem): TargetCapacity | null {
  if (!item.target) return null;
  return d.plan.targets.find((t) => t.course_id === item.course_id && t.target === item.target) ?? null;
}

function WhyLink({ exam }: { exam: TargetCapacity }) {
  return (
    <Link to={`/exams/${exam.target_id}#why`} className="muted" aria-label={`Why this plan for ${exam.target} in ${exam.course_title}`}>
      Why?
    </Link>
  );
}

/** The next step: one primary button beside "Go through today's plan in…" (UI direction, 2026-11-27). */
function NextStep({ item, a: inUse }: { item: PlanItem; a: AssistantWords }) {
  // A course's "Usually studied in" (2026-11-27) names that assistant for it; otherwise the one in use.
  const courses = useCourses().data;
  const usual = Array.isArray(courses) ? courses.find((c) => c.id === item.course_id)?.usually_studied_in : null;
  const a = usual ? assistantWords(usual) : inUse;
  const button = isReview(item)
    ? { to: "/review", label: "Start reviews" }
      : a.key === "chatgpt"
        ? { to: "/chat", label: "Open Chat" }
        : { to: `/concepts/${item.concept_id}`, label: "Open concept" };
  return (
    <section className="home-next" aria-label="Next step">
      <div className="home-actions">
        <Link to={button.to} className="btn primary">
          {button.label}
        </Link>
        <StudyIn />
      </div>
      {!isReview(item) && <p className="small muted">{continueHint(a, item.course_title)}</p>}
    </section>
  );
}

/** Today's plan, quietly: the first few items as "term · course · kind" with their minutes. The full plan is below. */
function TodayPlan({ items }: { items: PlanItem[] }) {
  if (items.length === 0) return null;
  return (
    <section className="home-plan" aria-labelledby="home-plan-title">
      <h2 id="home-plan-title" className="home-h">
        Today's plan
      </h2>
      <ul>
        {items.map((i) => (
          <li key={`${i.category}-${i.concept_id}`}>
            <span className="home-plan-what">
              <Link to={`/concepts/${i.concept_id}`}>{i.term}</Link>
              <span className="muted">
                {" "}
                · {i.course_title} · {SHORT_TAG[i.category].toLowerCase()}
              </span>
            </span>
            <span className="chip home-mins">{i.estimated_minutes} min</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });

/**
 * The next seven days from today (the strip opens the weekly review), reviews due today, minutes focused, and the
 * exams ahead with their status. Exams are marked in their course's colour (UI direction, 2026-11-27).
 */
function WeekPanel({ d, focus }: { d: Dashboard; focus: FocusSummary | undefined }) {
  const colors = new Map((useCourses().data ?? []).map((c) => [c.id, c.color]));
  const days = nextDays(7);
  const ahead = d.plan.targets.filter((t) => t.days_left >= 0).sort((x, y) => x.days_left - y.days_left);
  const due = useDueCount();
  return (
    <section className="home-week" aria-labelledby="home-week-title">
      <h2 id="home-week-title" className="home-h">
        This week
      </h2>
      {/* The strip opens the weekly review, Today's second view. */}
      <Link to="/week" className="home-strip-link" aria-label="Weekly review">
      <ol className="home-strip">
        {days.map((day, i) => {
          const dates = d.plan.targets.filter((t) => t.due_date.slice(0, 10) === day);
          const label = `${shortDay(day)}${dates.length ? `: ${dates.map((t) => `${t.target}, ${t.course_title}`).join("; ")}` : ""}`;
          return (
            <li key={day} className={i === 0 ? "today" : undefined} aria-label={label} title={label}>
              <span className="home-strip-wd" aria-hidden="true">
                {WEEKDAY.format(new Date(`${day}T00:00:00Z`)).slice(0, 2)}
              </span>
              <span className="home-strip-d" aria-hidden="true">
                {Number(day.slice(8, 10))}
              </span>
              <span className="home-strip-dot" aria-hidden="true">
                {dates.slice(0, 2).map((t) => (
                  <span key={t.target_id} className={`course-dot ${cc(colors.get(t.course_id))}`} />
                ))}
              </span>
            </li>
          );
        })}
      </ol>
      </Link>
      <ul className="home-rows">
        <li>
          <Link to="/review">Reviews today</Link>
          <span className="muted">{due}</span>
        </li>
        <li>
          <Link to="/focus">Focused this week</Link>
          <span className="muted">{focus ? `${focus.week_minutes} min` : "–"}</span>
        </li>
      </ul>
      {ahead.length > 0 && (
        <>
          <h3 className="home-h home-week-sub">Exams</h3>
          <ul className="home-rows home-exams">
            {ahead.slice(0, 4).map((t) => (
              <li key={t.target_id}>
                <span className="home-exam">
                  <CourseDot color={colors.get(t.course_id)} />
                  <Link to={`/exams/${t.target_id}`}>
                    <span className="home-exam-what">
                      {t.target} · {when(t)}
                    </span>
                    <span className="muted small home-exam-course">{t.course_title}</span>
                  </Link>
                </span>
                <span className={CAPACITY[t.status].tone}>{CAPACITY[t.status].label}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

const DETAIL_KEY = "rs.home.detail";

/** "Today in detail": open unless the learner hid it (remembered on this device); mounted only when open. */
function Detail({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(DETAIL_KEY) !== "hidden";
    } catch {
      return true;
    }
  });
  const toggle = () => {
    const now = !open;
    setOpen(now);
    try {
      localStorage.setItem(DETAIL_KEY, now ? "open" : "hidden");
    } catch {
      /* storage blocked: not remembered */
    }
  };
  return (
    <section className="home-detail" aria-labelledby="home-detail-title">
      <div className="home-detail-head">
        <h2 id="home-detail-title">Today in detail</h2>
        <button type="button" className="btn ghost small" aria-expanded={open} aria-controls="home-detail-body" onClick={toggle}>
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <div id="home-detail-body" className="home-detail-body">
          {children}
        </div>
      )}
    </section>
  );
}

function PlanCard({ d }: { d: Dashboard }) {
  return (
    <Card title="Full plan" meta={`${d.plan.planned_minutes} of ${d.plan.available_minutes} min`}>
      {d.plan.message && <p className="notice small" style={{ marginBottom: 12 }}>{d.plan.message}</p>}
      {d.plan.focus && (
        <p className="notice small" style={{ marginBottom: 12 }}>
          {d.plan.focus.message}
        </p>
      )}
      {d.plan.interests && !d.plan.focus && (
        <p className="notice small muted" style={{ marginBottom: 12 }}>
          {d.plan.interests.message} <Link to="/settings">Change in Settings</Link>
        </p>
      )}
      {d.plan.items.length === 0 ? (
        <p className="muted">You're caught up. Continue a topic or browse your library.</p>
      ) : (
        <ul className="list">
          {d.plan.items.map((item) => (
            <li key={`${item.category}-${item.concept_id}`} className="plan-item">
              <span className={CATEGORY_TONE[item.category]}>{item.category}</span>
              <div>
                <div className="row">
                  <Link to={`/concepts/${item.concept_id}`} style={{ fontWeight: 600 }}>
                    {item.term}
                  </Link>
                  <StudyChip status={item.study_status} />
                  {item.focus ? (
                    <span className="chip solid">Focus</span>
                  ) : (
                    item.course_kind === "interest" && <span className="chip">Interest</span>
                  )}
                </div>
                <div className="why">
                  {item.course_title}
                  {item.target && ` · ${item.target}`} — {item.why_selected}
                </div>
                {item.sections.length > 0 && (
                  <div className="tiny muted">{item.sections.map((s) => `${s.filename} ${s.citation_label}`).join(" · ")}</div>
                )}
              </div>
              <div className="plan-side">
                <span className="muted small">
                  {item.estimated_minutes} min{item.depth === "quick" ? " · quick check" : ""}
                </span>
                <StartFocus courseId={item.course_id} course={item.course_title} />
              </div>
            </li>
          ))}
        </ul>
      )}
      <WhyLinks d={d} />
      {d.plan.note && (
        <p className="tiny muted" style={{ marginTop: 12 }}>
          {d.plan.note}
        </p>
      )}
    </Card>
  );
}

/** One quiet "Why?" per exam that today's plan works towards. */
function WhyLinks({ d }: { d: Dashboard }) {
  const exams: TargetCapacity[] = [];
  for (const item of d.plan.items) {
    const exam = examFor(d, item);
    if (exam && !exams.some((e) => e.target_id === exam.target_id)) exams.push(exam);
  }
  if (exams.length === 0) return null;
  return (
    <p className="tiny muted" style={{ marginTop: 12 }}>
      Why this plan:{" "}
      {exams.map((e, i) => (
        <span key={e.target_id}>
          {i > 0 && " · "}
          <Link to={`/exams/${e.target_id}#why`}>
            {e.target}, {e.course_title}
          </Link>
        </span>
      ))}
    </p>
  );
}

function ExamsCard({ targets }: { targets: TargetCapacity[] }) {
  return (
    <Card title="Exams and midterms" action={<Link to="/exams" className="small">All</Link>}>
      {targets.length === 0 ? (
        <p className="muted small">No dates yet. Your assistant adds them when you plan a course.</p>
      ) : (
        <ul className="list">
          {targets.map((t) => (
            <li key={t.target_id} className="stack" style={{ gap: 4 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <Link to={`/courses/${t.course_id}?tab=targets`} style={{ fontWeight: 600 }}>
                  {t.course_title}
                </Link>
                <span className={CAPACITY[t.status].tone}>{CAPACITY[t.status].label}</span>
              </div>
              <div className="small muted">
                {t.target} · {when(t)} · {plural(t.concepts_in_scope, "concept")}
              </div>
              <div className="small">{t.message}</div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AttentionCard({ items }: { items: AttentionItem[] }) {
  return (
    <Card title="Needs attention">
      {items.length === 0 ? (
        <p className="muted small">Nothing needs you right now.</p>
      ) : (
        <ul className="list">
          {items.map((a, i) => (
            <li key={`${a.kind}-${a.id ?? i}`}>
              <Link to={attentionLink(a)} style={{ fontWeight: 600 }}>
                {a.title}
              </Link>
              {a.text && <div className="small muted">{a.text}</div>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const HOLDS = [
  ["courses", "course", "/courses"],
  ["sources", "material", "/library"],
  ["concepts", "concept", "/courses"],
  ["notes", "note", "/notes"],
  ["answers", "answer", "/history"],
  ["simulations", "simulation", "/simulations"],
] as const;

function Holds({ counts }: { counts: Dashboard["counts"] }) {
  return (
    <p className="home-holds small muted">
      What RecallSpring holds:{" "}
      {HOLDS.map(([k, word, to], i) => (
        <span key={k}>
          {i > 0 && " · "}
          <Link to={to}>{plural(counts[k], word)}</Link>
        </span>
      ))}
    </p>
  );
}

export function HomePage() {
  const q = useDashboard();
  const a = useAssistant();
  const focus = useFocusSummary();
  const name = useSession().data?.user.greeting_name;
  return (
    <div className="page">
      <Async q={q} lines={6}>
        {(d) => {
          const started = d.counts.courses > 0;
          const next = d.plan.items[0];
          return (
            <>
              <div className={started ? "home-top" : "home-top single"}>
                <header className="home-hello">
                  <p className="home-date">{longToday()}</p>
                  <h1 className="home-greeting">{greeting(new Date().getHours(), name)}</h1>
                  {started && (
                    <p className="home-sentence">
                      {todaySentence(d)}
                      {next && examFor(d, next) && (
                        <span className="small">
                          {" "}
                          <WhyLink exam={examFor(d, next)!} />
                        </span>
                      )}
                    </p>
                  )}
                  {a.key === null && started && (
                    <p className="home-quiet small">
                      Which assistant do you study with? <Link to="/welcome">Choose it</Link>
                    </p>
                  )}
                  {started && next && <NextStep item={next} a={a} />}
                  {started && <WaitingForGrade />}
                  {started && <TodayPlan items={d.plan.items.slice(0, 5)} />}
                </header>
                {started && <WeekPanel d={d} focus={focus.data} />}
              </div>

              {!started && <Empty title="Add your first course">{firstCourseHint(a)}</Empty>}

              <Detail>
                {started && (
                  <div className="home-detail-split">
                    <PlanCard d={d} />
                    <ExamsCard targets={d.plan.targets} />
                  </div>
                )}
                <div className="grid cols-3">
                  {/* On phones only this card stays, and only when something needs attention. */}
                  <div className={d.attention.length ? "home-attn" : "home-attn empty"}>
                    <AttentionCard items={d.attention} />
                  </div>
                  <Card title="Recent activity" action={<Link to="/history" className="small">All</Link>}>
                    <EventList rows={d.recent.slice(0, 4)} compact />
                  </Card>
                  <Card title="Add material">
                    <Upload />
                  </Card>
                </div>
                <Holds counts={d.counts} />
              </Detail>
            </>
          );
        }}
      </Async>
    </div>
  );
}

/** Starts a Pomodoro focus block for this item's course at once and shows only the timer. */
function StartFocus({ courseId, course }: { courseId: string; course: string }) {
  const p = usePomodoro();
  const busy = p.run.status === "running" && p.run.phase === "focus" && p.run.courseId === courseId;
  return (
    <button
      type="button"
      className="btn small"
      aria-label={busy ? `Show the focus timer for ${course}` : `Start focus on ${course}`}
      onClick={() => p.startFocus(courseId)}
    >
      {busy ? "Show focus" : "Start focus"}
    </button>
  );
}
