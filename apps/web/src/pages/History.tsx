import { useState } from "react";
import { Link } from "react-router";
import { Async, PageHead } from "../components/ui";
import { dayHeading, timeOnly } from "../format";
import { useHistory } from "../queries";
import type { HistoryRow } from "../types";

function entityLink(r: HistoryRow): string | null {
  if (!r.entity_id) return null;
  switch (r.entity_type) {
    case "concept":
      return `/concepts/${r.entity_id}`;
    case "source":
      return `/library/${r.entity_id}`;
    case "quiz":
      return `/simulations/${r.entity_id}`;
    case "course":
      return `/courses/${r.entity_id}`;
    case "note":
      return `/notes/${r.entity_id}`;
    default:
      return null;
  }
}

export function EventList({ rows, compact }: { rows: HistoryRow[]; compact?: boolean }) {
  if (rows.length === 0) return <p className="muted small">No activity yet.</p>;
  let lastDay = "";
  return (
    <div>
      {rows.map((r, i) => {
        const day = dayHeading(r.at);
        const showDay = !compact && day !== lastDay;
        lastDay = day;
        const to = entityLink(r);
        return (
          <div key={`${r.at}-${i}`}>
            {showDay && <div className="timeline-day">{day}</div>}
            <div className="event">
              <span className="t">{compact ? dayHeading(r.at) === "Today" ? timeOnly(r.at) : day.split(",")[0] : timeOnly(r.at)}</span>
              <span className={r.kind === "audit" ? "mark audit" : "mark"} aria-hidden="true" />
              <div>
                <div>
                  {r.text}
                  {r.label && (
                    <>
                      {" · "}
                      {to ? <Link to={to}>{r.label}</Link> : <span>{r.label}</span>}
                    </>
                  )}
                </div>
                {r.detail && <div className="small muted">{r.detail}</div>}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const FILTERS = [
  { id: "all", label: "Everything" },
  { id: "learning", label: "Learning" },
  { id: "audit", label: "Settings and changes" },
] as const;

export function HistoryPage() {
  const q = useHistory();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");
  return (
    <div className="page">
      <PageHead
        title="History"
        sub="When each answer was saved, graded and scheduled, and every change to your settings. Newest first."
      />
      <div className="row" role="group" aria-label="Filter history">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className="chip chip-filter" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>
      <div className="card">
        <Async q={q} lines={8}>
          {(rows) => <EventList rows={filter === "all" ? rows : rows.filter((r) => r.kind === filter)} />}
        </Async>
      </div>
      <p className="tiny muted">
        Filled dots are learning records; hollow dots are changes you or your assistant made to settings, targets and tokens. Sign-ins are
        not listed.
      </p>
    </div>
  );
}
