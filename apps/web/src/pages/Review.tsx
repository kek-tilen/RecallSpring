import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { request } from "../api";
import { Async, Empty, ErrorNote, PageHead } from "../components/ui";
import { dateLabel, daysFromToday, plural, relativeDay } from "../format";
import { courseTitles, keys, useCourses, useReviews } from "../queries";
import type { CourseColor, ReviewItem } from "../types";
import { CourseDot } from "../components/organise";
import { StudyIn } from "../components/StudyIn";
import { WaitingForGrade } from "../components/WaitingForGrade";

function Row({ item, course }: { item: ReviewItem; course: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const defer = useMutation({
    mutationFn: (days: number) =>
      request<ReviewItem>(`/reviews/${item.concept_id}/defer`, { method: "POST", json: { days, reason: "Snoozed in the web app" } }),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: keys.reviews });
      void qc.invalidateQueries({ queryKey: keys.dashboard });
      void qc.invalidateQueries({ queryKey: ["courses"] });
    },
  });
  return (
    <li className="stack" style={{ gap: 6 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <Link to={`/concepts/${item.concept_id}`} style={{ fontWeight: 600 }}>
            {item.term}
          </Link>
          {course && <span className="muted small"> · {course}</span>}
        </div>
        <div className="row">
          <span className="small muted">
            {dateLabel(item.due_at)} ({relativeDay(item.due_at)})
          </span>
          {item.is_due && (
            <button type="button" className="btn small" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
              Snooze
            </button>
          )}
        </div>
      </div>
      {item.due_reason.message && <div className="small muted">{item.due_reason.message}</div>}
      {open && (
        <div className="row" role="group" aria-label={`Snooze ${item.term}`}>
          <span className="small">Snooze for</span>
          {[1, 3, 7].map((d) => (
            <button key={d} type="button" className="btn small" disabled={defer.isPending} onClick={() => defer.mutate(d)}>
              {plural(d, "day")}
            </button>
          ))}
          <span className="tiny muted">Snoozing is recorded; skipped reviews simply stay due.</span>
        </div>
      )}
      {defer.error && <ErrorNote error={defer.error} />}
    </li>
  );
}

/** Reviews per day for the next 14 days (today = what is due now), as quiet bars. */
function NextDays({ items }: { items: ReviewItem[] }) {
  const counts = Array.from({ length: 14 }, () => 0);
  for (const i of items) counts[i.is_due ? 0 : Math.min(13, Math.max(0, daysFromToday(i.due_at)))]! += 1;
  const max = Math.max(1, ...counts);
  const said = counts
    .map((n, d) => (n ? `${d === 0 ? "today" : d === 1 ? "tomorrow" : `in ${d} days`} ${n}` : ""))
    .filter(Boolean)
    .join(", ");
  return (
    <svg className="review-days" viewBox="0 0 280 56" width="280" height="56" role="img" aria-label={`Reviews in the next 14 days: ${said || "none"}`}>
      {counts.map((n, d) => {
        const h = n ? Math.max(4, Math.round((n / max) * 44)) : 2;
        return <rect key={d} x={d * 20 + 3} y={48 - h} width="14" height={h} rx="2" className={d === 0 ? "today" : n ? "on" : "off"} />;
      })}
      <line x1="0" y1="48.5" x2="280" y2="48.5" className="base" />
    </svg>
  );
}

/** "2 overdue · 4 today" for one course's due concepts. */
export function dueWords(list: ReviewItem[]): string {
  const overdue = list.filter((i) => daysFromToday(i.due_at) < 0).length;
  const today = list.length - overdue;
  return [overdue ? `${overdue} overdue` : "", today ? `${today} today` : ""].filter(Boolean).join(" · ");
}

/**
 * 2026-11-26: the page says what is due, and per course starts the review itself with the learner's assistant.
 * 2026-11-27 (UI direction): one group per course (its colour, "2 overdue · 4 today", Review in…), its concepts folded
 * below with Snooze; the next 14 days sit beside them.
 */
function DueNow({ due, titles, colors }: { due: Map<string, ReviewItem[]>; titles: Record<string, string>; colors: Map<string, CourseColor | null> }) {
  return (
    <section className="review-now" aria-labelledby="review-now-title">
      <h2 id="review-now-title" className="sr-only">
        Due now
      </h2>
      {due.size === 0 ? (
        <p className="muted">Nothing is due now. The next reviews are listed beside this.</p>
      ) : (
        <ul className="review-courses">
          {[...due.entries()].map(([courseId, list]) => {
            const title = titles[courseId] ?? "Course";
            return (
              <li key={courseId} className="review-course">
                <div className="review-course-head">
                  <CourseDot color={colors.get(courseId)} />
                  <span className="review-course-name">{title}</span>
                  <span className="muted small review-course-count">{dueWords(list)}</span>
                </div>
                <div className="review-course-actions">
                  <Link to={`/review/now/${courseId}`} className="btn small primary">
                    Review now
                  </Link>
                  <StudyIn course={{ id: courseId, title }} review={{}} quiet />
                </div>
                <details className="review-fold">
                  <summary className="small muted">{plural(list.length, "concept")}</summary>
                  <ul className="list review-concepts">
                    {list.map((i) => (
                      <Row key={i.concept_id} item={i} course="" />
                    ))}
                  </ul>
                </details>
              </li>
            );
          })}
        </ul>
      )}
      <p className="tiny muted">
        Review now asks the questions you saved before, here, from memory; Review in… has your assistant ask new ones. The
        next date follows the grade.
      </p>
    </section>
  );
}

export function ReviewPage() {
  const q = useReviews();
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  const colors = new Map((courses.data ?? []).map((c) => [c.id, c.color]));
  return (
    <div className="page">
      <Async q={q} lines={6}>
        {(data) => {
          const upcoming = data.items.filter((i) => !i.is_due);
          const due = new Map<string, ReviewItem[]>();
          for (const i of [...data.items].sort((a, b) => a.due_at.localeCompare(b.due_at))) {
            if (i.is_due) due.set(i.course_id, [...(due.get(i.course_id) ?? []), i]);
          }
          const total = data.items.length - upcoming.length;
          return (
            <>
              <PageHead title="Review" sub={total ? `${total} due` : "Nothing due now"} />
              {data.items.length === 0 ? (
                <Empty title="You're caught up.">Continue a topic or browse your library.</Empty>
              ) : (
                <div className="review-layout">
                  <DueNow due={due} titles={titles} colors={colors} />
                  <section className="review-next" aria-labelledby="review-next-title">
                    <h2 id="review-next-title" className="review-h">
                      Next 14 days
                    </h2>
                    <NextDays items={data.items} />
                    <p className="tiny muted review-days-note">Today highlighted · the dates follow your grades</p>
                    {upcoming.length === 0 ? (
                      <p className="small muted">Nothing else in the next 14 days.</p>
                    ) : (
                      <ul className="list">
                        {upcoming.map((i) => (
                          <Row key={i.concept_id} item={i} course={titles[i.course_id] ?? ""} />
                        ))}
                      </ul>
                    )}
                    <WaitingForGrade />
                  </section>
                </div>
              )}
              {data.note && <p className="tiny muted">{data.note}</p>}
            </>
          );
        }}
      </Async>
    </div>
  );
}
