import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Link } from "react-router";
import { API, request } from "../api";
import { CourseDot, cc, groupPath, useInvalidateOrganisation } from "../components/organise";
import { DuplicatesPanel, RecentlyDeleted } from "../components/ExamCleanup";
import { TargetDialog } from "../components/TargetDialog";
import { Async, Empty, ErrorNote, PageHead } from "../components/ui";
import { TARGET_KIND, addDays, dateLabel, daysBetween, plural, todayIso } from "../format";
import { useCourses, useGroups, useTargets } from "../queries";
import type { Target, TimelineTarget } from "../types";

const DAY = 14; // pixels per day: about four months fit on a laptop screen
const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const MONTH = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });

function shortDate(iso: string): string {
  return SHORT.format(new Date(`${iso}T00:00:00Z`));
}

interface Moved {
  target: TimelineTarget;
  from: string;
  to: string;
}

const LANE = 38; // vertical step between markers that would overlap in one row
const MARKER_WIDTH = 130; // approximate pill width, used only to decide overlaps

/** Lane per target so markers close in time sit on separate lines instead of covering each other. */
function lanes(list: TimelineTarget[], start: string): Map<string, number> {
  const ends: number[] = [];
  const out = new Map<string, number>();
  for (const t of [...list].sort((a, b) => a.due_date.localeCompare(b.due_date))) {
    const left = daysBetween(start, t.due_date) * DAY;
    let lane = ends.findIndex((end) => end <= left);
    if (lane === -1) lane = ends.length;
    ends[lane] = left + MARKER_WIDTH;
    out.set(t.id, lane);
  }
  return out;
}

function Marker({ t, start, lane, onMove, onEdit }: {
  t: TimelineTarget;
  start: string;
  lane: number;
  onMove: (t: TimelineTarget, to: string) => void;
  onEdit: (t: TimelineTarget) => void;
}) {
  const [offset, setOffset] = useState(0); // days, while dragging or moving with the keyboard
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false); // a drag ends with a click event; it must not open the editor
  const shown = addDays(t.due_date, offset);
  const left = daysBetween(start, shown) * DAY + DAY / 2 - 12;
  const done = t.status !== "upcoming";

  function down(e: PointerEvent<HTMLButtonElement>) {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent<HTMLButtonElement>) {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    if (Math.abs(dx) > 4) {
      drag.current.moved = true;
      setDragging(true);
    }
    if (drag.current.moved) setOffset(Math.round(dx / DAY));
  }
  function up(e: PointerEvent<HTMLButtonElement>) {
    const state = drag.current;
    drag.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
    setDragging(false);
    if (state?.moved) {
      suppressClick.current = true;
      const days = Math.round((e.clientX - state.x) / DAY);
      setOffset(0);
      if (days !== 0) onMove(t, addDays(t.due_date, days));
    }
  }
  function click() {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    if (offset === 0) onEdit(t);
  }
  function key(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const step = (e.shiftKey ? 7 : 1) * (e.key === "ArrowLeft" ? -1 : 1);
      setOffset((o) => o + step);
    } else if (e.key === "Enter" && offset !== 0) {
      e.preventDefault();
      const to = addDays(t.due_date, offset);
      setOffset(0);
      onMove(t, to);
    } else if (e.key === "Escape" && offset !== 0) {
      e.preventDefault();
      setOffset(0);
    }
  }

  return (
    <button
      type="button"
      className={`tl-marker ${cc(t.course_color)} ${dragging ? "dragging" : ""} ${done ? "done" : ""}`}
      style={{ left, top: 10 + lane * LANE }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={() => {
        drag.current = null;
        setDragging(false);
        setOffset(0);
      }}
      onClick={click}
      onKeyDown={key}
      aria-label={`${t.name}, ${t.course_title}, ${dateLabel(shown)}${offset ? " (not saved yet)" : ""}. Drag or use the arrow keys to move it, Enter to save; click to edit.`}
      title={`${t.course_title}: ${t.name} · ${dateLabel(shown)}${t.result ? ` · ${t.result}` : ""}`}
    >
      <CourseDot color={t.course_color} />
      {t.name}
      <span className="tl-date">{shortDate(shown)}</span>
      {done && <span aria-hidden="true">{t.status === "passed" ? "✓" : t.status === "failed" ? "↺" : "×"}</span>}
    </button>
  );
}

function Timeline({ targets, onMove, onEdit }: {
  targets: TimelineTarget[];
  onMove: (t: TimelineTarget, to: string) => void;
  onEdit: (t: TimelineTarget) => void;
}) {
  const today = todayIso();
  const scroller = useRef<HTMLDivElement>(null);
  const { start, days, rows, months, weeks } = useMemo(() => {
    const dates = targets.map((t) => t.due_date).sort();
    const first = dates[0] && dates[0] < today ? dates[0] : today;
    const last = dates.at(-1) && dates.at(-1)! > today ? dates.at(-1)! : today;
    let begin = addDays(first, -10);
    const weekday = new Date(`${begin}T00:00:00Z`).getUTCDay(); // 0 = Sunday
    begin = addDays(begin, -((weekday + 6) % 7)); // back to Monday
    const span = Math.max(daysBetween(begin, last) + 28, 120);
    const byCourse = new Map<string, TimelineTarget[]>();
    for (const t of targets) byCourse.set(t.course_id, [...(byCourse.get(t.course_id) ?? []), t]);
    const monthMarks: { left: number; label: string }[] = [];
    const weekMarks: number[] = [];
    for (let i = 0; i <= span; i++) {
      const day = addDays(begin, i);
      if (day.endsWith("-01") || i === 0) monthMarks.push({ left: i * DAY, label: MONTH.format(new Date(`${day}T00:00:00Z`)) });
      if (i % 7 === 0) weekMarks.push(i * DAY);
    }
    return { start: begin, days: span, rows: [...byCourse.values()], months: monthMarks, weeks: weekMarks };
  }, [targets, today]);
  const width = days * DAY;
  const todayLeft = daysBetween(start, today) * DAY + DAY / 2;

  useEffect(() => {
    if (scroller.current) scroller.current.scrollLeft = Math.max(0, todayLeft - 3 * DAY);
  }, [todayLeft]);

  return (
    <div className="timeline-wrap" ref={scroller}>
      <div className="timeline" style={{ width: width + 180 }}>
        <div className="tl-label head">Course</div>
        <div className="tl-axis" style={{ width }}>
          {months.map((m) => (
            <span key={m.left} className="tl-month" style={{ left: m.left }}>
              {m.label}
            </span>
          ))}
          <span className="tl-today" style={{ left: todayLeft }} title="Today" />
        </div>
        {rows.map((list) => {
          const first = list[0]!;
          const laneOf = lanes(list, start);
          const height = 52 + Math.max(0, ...laneOf.values()) * LANE;
          return [
            <div key={`${first.course_id}-label`} className="tl-label" title={first.course_title} style={{ height }}>
              <CourseDot color={first.course_color} />
              <Link to={`/courses/${first.course_id}?tab=targets`} style={{ color: "inherit", textDecoration: "none" }}>
                {first.course_title}
              </Link>
            </div>,
            <div key={`${first.course_id}-track`} className="tl-track" style={{ width, height }}>
              {weeks.map((w) => (
                <span key={w} className="tl-week" style={{ left: w }} />
              ))}
              <span className="tl-today" style={{ left: todayLeft }} />
              {list.map((t) => (
                <Marker
                  key={`${t.id}-${t.due_date}`}
                  t={t}
                  start={start}
                  lane={laneOf.get(t.id) ?? 0}
                  onMove={onMove}
                  onEdit={onEdit}
                />
              ))}
            </div>,
          ];
        })}
      </div>
    </div>
  );
}

export function ExamsPage() {
  const q = useTargets();
  const groups = useGroups();
  const courses = useCourses();
  const refresh = useInvalidateOrganisation();
  const [editing, setEditing] = useState<TimelineTarget | null>(null);
  const [adding, setAdding] = useState(false);
  const [showPast, setShowPast] = useState(false);
  const [calendarGroup, setCalendarGroup] = useState("");
  const [toast, setToast] = useState<Moved | null>(null);
  const [deleted, setDeleted] = useState<Target | null>(null);
  const restore = useMutation({
    mutationFn: (id: string) => request(`/targets/${id}/restore`, { method: "POST" }),
    onSuccess: () => {
      setDeleted(null);
      refresh();
    },
  });

  const move = useMutation({
    mutationFn: ({ target, to }: { target: TimelineTarget; to: string; from: string }) =>
      request(`/targets/${target.id}`, { method: "PATCH", json: { due_date: to } }),
    onSuccess: (_data, vars) => {
      refresh();
      setToast({ target: vars.target, from: vars.from, to: vars.to });
    },
  });
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 7000);
    return () => window.clearTimeout(id);
  }, [toast]);
  useEffect(() => {
    if (!deleted) return;
    const id = window.setTimeout(() => setDeleted(null), 9000);
    return () => window.clearTimeout(id);
  }, [deleted]);

  const archivedCourses = new Set((courses.data ?? []).filter((c) => c.status === "archived").map((c) => c.id));
  const semesters = (groups.data ?? []).filter((g) => g.status === "active");

  return (
    <div className="page">
      <PageHead
        title="Exams"
        sub="Every kolokvij and exam on one timeline. Drag one to move its date (or focus it and use the arrow keys), click it to edit."
      >
        <button type="button" className="btn primary" onClick={() => setAdding(true)} disabled={!courses.data?.length}>
          Add exam
        </button>
      </PageHead>
      <Async q={q} lines={5}>
        {(all) => {
          const visible = all.filter(
            (t) => !archivedCourses.has(t.course_id) && (showPast || t.status === "upcoming" || t.status === "failed"),
          );
          return (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <label className="row small">
                  <input type="checkbox" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} />
                  Show passed and cancelled
                </label>
                <div className="row">
                  {semesters.length > 0 && (
                    <label>
                      <span className="sr-only">Calendar for</span>
                      <select className="inline-input" value={calendarGroup} onChange={(e) => setCalendarGroup(e.target.value)}>
                        <option value="">All courses</option>
                        {semesters.map((g) => (
                          <option key={g.id} value={g.id}>
                            {groupPath(groups.data, g.id)}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <a className="btn" href={`${API}/calendar.ics${calendarGroup ? `?group_id=${calendarGroup}` : ""}`} download>
                    Download calendar (.ics)
                  </a>
                </div>
              </div>
              <DuplicatesPanel targets={all.filter((t) => !archivedCourses.has(t.course_id))} />
              {visible.length === 0 ? (
                <Empty title="No exams yet">
                  Add one here, or use <strong>Plan semester</strong> in Claude's + menu to set up all your kolokviji at once.
                </Empty>
              ) : (
                <Timeline targets={visible} onMove={(t, to) => move.mutate({ target: t, to, from: t.due_date })} onEdit={setEditing} />
              )}
              {move.error && <ErrorNote error={move.error} />}
              {visible.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Exam</th>
                        <th>Course</th>
                        <th>Status</th>
                        <th>
                          <span className="sr-only">Edit</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.map((t) => (
                        <tr key={t.id}>
                          <td className="nowrap">
                            {dateLabel(t.due_date)}
                            <div className="tiny muted">{t.days_left >= 0 ? `in ${plural(t.days_left, "day")}` : "passed"}</div>
                          </td>
                          <td>
                            <strong>{t.name}</strong> <span className="muted small">{TARGET_KIND[t.kind] ?? t.kind}</span>
                            {t.duplicates.length > 0 && <span className="chip warn" style={{ marginLeft: 8 }}>Possible duplicate</span>}
                            <div className="small muted pre">{t.scope_description}</div>
                          </td>
                          <td>
                            <span className="row" style={{ gap: 6 }}>
                              <CourseDot color={t.course_color} />
                              {t.course_title}
                            </span>
                          </td>
                          <td>
                            <span className={t.status === "passed" ? "chip good" : t.status === "failed" ? "chip bad" : "chip"}>
                              {t.status}
                              {t.result ? ` · ${t.result}` : ""}
                            </span>
                          </td>
                          <td>
                            <button type="button" className="btn small" onClick={() => setEditing(t)}>
                              Edit
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <RecentlyDeleted />
            </>
          );
        }}
      </Async>
      {editing && (
        <TargetDialog
          key={editing.id + editing.revision}
          target={editing}
          open
          onClose={() => setEditing(null)}
          onDeleted={(t) => {
            setToast(null);
            setDeleted(t);
          }}
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
      {toast && (
        <div className="toast" role="status">
          Moved {toast.target.name} to {dateLabel(toast.to)}.
          <button
            type="button"
            className="btn small"
            onClick={() => {
              move.mutate({ target: toast.target, to: toast.from, from: toast.to });
              setToast(null);
            }}
          >
            Undo
          </button>
        </div>
      )}
    </div>
  );
}
