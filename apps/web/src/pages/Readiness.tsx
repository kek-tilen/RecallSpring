import { Link, useParams } from "react-router";
import { CourseDot } from "../components/organise";
import { Async, Card, Empty, Meter, PageHead } from "../components/ui";
import { dateLabel, gradeLabel, plural } from "../format";
import { useReadiness } from "../queries";
import type { ExamReadiness, ReadinessConcept, ReadinessCounts, ReadinessState } from "../types";

export const READINESS_ORDER: ReadinessState[] = ["not_studied", "weak", "not_practised", "developing", "solid"];
export const READINESS_LABEL: Record<ReadinessState, string> = {
  not_studied: "Not studied yet",
  weak: "Weak",
  not_practised: "Studied, not practised",
  developing: "Getting there",
  solid: "Solid",
};
const STEP: Record<ReadinessState, number | "w"> = { not_studied: 0, weak: "w", not_practised: 1, developing: 2, solid: 3 };
const CHIP: Record<ReadinessState, string> = {
  not_studied: "chip",
  weak: "chip warn",
  not_practised: "chip",
  developing: "chip",
  solid: "chip good",
};
const CAPACITY = {
  ok: { tone: "chip good", label: "On track" },
  tight: { tone: "chip warn", label: "Tight" },
  at_risk: { tone: "chip bad", label: "At risk" },
} as const;

export function ReadinessMeter({ counts, label }: { counts: ReadinessCounts; label: string }) {
  return (
    <Meter label={label} segments={READINESS_ORDER.map((s) => ({ label: READINESS_LABEL[s], value: counts[s], step: STEP[s] }))} />
  );
}

/** The bar alone (no legend), for lists; the counts are in its accessible name. */
export function MiniReadiness({ counts, label }: { counts: ReadinessCounts; label: string }) {
  const total = READINESS_ORDER.reduce((n, s) => n + counts[s], 0);
  const summary = READINESS_ORDER.filter((s) => counts[s] > 0)
    .map((s) => `${READINESS_LABEL[s]}: ${counts[s]}`)
    .join(", ");
  return (
    <div className="meter" role="img" aria-label={`${label}. ${summary || "No concepts"}`} style={{ height: 8 }}>
      {total === 0 ? (
        <span className="r0" style={{ flex: 1 }} />
      ) : (
        READINESS_ORDER.filter((s) => counts[s] > 0).map((s) => (
          <span key={s} className={`r${STEP[s]}`} style={{ flex: counts[s] }} title={`${READINESS_LABEL[s]}: ${counts[s]} of ${total}`} />
        ))
      )}
    </div>
  );
}

function openWork(counts: ReadinessCounts): string {
  const parts = [];
  if (counts.not_studied) parts.push(`${counts.not_studied} not studied`);
  if (counts.weak) parts.push(`${counts.weak} weak`);
  if (counts.not_practised) parts.push(`${counts.not_practised} not practised`);
  return parts.length ? parts.join(" · ") : "Nothing open";
}

function ConceptRow({ c }: { c: ReadinessConcept }) {
  return (
    <li>
      <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <Link to={`/concepts/${c.id}`} style={{ fontWeight: 600 }}>
          {c.term}
        </Link>
        <span className="row" style={{ gap: 6 }}>
          {c.due && <span className="chip warn">Review due</span>}
          {c.exam_weight !== null && c.exam_weight >= 1.5 && <span className="chip">Frequent in old papers</span>}
          <span className={CHIP[c.state]}>{READINESS_LABEL[c.state]}</span>
        </span>
      </div>
      <div className="tiny muted">
        {c.last_grade !== null ? `Last answer ${gradeLabel(c.last_grade)}` : c.state === "not_studied" ? "Learn it first" : "No answer yet"}
        {c.citations.length > 0 && ` · ${c.citations.join("; ")}`}
      </div>
    </li>
  );
}

function Groups({ r }: { r: ExamReadiness }) {
  if (r.groups.length === 0) {
    return (
      <Empty title="No concepts in scope yet">
        Import the material for this exam and ask your assistant to create concepts from it; they appear here by file.
      </Empty>
    );
  }
  return (
    <div className="stack" style={{ gap: 12 }}>
      {r.groups.map((g) => {
        const total = g.concepts.length;
        return (
          <details key={`${g.kind}-${g.id ?? "none"}`} className="group-block" open={g.counts.solid + g.counts.developing < total}>
            <summary>
              <div className="material-head">
                <div style={{ overflowWrap: "anywhere" }}>
                  <span style={{ fontWeight: 600 }}>{g.title}</span>
                  <span className="muted small">
                    {g.pages && ` · ${g.pages}`} · {plural(total, "concept")}
                  </span>
                </div>
                <div className="small muted">{openWork(g.counts)}</div>
                <MiniReadiness counts={g.counts} label={g.title} />
              </div>
            </summary>
            <ul className="list" style={{ marginTop: 10 }}>
              {g.concepts.map((c) => (
                <ConceptRow key={c.id} c={c} />
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

function Weakest({ r }: { r: ExamReadiness }) {
  if (r.weakest.length === 0) {
    return (
      <p className="muted small">
        {r.summary.weak === 0 && r.summary.developing + r.summary.solid === 0
          ? "No graded answers yet, so nothing is known to be weak."
          : "No weak concepts in your answers so far."}
      </p>
    );
  }
  return (
    <ul className="list">
      {r.weakest.map((w) => (
        <li key={w.id}>
          <Link to={`/concepts/${w.id}`} style={{ fontWeight: 600 }}>
            {w.term}
          </Link>
          <span className="muted small"> · {w.group}</span>
          <div className="small">{w.reason}</div>
          {w.gaps.length > 0 && (
            <>
              <div className="tiny muted" style={{ marginTop: 4 }}>
                Missing in your last answer (from its feedback):
              </div>
              <ul className="small" style={{ margin: "2px 0 0", paddingLeft: 18 }}>
                {w.gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </>
          )}
          {w.remediation && <div className="small muted">Tip: {w.remediation}</div>}
          {w.citations.length > 0 && <div className="tiny muted">Read again: {w.citations.join("; ")}</div>}
        </li>
      ))}
    </ul>
  );
}

function Simulations({ r }: { r: ExamReadiness }) {
  if (r.simulations.length === 0) return <p className="muted small">No simulation for this exam yet.</p>;
  return (
    <ul className="list">
      {r.simulations.map((q) => (
        <li key={q.id} className="row" style={{ justifyContent: "space-between" }}>
          <Link to={`/simulations/${q.id}`}>{q.title}</Link>
          <span className="small muted">
            {q.status === "submitted"
              ? q.earned_points !== null && q.max_points
                ? `${q.earned_points}/${q.max_points} points${q.pending_items ? ` · ${q.pending_items} waiting for a grade` : ""}`
                : "Submitted"
              : "Not submitted"}
            {q.mode === "diagnostic" ? " · diagnostic" : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ReadinessPage() {
  const { targetId = "" } = useParams();
  const q = useReadiness(targetId);
  return (
    <div className="page">
      <Async q={q} lines={6}>
        {(r) => {
          const t = r.target;
          const s = r.summary;
          const when = t.days_left > 0 ? `in ${plural(t.days_left, "day")}` : t.days_left === 0 ? "today" : "passed";
          return (
            <>
              <PageHead
                title={`${t.name}: readiness`}
                sub={
                  <span className="row" style={{ gap: 6 }}>
                    <CourseDot color={t.course.color} />
                    <span>
                      {t.course.title} · {dateLabel(t.due_date)} ({when})
                    </span>
                  </span>
                }
                crumbs={[
                  { to: "/exams", label: "Exams" },
                  { to: `/courses/${t.course.id}?tab=targets`, label: t.course.title },
                ]}
              />
              <div className="grid cols-2" style={{ alignItems: "start" }}>
                <div className="stack" style={{ gap: 20 }}>
                  <Card title="Where you stand" meta={plural(s.concepts, "concept") + " in scope"}>
                    <div className="stack">
                      <ReadinessMeter counts={s} label={`Readiness for ${t.name}`} />
                      {r.capacity ? (
                        <p className="small">
                          <span className={CAPACITY[r.capacity.status].tone}>{CAPACITY[r.capacity.status].label}</span> {r.capacity.message}
                        </p>
                      ) : (
                        <p className="small">
                          About {s.remaining_minutes} min of work left. The time check covers the next exam of each course; this one comes
                          later.
                        </p>
                      )}
                      {s.due > 0 && (
                        <p className="small">
                          {plural(s.due, "review")} due now · <Link to="/review">Review</Link>
                        </p>
                      )}
                      {t.scope_description && <p className="small muted pre">Scope: {t.scope_description}</p>}
                    </div>
                  </Card>
                  <Card title="Next steps">
                    <ol className="small" style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6 }}>
                      {r.next_steps.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ol>
                  </Card>
                  <Card title="Weakest concepts" meta="From your graded answers">
                    <Weakest r={r} />
                  </Card>
                  <Card title="Simulations for this exam">
                    <Simulations r={r} />
                  </Card>
                </div>
                <Card title="By material" meta="In the order it is taught">
                  <Groups r={r} />
                </Card>
              </div>
              <p className="tiny muted">{r.note}</p>
            </>
          );
        }}
      </Async>
    </div>
  );
}
