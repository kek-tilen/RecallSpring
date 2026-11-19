import { Link } from "react-router";
import { Async, Empty, PageHead, StudyMeter } from "../components/ui";
import { dateLabel, plural } from "../format";
import { useCourseSummary } from "../queries";

export function CoursesPage() {
  const q = useCourseSummary();
  return (
    <div className="page">
      <PageHead title="Courses" sub="Each course with its next exam, what you have studied and what is due." />
      <Async q={q} lines={6}>
        {(courses) =>
          courses.length === 0 ? (
            <Empty title="No courses yet">Ask Claude to create a course and import your material; it will appear here.</Empty>
          ) : (
            <div className="grid cols-2">
              {courses.map((c) => (
                <article key={c.id} className="card stack">
                  <div>
                    <h2>
                      <Link to={`/courses/${c.id}`}>{c.title}</Link>
                    </h2>
                    {c.description && <p className="muted small">{c.description}</p>}
                  </div>
                  {c.active_target ? (
                    <div className="notice small">
                      <strong>{c.active_target.name}</strong> on {dateLabel(c.active_target.due_date)} ·{" "}
                      {c.active_target.days_left >= 0 ? `${plural(c.active_target.days_left, "day")} left` : "date passed"}
                    </div>
                  ) : (
                    <div className="notice small muted">No exam or kolokvij set. Claude asks for it at the start of a session.</div>
                  )}
                  <StudyMeter progress={c.progress} />
                  <div className="row small muted" style={{ gap: 16 }}>
                    <span>{plural(c.progress.concepts, "concept")}</span>
                    <span>{plural(c.sources, "material")}</span>
                    <span>{plural(c.notes, "note")}</span>
                    <span>{plural(c.simulations, "simulation")}</span>
                    {c.due_reviews > 0 && <span className="chip warn">{c.due_reviews} due</span>}
                  </div>
                </article>
              ))}
            </div>
          )
        }
      </Async>
    </div>
  );
}
