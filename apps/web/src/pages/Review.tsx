import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { get, request } from "../api";
import { Async, Card, Empty, ErrorNote, PageHead } from "../components/ui";
import { dateLabel, daysFromToday, plural, relativeDay } from "../format";
import { courseTitles, keys, useCourses } from "../queries";
import type { ReviewItem } from "../types";

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
          <span className="muted small"> · {course}</span>
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

export function ReviewPage() {
  const q = useQuery({ queryKey: keys.reviews, queryFn: () => get<{ items: ReviewItem[]; note: string }>("/reviews/due", { horizon_days: 14 }) });
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  return (
    <div className="page">
      <PageHead
        title="Review"
        sub="RecallSpring schedules reviews from your graded answers. Practise them with Claude: say “Review what is due”."
      />
      <Async q={q} lines={6}>
        {(data) => {
          const overdue = data.items.filter((i) => i.is_due && daysFromToday(i.due_at) < 0);
          const today = data.items.filter((i) => i.is_due && daysFromToday(i.due_at) >= 0);
          const upcoming = data.items.filter((i) => !i.is_due);
          if (data.items.length === 0) {
            return <Empty title="You're caught up.">Continue a topic or browse your library.</Empty>;
          }
          return (
            <div className="stack" style={{ gap: 20 }}>
              {[
                { title: "Overdue", items: overdue },
                { title: "Today", items: today },
                { title: "Next 14 days", items: upcoming },
              ].map((g) => (
                <Card key={g.title} title={g.title} meta={plural(g.items.length, "concept")}>
                  {g.items.length === 0 ? (
                    <p className="small muted">{g.title === "Overdue" ? "Nothing overdue." : "Nothing here."}</p>
                  ) : (
                    <ul className="list">
                      {g.items.map((i) => (
                        <Row key={i.concept_id} item={i} course={titles[i.course_id] ?? ""} />
                      ))}
                    </ul>
                  )}
                </Card>
              ))}
              <p className="tiny muted">{data.note}</p>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
