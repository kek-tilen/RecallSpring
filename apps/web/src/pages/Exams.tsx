import { useMutation } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { API, request } from "../api";
import { CourseDot, cc, groupPath, useInvalidateOrganisation } from "../components/organise";
import { DuplicatesPanel, RecentlyDeleted } from "../components/ExamCleanup";
import { StudyIn } from "../components/StudyIn";
import { TargetDialog } from "../components/TargetDialog";
import { Async, Chevron, Empty, ErrorNote, PageHead, SectionMenu } from "../components/ui";
import { addDays, dateLabel, daysBetween, plural, shortDay, todayIso } from "../format";
import { useCourses, useGroups, useReadiness, useTargets } from "../queries";
import type { ExamReadiness, Target, TimelineTarget } from "../types";
import { MiniReadiness } from "./Readiness";

// Exams as drawn (UI direction, 2026-11-27): a timeline from two weeks back to about five weeks ahead (each exam in
// its course's colour, passed ones hollow, today dashed), the list, and the selected exam's readiness with Study in…
// beside each weak topic. The timeline only shows dates; a date is changed on the exam itself (Edit).

const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const shortDate = (iso: string) => SHORT.format(new Date(`${iso}T00:00:00Z`));
const isBehind = (t: Target) => t.status === "passed" || t.status === "cancelled";
const STATUS_WORD: Record<string, string> = { passed: "passed", failed: "not passed yet", cancelled: "cancelled" };
const CAPACITY = {
  ok: { tone: "chip tint-chip", label: "On track" },
  tight: { tone: "chip warn", label: "Tight" },
  at_risk: { tone: "chip bad", label: "At risk" },
} as const;

function daysWord(n: number): string {
  if (n < 0) return "passed";
  if (n === 0) return "today";
  return plural(n, "day");
}

/** The SVG is drawn at the width it gets, so its 11 px labels stay 11 px on a phone and on a wide screen. */
function useWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(280, Math.round(el.getBoundingClientRect().width) || fallback));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, width];
}

export function Timeline({ targets }: { targets: TimelineTarget[] }) {
  const [box, W] = useWidth(600);
  const today = todayIso();
  const start = addDays(today, -14);
  const lastUpcoming = targets
    .filter((t) => t.due_date >= today && !isBehind(t))
    .map((t) => t.due_date)
    .sort()
    .at(-1);
  let end = addDays(today, 35);
  if (lastUpcoming && addDays(lastUpcoming, 5) > end) end = [addDays(lastUpcoming, 5), addDays(today, 84)].sort()[0]!;
  const span = daysBetween(start, end);
  const pad = 20;
  const x = (iso: string) => pad + (daysBetween(start, iso) / span) * (W - 2 * pad);
  const shown = targets.filter((t) => t.due_date >= start && t.due_date <= end).sort((a, b) => a.due_date.localeCompare(b.due_date));

  // Labels sit above their dot; one that would cover the previous one moves up a line.
  const right = [-Infinity, -Infinity];
  const placed = shown.map((t) => {
    const text = isBehind(t) ? `${t.name} · ${STATUS_WORD[t.status]}` : `${t.name} · ${t.course_title}`;
    const width = text.length * 5.6;
    const cx = x(t.due_date);
    const lx = Math.min(Math.max(cx, width / 2 + 2), W - width / 2 - 2);
    let lane = right.findIndex((r) => lx - width / 2 > r + 8);
    if (lane === -1) lane = right[0]! <= right[1]! ? 0 : 1;
    right[lane] = lx + width / 2;
    return { t, text, cx, lx, lane };
  });
  const top = placed.some((p) => p.lane === 1) ? 16 : 0;
  const axis = 50 + top;
  const ticks: string[] = [];
  const step = W < 480 ? 14 : 7;
  for (let i = 0; i <= span; i += step) ticks.push(addDays(start, i));
  const label =
    `Timeline from ${dateLabel(start)} to ${dateLabel(end)}: ` +
    [
      ...shown.map((t) => `${t.name}, ${t.course_title}, ${isBehind(t) ? `${STATUS_WORD[t.status]} on` : "on"} ${dateLabel(t.due_date)}`),
      `today ${dateLabel(today)}`,
    ].join("; ");

  return (
    <div ref={box} className="exam-timeline">
      <svg width={W} height={axis + 26} viewBox={`0 0 ${W} ${axis + 26}`} role="img" aria-label={label}>
        <line x1={pad} y1={axis} x2={W - pad} y2={axis} className="tl-axis-line" />
        {ticks.map((d) => (
          <g key={d}>
            <line x1={x(d)} y1={axis - 4} x2={x(d)} y2={axis + 4} className="tl-tick" />
            {Math.abs(x(d) - x(today)) > 30 && (
              <text x={x(d)} y={axis + 20} className="tl-tick-label" textAnchor="middle">
                {shortDate(d)}
              </text>
            )}
          </g>
        ))}
        <line x1={x(today)} y1={axis - 30 - top} x2={x(today)} y2={axis + 8} className="tl-today-line" />
        <text x={x(today)} y={axis + 20} className="tl-today-label" textAnchor="middle">
          Today
        </text>
        {placed.map(({ t, text, cx, lx, lane }) => (
          <g key={t.id} className={cc(t.course_color)}>
            {isBehind(t) ? (
              <circle cx={cx} cy={axis} r={6} className="tl-dot hollow" />
            ) : (
              <circle cx={cx} cy={axis} r={7} className="tl-dot" />
            )}
            <text x={lx} y={axis - 16 - lane * 16} textAnchor="middle" className={isBehind(t) ? "tl-name past" : "tl-name"}>
              {text}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function ExamRow({ t, on, pick }: { t: TimelineTarget; on: boolean; pick: () => void }) {
  const r = useReadiness(t.id);
  const cap = !isBehind(t) && r.data?.capacity ? CAPACITY[r.data.capacity.status] : null;
  return (
    <li>
      <button type="button" className={on ? "exam-row on" : "exam-row"} aria-pressed={on} onClick={pick}>
        <span className="exam-row-name">
          <span className="exam-row-title">
            <CourseDot color={t.course_color} />
            {t.name}
          </span>
          <span className="small muted">
            {t.course_title} · {shortDay(t.due_date)} · {isBehind(t) ? STATUS_WORD[t.status] + (t.result ? ` (${t.result})` : "") : daysWord(t.days_left)}
          </span>
        </span>
        <span className="row" style={{ gap: 6 }}>
          {(t.duplicates?.length ?? 0) > 0 && <span className="chip warn">Possible duplicate</span>}
          {t.status === "failed" && <span className="chip warn">Retake</span>}
          {cap && <span className={cap.tone}>{cap.label}</span>}
        </span>
      </button>
    </li>
  );
}

/** What to work on first: the weakest graded concepts, then those not studied yet (in the order of the material). */
function weakestFirst(r: ExamReadiness): { id: string; term: string; why: string; where: string | undefined }[] {
  const weak = r.weakest.map((w) => ({ id: w.id, term: w.term, why: (w.gaps[0] ?? w.reason).replace(/\.$/, ""), where: w.citations[0] }));
  const seen = new Set(weak.map((w) => w.id));
  const unread = r.groups
    .flatMap((g) => g.concepts)
    .filter((c) => c.state === "not_studied" && !seen.has(c.id))
    .map((c) => ({ id: c.id, term: c.term, why: "Not studied yet", where: c.citations[0] }));
  return [...weak, ...unread].slice(0, 5);
}

function countsLine(s: ExamReadiness["summary"]): string {
  return [
    s.not_studied && `${s.not_studied} not studied`,
    s.weak && `${s.weak} weak`,
    s.not_practised && `${s.not_practised} studied`,
    s.developing && `${s.developing} getting there`,
    s.solid && `${s.solid} solid`,
  ]
    .filter(Boolean)
    .join(" · ");
}

function ExamDetail({ t, onEdit }: { t: TimelineTarget; onEdit: () => void }) {
  const q = useReadiness(t.id);
  const course = { id: t.course_id, title: t.course_title };
  return (
    <section className="exam-detail" aria-labelledby="exam-detail-title">
      <div className="exam-detail-head">
        <div style={{ minWidth: 0 }}>
          <div className="small muted">
            {t.course_title} · {isBehind(t) ? `${STATUS_WORD[t.status]} · ${dateLabel(t.due_date)}` : t.days_left >= 0 ? `${daysWord(t.days_left)} left` : "date passed"}
          </div>
          <h2 id="exam-detail-title" className="exam-detail-title">
            {t.name}
          </h2>
        </div>
        <span className="row" style={{ gap: 4 }}>
          <button type="button" className="btn small ghost" onClick={onEdit}>
            Edit
          </button>
          <Link to={`/exams/${t.id}`} className="btn small ghost">
            Full readiness
          </Link>
        </span>
      </div>
      <Async q={q} lines={4}>
        {(r) => {
          const first = weakestFirst(r);
          return (
            <>
              <MiniReadiness counts={r.summary} label={`Readiness for ${t.name}`} />
              <p className="small muted exam-counts">{countsLine(r.summary) || "No concepts in scope yet"}</p>
              {r.capacity && !isBehind(t) && <p className="small">{r.capacity.message}</p>}
              {!isBehind(t) && first.length > 0 && (
                <>
                  <h3 className="exam-weak-h">Weakest first</h3>
                  <ul className="source-rows" aria-label="Weakest first">
                    {first.map((w) => (
                      <li key={w.id} className="source-row">
                        <span className="source-row-name">
                          <Link to={`/concepts/${w.id}`}>{w.term}</Link>
                          <span className="small muted">{[w.why, w.where].filter(Boolean).join(" · ")}</span>
                        </span>
                        <StudyIn
                          course={course}
                          ask={{
                            label: "Study",
                            message: `Help me with "${w.term}" in ${t.course_title} for ${t.name} (${dateLabel(t.due_date)}). ${w.why}${w.where ? ` (${w.where})` : ""}.`,
                          }}
                        />
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="tiny muted exam-why">
                <Link to={`/exams/${t.id}#why`}>Why this plan</Link> · not a prediction of your grade
              </p>
            </>
          );
        }}
      </Async>
    </section>
  );
}

export function ExamsPage() {
  const q = useTargets();
  const groups = useGroups();
  const courses = useCourses();
  const refresh = useInvalidateOrganisation();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState<TimelineTarget | null>(null);
  const [adding, setAdding] = useState(false);
  const [behindOpen, setBehindOpen] = useState(false);
  const [calendarGroup, setCalendarGroup] = useState("");
  const [deleted, setDeleted] = useState<Target | null>(null);
  const restore = useMutation({
    mutationFn: (id: string) => request(`/targets/${id}/restore`, { method: "POST" }),
    onSuccess: () => {
      setDeleted(null);
      refresh();
    },
  });
  useEffect(() => {
    if (!deleted) return;
    const id = window.setTimeout(() => setDeleted(null), 9000);
    return () => window.clearTimeout(id);
  }, [deleted]);

  const archivedCourses = new Set((courses.data ?? []).filter((c) => c.status === "archived").map((c) => c.id));
  const semesters = (groups.data ?? []).filter((g) => g.status === "active");

  return (
    <div className="page exams-page">
      <PageHead title="Exams">
        <button type="button" className="btn" onClick={() => setAdding(true)} disabled={!courses.data?.length}>
          + Add exam
        </button>
        <SectionMenu label="Calendar">
          {semesters.length > 0 && (
            <label className="field small">
              Calendar for
              <select value={calendarGroup} onChange={(e) => setCalendarGroup(e.target.value)}>
                <option value="">All courses</option>
                {semesters.map((g) => (
                  <option key={g.id} value={g.id}>
                    {groupPath(groups.data, g.id)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <a className="btn small ghost" href={`${API}/calendar.ics${calendarGroup ? `?group_id=${calendarGroup}` : ""}`} download>
            Download calendar (.ics)
          </a>
        </SectionMenu>
      </PageHead>
      <Async q={q} lines={5}>
        {(all) => {
          const mine = all.filter((t) => !archivedCourses.has(t.course_id));
          const coming = mine.filter((t) => !isBehind(t)).sort((a, b) => a.due_date.localeCompare(b.due_date));
          const behind = mine.filter(isBehind).sort((a, b) => b.due_date.localeCompare(a.due_date));
          const picked = mine.find((t) => t.id === params.get("exam")) ?? coming[0] ?? behind[0];
          const pick = (t: TimelineTarget) => setParams({ exam: t.id }, { replace: true });
          if (mine.length === 0) {
            return (
              <Empty title="No exams yet">
                Add one here, or plan your semester in a planning chat with your assistant (see the Guide) to set up all your midterms and exams at once.
              </Empty>
            );
          }
          const passed = behind.filter((t) => t.status === "passed").length;
          return (
            <>
              <DuplicatesPanel targets={mine} />
              <Timeline targets={mine} />
              <div className="exams-layout">
                <div>
                  <div className="exams-label">Coming up</div>
                  {coming.length === 0 ? (
                    <p className="small muted">Nothing coming up. Add the next midterm or exam with + Add exam.</p>
                  ) : (
                    <ul className="exam-rows" aria-label="Coming up">
                      {coming.map((t) => (
                        <ExamRow key={t.id} t={t} on={t.id === picked?.id} pick={() => pick(t)} />
                      ))}
                    </ul>
                  )}
                  {behind.length > 0 && (
                    <>
                      <button type="button" className="exams-label exams-behind" aria-expanded={behindOpen} onClick={() => setBehindOpen(!behindOpen)}>
                        <Chevron open={behindOpen} />
                        Behind you
                        <span className="group-count">{passed > 0 ? `${passed} passed` : plural(behind.length, "exam")}</span>
                      </button>
                      {behindOpen && (
                        <ul className="exam-rows" aria-label="Behind you">
                          {behind.map((t) => (
                            <ExamRow key={t.id} t={t} on={t.id === picked?.id} pick={() => pick(t)} />
                          ))}
                        </ul>
                      )}
                    </>
                  )}
                </div>
                {picked && <ExamDetail key={picked.id} t={picked} onEdit={() => setEditing(picked)} />}
              </div>
              <RecentlyDeleted />
            </>
          );
        }}
      </Async>
      {restore.error && <ErrorNote error={restore.error} />}
      {editing && (
        <TargetDialog
          key={editing.id + editing.revision}
          target={editing}
          open
          onClose={() => setEditing(null)}
          onDeleted={(t) => setDeleted(t)}
        />
      )}
      {deleted && (
        <div className="toast" role="status">
          Deleted {deleted.name}.
          <button type="button" className="btn small" onClick={() => restore.mutate(deleted.id)} disabled={restore.isPending}>
            Undo
          </button>
        </div>
      )}
      {adding && <TargetDialog open onClose={() => setAdding(false)} />}
    </div>
  );
}
