import { Link, useSearchParams } from "react-router";
import { CourseDot } from "../components/organise";
import { Async, Card, PageHead } from "../components/ui";
import { GRADE_LABEL, dateLabel, plural } from "../format";
import { useWeek } from "../queries";
import type { WeekReview } from "../types";
import { MiniReadiness } from "./Readiness";

function range(w: WeekReview): string {
  return `${dateLabel(w.week.start)} – ${dateLabel(w.week.end)}`;
}

function trend(w: WeekReview): string | null {
  const { average, previous_average: prev } = w.grades;
  if (average === null || prev === null) return null;
  if (average > prev) return `up from ${prev}`;
  if (average < prev) return `down from ${prev}`;
  return "same as the week before";
}

/** Compact card for Today: the review's plain sentences and a link to the full page. */
export function WeekCard() {
  const q = useWeek(0);
  return (
    <Card title="This week" action={<Link to="/week" className="small">Weekly review</Link>}>
      <Async q={q} lines={3}>
        {(w) => (
          <ul className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
            {w.summary.slice(0, 4).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </Async>
    </Card>
  );
}

function Numbers({ w }: { w: WeekReview }) {
  const a = w.activity;
  const t = trend(w);
  const stats: [string, string, string | null][] = [
    ["Active days", `${a.active_days.length} of ${w.week.days_counted}`, null],
    ["Answers", String(a.answers), a.graded ? `${a.graded} graded` : null],
    ["Concepts studied", String(a.concepts_studied + a.concepts_known), a.concepts_known ? `${a.concepts_known} you knew` : null],
    ["Simulations", String(a.simulations), null],
    ["Average grade", w.grades.average === null ? "–" : `${w.grades.average}/4`, t],
    ["Study time", w.sessions.timed ? `${w.session_minutes} min` : "–", `${w.planned_minutes} min planned`],
  ];
  return (
    <div className="stats">
      {stats.map(([label, value, hint]) => (
        <div key={label} className="stat">
          <div className="n">{value}</div>
          <div className="l">{label}</div>
          {hint && <div className="tiny muted">{hint}</div>}
        </div>
      ))}
    </div>
  );
}

function Grades({ w }: { w: WeekReview }) {
  const max = Math.max(1, ...w.grades.distribution);
  if (w.grades.count === 0) return <p className="muted small">No graded answers this week.</p>;
  return (
    <table className="grade-bars">
      <caption className="sr-only">Graded answers per grade</caption>
      <tbody>
        {w.grades.distribution.map((n, grade) => (
          <tr key={grade}>
            <th scope="row" className="small">
              {grade} · {GRADE_LABEL[grade]}
            </th>
            <td>
              <span className="grade-bar" style={{ width: `${(100 * n) / max}%` }} aria-hidden="true" />
            </td>
            <td className="small num">{n}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Courses({ w }: { w: WeekReview }) {
  if (w.courses.length === 0) return <p className="muted small">Nothing recorded per course.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Course</th>
            <th className="num">Answers</th>
            <th className="num">Average</th>
            <th className="num">Studied</th>
          </tr>
        </thead>
        <tbody>
          {w.courses.map((c) => (
            <tr key={c.id}>
              <td>
                <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                  <CourseDot color={c.color} />
                  <Link to={`/courses/${c.id}`}>{c.title}</Link>
                </span>
              </td>
              <td className="num">{c.answers}</td>
              <td className="num">{c.average_grade === null ? "–" : `${c.average_grade}/4`}</td>
              <td className="num">{c.concepts_studied}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Exams({ w }: { w: WeekReview }) {
  if (w.exams.length === 0) return <p className="muted small">No exam in the next three weeks.</p>;
  return (
    <ul className="list">
      {w.exams.map((e) => (
        <li key={e.id} className="stack" style={{ gap: 4 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <Link to={`/exams/${e.id}`} style={{ fontWeight: 600 }}>
              {e.name}
            </Link>
            <span className="small muted">
              {dateLabel(e.due_date)} · {e.days_left === 0 ? "today" : `in ${plural(e.days_left, "day")}`}
            </span>
          </div>
          <span className="small row" style={{ gap: 6, flexWrap: "nowrap", alignItems: "baseline" }}>
            <CourseDot color={e.course_color} />
            <span>
              {e.course_title} · {plural(e.concepts, "concept")}: {e.not_studied} not studied, {e.weak} weak, {e.not_practised}{" "}
              not practised
            </span>
          </span>
          <MiniReadiness counts={e} label={`Readiness for ${e.name}`} />
        </li>
      ))}
    </ul>
  );
}

export function WeekPage() {
  const [params, setParams] = useSearchParams();
  const weeksAgo = Math.max(0, Math.min(52, Number(params.get("weeks_ago")) || 0));
  const q = useWeek(weeksAgo);
  const go = (n: number) => setParams(n ? { weeks_ago: String(n) } : {}, { replace: true });
  return (
    <div className="page">
      <PageHead title="Weekly review" sub="What RecallSpring recorded in one week, Monday to Sunday, and the exams ahead.">
        <div className="row">
          <button type="button" className="btn" onClick={() => go(weeksAgo + 1)} disabled={weeksAgo >= 52}>
            ← Earlier week
          </button>
          <button type="button" className="btn" onClick={() => go(weeksAgo - 1)} disabled={weeksAgo === 0}>
            Later week →
          </button>
        </div>
      </PageHead>
      <Async q={q} lines={6}>
        {(w) => (
          <div className="stack" style={{ gap: 20 }}>
            <h2 style={{ margin: 0 }}>
              {range(w)}
              {w.week.is_current && <span className="chip" style={{ marginLeft: 8, verticalAlign: "middle" }}>This week</span>}
            </h2>
            <div className="grid cols-2" style={{ alignItems: "start" }}>
              <div className="stack" style={{ gap: 20 }}>
                <Card title="In short">
                  <ul className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
                    {w.summary.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  {w.reviews && w.reviews.overdue > 0 && (
                    <p className="small" style={{ marginBottom: 0 }}>
                      <Link to="/review">Open Review</Link> for the {plural(w.reviews.overdue, "overdue review")}.
                    </p>
                  )}
                </Card>
                <Card title="Numbers">
                  <Numbers w={w} />
                </Card>
                <Card title="Grades" meta={w.grades.count ? plural(w.grades.count, "graded answer") : undefined}>
                  <Grades w={w} />
                </Card>
              </div>
              <div className="stack" style={{ gap: 20 }}>
                {w.week.is_current && (
                  <Card title="Exams in the next three weeks" action={<Link to="/exams" className="small">All exams</Link>}>
                    <Exams w={w} />
                  </Card>
                )}
                <Card title="By course">
                  <Courses w={w} />
                </Card>
                {w.reviews && (
                  <Card title="Reviews">
                    <p className="small" style={{ margin: 0 }}>
                      {plural(w.reviews.overdue, "review")} overdue · {plural(w.reviews.due_next_7_days, "review")} due in the next 7 days.
                    </p>
                  </Card>
                )}
              </div>
            </div>
            <p className="tiny muted">{w.note}</p>
          </div>
        )}
      </Async>
    </div>
  );
}
