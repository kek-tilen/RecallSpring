import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useLocation } from "react-router";
import { request } from "../api";
import { Async, Card, ErrorNote } from "../components/ui";
import { dateTime, plural } from "../format";
import { useRationale } from "../queries";
import type { PaperFile, PlanRationale, RationaleTopic, ReadinessState, TargetProfile } from "../types";

/** ADR-013 §4: "Why this plan" on the Readiness page, from the server's rationale (rationale-v1, no model). */

const BLOOM = ["", "Remember", "Understand", "Apply", "Analyse", "Evaluate", "Create"];
const pct = (x: number) => `${Math.round(x * 100)} %`;

const STATE_LABEL: Record<ReadinessState, string> = {
  not_studied: "Not studied yet",
  weak: "Weak",
  not_practised: "Studied, not practised",
  developing: "Getting there",
  solid: "Solid",
};
const STATE_CHIP: Record<ReadinessState, string> = {
  not_studied: "chip",
  weak: "chip warn",
  not_practised: "chip",
  developing: "chip",
  solid: "chip good",
};
const STATUS: Record<RationaleTopic["status"], { label: string; tone: string }> = {
  not_studied: { label: "Not studied yet", tone: "chip" },
  in_progress: { label: "In progress", tone: "chip" },
  weak: { label: "Weak", tone: "chip warn" },
  solid: { label: "Solid", tone: "chip good" },
  not_in_material: { label: "Not in your material", tone: "chip warn" },
  unmapped: { label: "Not linked to your material", tone: "chip warn" },
};
const BASIS: Record<string, string> = {
  points: "Weighted by the points on the old papers.",
  share: "Weighted by each topic's share of the paper.",
  topics: "The paper shows no points, so every topic counts the same.",
};
const CATEGORY_WORD: Record<string, string> = {
  "Learn next": "Learn",
  "Review due": "Review",
  Strengthen: "Strengthen",
  Practice: "Practise",
  Maintain: "Keep fresh",
};

function size(t: { points: number | null; share: number | null }): string {
  if (t.points != null) return plural(t.points, "point");
  if (t.share != null) return pct(t.share);
  return "—";
}

function bloomLine(mix: Record<string, number>): string {
  const entries = Object.entries(mix).sort(([a], [b]) => Number(a) - Number(b));
  return entries.length ? entries.map(([level, share]) => `${BLOOM[Number(level)] ?? `Level ${level}`} ${pct(share)}`).join(" · ") : "—";
}

const USE: Record<string, string> = { style: "only its kind of questions counts", style_and_topics: "its topics count too" };

/** The old papers behind the analysis, each linked when RecallSpring has a copy, with the exam it was for and how it
 * is used (ADR-013 §1). */
export function Papers({ profile }: { profile: TargetProfile }) {
  return (
    <>
      <PaperList profile={profile} />
      <PapersLeftOut profile={profile} />
    </>
  );
}

/** Past papers left out on the learner's word, and those of the course the analysis has not looked at (owner
 * 2026-11-25: an analysis read one photo and missed four). */
function PapersLeftOut({ profile }: { profile: TargetProfile }) {
  const skipped = profile.skipped_papers ?? [];
  const missing = profile.not_looked_at ?? [];
  const unproven = profile.evidence_missing ?? [];
  return (
    <>
      {skipped.length > 0 && (
        <div className="small muted" style={{ marginTop: 4 }}>
          Left out on your word:{" "}
          {skipped.map((s, i) => (
            <span key={s.source_id}>
              {i > 0 && "; "}
              {s.source && !s.source.removed ? <Link to={`/library/${s.source.id}`}>{s.source.filename}</Link> : "a paper"} ({s.reason})
            </span>
          ))}
        </div>
      )}
      {unproven.length > 0 && (
        <div className="small muted" style={{ marginTop: 4 }}>
          Your assistant did not say why these files belong to their paper: {unproven.map((u) => u.filename).join(", ")}. Ask it to analyse
          the papers again.
        </div>
      )}
      {missing.length > 0 && (
        <div className="small" role="note" style={{ marginTop: 4 }}>
          <span className="chip warn">Not looked at</span> Past papers of this course not in the analysis:{" "}
          {missing.map((m, i) => (
            <span key={m.id}>
              {i > 0 && ", "}
              <Link to={`/library/${m.id}`}>{m.filename}</Link>
            </span>
          ))}
          . Ask your assistant to look at them, or tell it which ones do not apply.
        </div>
      )}
    </>
  );
}

function PaperList({ profile }: { profile: TargetProfile }) {
  const papers = profile.papers ?? [];
  if (papers.length === 0) {
    if (profile.source && !profile.source.removed) return <Link to={`/library/${profile.source.id}`}>{profile.source.filename}</Link>;
    return <span className="muted">No paper named</span>;
  }
  return (
    <ul style={{ margin: 0, paddingLeft: 18 }}>
      {papers.map((p, i) => {
        const name = p.label || p.source?.filename || "Old paper";
        const files: PaperFile[] = p.files ?? (p.source ? [p.source] : []);
        const live = files.filter((f) => !f.removed);
        const extra = [p.total_points != null ? plural(p.total_points, "point") : null, p.duration_minutes ? `${p.duration_minutes} min` : null]
          .filter(Boolean)
          .join(" · ");
        return (
          <li key={i}>
            {files.length === 1 && live.length === 1 ? <Link to={`/library/${live[0]!.id}`}>{name}</Link> : name}
            {files.length > 1 && <span className="muted"> · {plural(files.length, "file")}</span>}
            {p.exam && <span> · for {p.exam}</span>}
            {extra && <span className="muted"> · {extra}</span>}
            {live.length === 0 && <span className="muted"> · no copy in RecallSpring</span>}
            {(files.length > 1 || files.some((f) => f.why)) && (
              <ul className="small" style={{ margin: "2px 0 0", paddingLeft: 18 }} aria-label={`Files of ${name}`}>
                {files.map((f) => (
                  <li key={f.id}>
                    {f.removed ? <span className="muted">{f.filename} (removed)</span> : <Link to={`/library/${f.id}`}>{f.filename}</Link>}
                    {f.why && <span className="muted"> · {f.why}</span>}
                    {f.strength === "weak" && (
                      <span className="chip warn" style={{ marginLeft: 6 }} title="Only inferred, e.g. from the numbering: check that this file belongs to the paper.">
                        Weak evidence
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {p.use && (
              <div className={p.use === "style" ? "small" : "small muted"}>
                {p.use === "style" ? <span className="chip">Style only</span> : null} {USE[p.use]}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Whether the learner confirmed the analysis (ADR-013 §1). */
export function ProfileConfirmation({ profile }: { profile: TargetProfile }) {
  if (profile.confirmation === "confirmed")
    return (
      <span className="small">
        Confirmed by you{profile.confirmed_at ? ` on ${dateTime(profile.confirmed_at)}` : ""}
        {profile.confirmed_via === "assistant" ? " (through your assistant)" : ""}.
      </span>
    );
  if (profile.confirmation === "unconfirmed")
    return <span className="small">Not confirmed yet: check the analysis against the paper.</span>;
  return <span className="small muted">Analysed before analyses were confirmed. Ask your assistant to analyse the paper again.</span>;
}

/** The learner confirms the latest analysis here; corrections go through the assistant, which reads the paper again. */
export function ConfirmProfile({ targetId, profile }: { targetId: string; profile: TargetProfile }) {
  const qc = useQueryClient();
  const confirm = useMutation({
    mutationFn: () => request(`/targets/${targetId}/profile/confirm`, { method: "POST", json: { profile_id: profile.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["targets", targetId] });
      void qc.invalidateQueries({ queryKey: ["courses"] });
    },
  });
  return (
    <div className="stack" style={{ gap: 6 }}>
      <ProfileConfirmation profile={profile} />
      {profile.confirmation === "unconfirmed" && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn small" disabled={confirm.isPending} onClick={() => confirm.mutate()}>
              It matches the paper
            </button>
          </div>
          <span className="tiny muted">Something is wrong? Tell your assistant: it reads the paper again and saves a new analysis.</span>
        </>
      )}
      {confirm.error && <ErrorNote error={confirm.error} />}
    </div>
  );
}

function Topics({ r }: { r: PlanRationale }) {
  if (r.topics.length === 0) return null;
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Topics on the old papers</caption>
        <thead>
          <tr>
            <th>Topic</th>
            <th>On the paper</th>
            <th>Concepts</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {r.topics.map((t, i) => (
            <tr key={i} className={t.style_only ? "muted" : undefined}>
              <td style={{ minWidth: 140 }}>
                <span style={{ fontWeight: 600 }}>{t.label}</span>
                {t.from_web && (
                  <div>
                    <span className="chip" title="Added from the web at your request, not from your course material">
                      From the web
                    </span>
                  </div>
                )}
              </td>
              <td className="small">
                {size(t)}
                {t.where && <div className="muted">{t.where}</div>}
                {t.papers.length > 1 && <div className="muted">on {t.papers.length} papers</div>}
              </td>
              <td className="small">
                {t.concepts.length === 0 ? (
                  <span className="muted">—</span>
                ) : (
                  <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 4 }}>
                    {t.concepts.map((c) => (
                      <li key={c.id}>
                        <Link to={`/concepts/${c.id}`}>{c.term}</Link> <span className={STATE_CHIP[c.state]}>{STATE_LABEL[c.state]}</span>
                        {!c.in_scope && <span className="tiny muted"> · outside this exam's scope</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
              <td>
                <span className={STATUS[t.status].tone}>{STATUS[t.status].label}</span>
                {t.style_only && (
                  <div className="tiny muted" style={{ marginTop: 4 }}>
                    Style only: does not change your plan
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Today({ r }: { r: PlanRationale }) {
  const today = r.today;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {today.items.length === 0 ? (
        <p className="small muted">{today.note}</p>
      ) : (
        <ol className="small" style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6 }}>
          {today.items.map((i) => (
            <li key={`${i.category}-${i.concept_id}`}>
              {CATEGORY_WORD[i.category] ?? i.category} <Link to={`/concepts/${i.concept_id}`}>{i.term}</Link>
              <span className="muted"> · {i.minutes} min</span>
              <div className="tiny muted">
                {i.topics.length > 0
                  ? `On the paper: ${i.topics.map((t) => (t.points != null || t.share != null ? `${t.label} (${size(t)})` : t.label)).join(", ")}`
                  : "Not on the old papers"}
                {" — "}
                {i.why}
              </div>
            </li>
          ))}
        </ol>
      )}
      {today.items.length > 0 && today.other_courses_items > 0 && (
        <p className="tiny muted">Today's plan also has {plural(today.other_courses_items, "item")} for other courses.</p>
      )}
      <details>
        <summary className="small">How RecallSpring orders the work</summary>
        <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18, display: "grid", gap: 4 }}>
          {r.order_rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function WhyThisPlanBody({ r }: { r: PlanRationale }) {
  const c = r.coverage;
  const b = r.bloom;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <section className="stack" style={{ gap: 6 }} aria-labelledby="why-paper">
        <h3 id="why-paper">
          What the old papers show
        </h3>
        {r.profile ? (
          <>
            <div className="small">
              <Papers profile={r.profile} />
            </div>
            {r.profile.notes && (
              <div className="small">
                <span className="muted">Your assistant's note: </span>
                <span className="pre">{r.profile.notes}</span>
              </div>
            )}
            <ConfirmProfile targetId={r.target.id} profile={r.profile} />
          </>
        ) : (
          <p className="small muted">No old paper has been analysed. Give your assistant an old kolokvij or exam to analyse.</p>
        )}
      </section>

      {r.topics.length > 0 && (
        <section className="stack" style={{ gap: 6 }} aria-labelledby="why-coverage">
          <h3 id="why-coverage">
            How much of it you have covered
          </h3>
          {c && (
            <p className="small">
              {c.studied_percent} % studied · {c.ready_percent} % getting there or solid · {c.solid_percent} % solid
              {c.not_in_material_percent > 0 && ` · ${c.not_in_material_percent} % not in your material`}
              <span className="muted"> — {BASIS[c.basis] ?? ""}</span>
            </p>
          )}
          <Topics r={r} />
          {r.not_on_paper.count > 0 && (
            <p className="tiny muted">
              In this exam's scope but not on the old papers: {r.not_on_paper.terms.join(", ")}
              {r.not_on_paper.count > r.not_on_paper.terms.length ? ` and ${r.not_on_paper.count - r.not_on_paper.terms.length} more` : ""}.
            </p>
          )}
        </section>
      )}

      {Object.keys(b.paper).length > 0 && (
        <section className="stack" style={{ gap: 4 }} aria-labelledby="why-bloom">
          <h3 id="why-bloom">
            Kinds of questions
          </h3>
          <p className="small">On the paper: {bloomLine(b.paper)}</p>
          <p className="small">What you practised for this exam: {bloomLine(b.practised)}</p>
          <p className="tiny muted">Your practice limit: {BLOOM[b.practice_limit] ?? `level ${b.practice_limit}`} (level {b.practice_limit}).</p>
        </section>
      )}

      <section className="stack" style={{ gap: 6 }} aria-labelledby="why-today">
        <h3 id="why-today">
          Today's work for this course{r.today.minutes > 0 ? ` · ${r.today.minutes} min` : ""}
        </h3>
        <Today r={r} />
        {r.fit.capacity && <p className="small">{r.fit.capacity.message}</p>}
      </section>

      {r.limits.length > 0 && (
        <section className="stack" style={{ gap: 6 }} aria-labelledby="why-limits">
          <h3 id="why-limits">
            What this cannot tell you
          </h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
            {r.limits.map((l) => (
              <li key={l.code}>{l.message}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** The section itself; Home's "Why?" links here with #why. */
export function WhyThisPlan({ targetId }: { targetId: string }) {
  const q = useRationale(targetId);
  const { hash } = useLocation();
  const ready = !!q.data;
  useEffect(() => {
    const el = ready && hash === "#why" ? document.getElementById("why") : null;
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "start" });
  }, [ready, hash]);
  return (
    <Card id="why" title="Why this plan" meta="Computed by RecallSpring from your exam analysis and answers">
      <Async q={q} lines={4}>
        {(r) => <WhyThisPlanBody r={r} />}
      </Async>
    </Card>
  );
}

