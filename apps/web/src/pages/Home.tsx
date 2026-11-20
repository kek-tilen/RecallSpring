import { Link } from "react-router";
import { EventList } from "./History";
import { Upload } from "../components/Upload";
import { Async, Card, Empty, PageHead, StudyChip } from "../components/ui";
import { dateLabel, longToday, plural } from "../format";
import { useDashboard } from "../queries";
import type { AttentionItem, PlanItem, TargetCapacity } from "../types";

const CATEGORY_TONE: Record<PlanItem["category"], string> = {
  "Learn next": "chip solid",
  "Review due": "chip warn",
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
  if (a.kind === "backup") return "/settings";
  return "/history";
}

export function HomePage() {
  const q = useDashboard();
  return (
    <div className="page">
      <Async q={q} lines={6}>
        {(d) => {
          const learn = d.plan.items.find((i) => i.category === "Learn next") ?? d.plan.items[0];
          const due = d.plan.items.filter((i) => i.category === "Review due");
          return (
            <>
              <PageHead
                title="Today"
                sub={`${longToday()} · ${d.plan.planned_minutes} of ${d.plan.available_minutes} minutes planned`}
              />

              {d.counts.courses === 0 ? (
                <Empty title="Add your first course">
                  Start with a planning chat in Claude: tell it your courses, kolokvij dates, scope and material. The{" "}
                  <Link to="/guide">Guide</Link> has prompts to copy. Everything Claude saves appears here.
                </Empty>
              ) : (
                <div className="grid cols-3">
                  <Card title="Continue learning" tint>
                    {learn ? (
                      <div className="stack">
                        <div>
                          <Link to={`/concepts/${learn.concept_id}`} style={{ fontWeight: 650 }}>
                            {learn.term}
                          </Link>
                          <div className="muted small">{learn.course_title}</div>
                        </div>
                        <p className="small muted">{learn.why_selected}</p>
                        <p className="small">
                          Open the <strong>{learn.course_title}</strong> project in Claude and say “Start studying”.
                        </p>
                      </div>
                    ) : (
                      <p className="muted small">Nothing new is planned for today.</p>
                    )}
                  </Card>
                  <Card title="Review knowledge" tint>
                    <div className="stack">
                      <div className="stat" style={{ background: "var(--bg)" }}>
                        <div className="n">{due.length}</div>
                        <div className="l">{due.length === 1 ? "concept due today" : "concepts due today"}</div>
                      </div>
                      <Link to="/review" className="btn">
                        See reviews
                      </Link>
                    </div>
                  </Card>
                  <Card title="Add material" tint>
                    <Upload />
                  </Card>
                </div>
              )}

              <div className="split">
                <div className="stack" style={{ gap: 20 }}>
                  <Card title="Today's plan" meta={`${d.plan.planned_minutes} min`}>
                    {d.plan.message && <p className="notice small" style={{ marginBottom: 12 }}>{d.plan.message}</p>}
                    {d.plan.focus && (
                      <p className="notice small" style={{ marginBottom: 12 }}>
                        {d.plan.focus.message}
                      </p>
                    )}
                    {d.plan.interests && !d.plan.focus && (
                      <p className="notice small muted" style={{ marginBottom: 12 }}>
                        {d.plan.interests.message}{" "}
                        <Link to="/settings">Change in Settings</Link>
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
                                <div className="tiny muted">
                                  {item.sections.map((s) => `${s.filename} ${s.citation_label}`).join(" · ")}
                                </div>
                              )}
                            </div>
                            <span className="muted small">{item.estimated_minutes} min</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className="tiny muted" style={{ marginTop: 12 }}>
                      {d.plan.note}
                    </p>
                  </Card>

                  {d.plan.targets.length > 0 && (
                    <Card title="Exams and kolokviji">
                      <ul className="list">
                        {d.plan.targets.map((t) => (
                          <li key={t.target_id} className="stack" style={{ gap: 4 }}>
                            <div className="row" style={{ justifyContent: "space-between" }}>
                              <Link to={`/courses/${t.course_id}?tab=targets`} style={{ fontWeight: 600 }}>
                                {t.target} · {t.course_title}
                              </Link>
                              <span className={CAPACITY[t.status].tone}>{CAPACITY[t.status].label}</span>
                            </div>
                            <div className="small muted">
                              {dateLabel(t.due_date)} · {plural(t.days_left, "day")} left · {plural(t.concepts_in_scope, "concept")} in scope
                            </div>
                            <div className="small">{t.message}</div>
                          </li>
                        ))}
                      </ul>
                    </Card>
                  )}
                </div>

                <div className="stack" style={{ gap: 20 }}>
                  <Card title="Needs attention">
                    {d.attention.length === 0 ? (
                      <p className="muted small">Nothing needs you right now.</p>
                    ) : (
                      <ul className="list">
                        {d.attention.map((a, i) => (
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
                  <Card title="What RecallSpring holds">
                    <div className="stats">
                      {(
                        [
                          ["courses", "Courses", "/courses"],
                          ["sources", "Materials", "/library"],
                          ["concepts", "Concepts", "/courses"],
                          ["notes", "Notes", "/notes"],
                          ["answers", "Answers", "/history"],
                          ["simulations", "Simulations", "/simulations"],
                        ] as const
                      ).map(([k, label, to]) => (
                        <Link key={k} to={to} className="stat" style={{ textDecoration: "none", color: "inherit" }}>
                          <div className="n">{d.counts[k]}</div>
                          <div className="l">{label}</div>
                        </Link>
                      ))}
                    </div>
                  </Card>
                  <Card title="Recent activity" action={<Link to="/history" className="small">All history</Link>}>
                    <EventList rows={d.recent} compact />
                  </Card>
                </div>
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}
