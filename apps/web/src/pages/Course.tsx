import { SavedPhotos } from "../components/Photos";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { get } from "../api";
import { Async, BandChip, BandMeter, Card, Difficulty, Empty, GradeChip, PageHead, StudyChip, StudyMeter } from "../components/ui";
import { CourseDialog, CourseDot, FocusControl, groupPath } from "../components/organise";
import { TargetDialog } from "../components/TargetDialog";
import { SelfAssessOffer, SelfCheckNote, SelfTag } from "../components/SelfAssess";
import { ATTEMPT_KIND, CAPTURED_VIA, STUDY_LABEL, TARGET_KIND, dateLabel, dateTime, gradedBy, plural, relativeDay } from "../format";
import { useCourseOverview, useGroups } from "../queries";
import type { AttemptDetail, AttemptRow, ConceptRow, CourseOverview, StudyStatus, Target, TargetProfile } from "../types";
import { NewNoteButton, NoteList } from "./Notes";
import { FolderBrowser } from "./Library";
import { QuizTable } from "./Simulations";

const TABS = [
  { id: "concepts", label: "Concepts" },
  { id: "targets", label: "Exams" },
  { id: "materials", label: "Materials" },
  { id: "notes", label: "Notes" },
  { id: "simulations", label: "Simulations" },
  { id: "answers", label: "Answers" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function CoursePage() {
  const { courseId = "" } = useParams();
  const [params] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "concepts") as Tab;
  const q = useCourseOverview(courseId);
  const groups = useGroups();
  const [editCourse, setEditCourse] = useState(false);

  return (
    <div className="page">
      <Async q={q} lines={8}>
        {(o) => {
          const active = o.targets.find((t) => t.id === o.active_target_id);
          const isInterest = o.course.kind === "interest";
          const tabs = TABS.filter((t) => !(isInterest && t.id === "targets"));
          const counts: Record<Tab, number | null> = {
            concepts: o.concepts.length,
            targets: o.targets.length,
            materials: o.sources.length,
            notes: o.notes,
            simulations: o.quizzes.length,
            answers: null,
          };
          return (
            <>
              <PageHead
                title={
                  <span className="row" style={{ gap: 10 }}>
                    <CourseDot color={o.course.color} />
                    {o.course.title}
                    {isInterest && <span className="chip">Interest</span>}
                    {o.course.status === "archived" && <span className="chip">Archived</span>}
                  </span>
                }
                sub={
                  isInterest
                    ? "Personal interest: no exam, no deadline."
                    : [groupPath(groups.data, o.course.group_id), o.course.description].filter(Boolean).join(" · ") || undefined
                }
                crumbs={[{ to: "/courses", label: "Courses" }]}
              >
                <FocusControl course={o.course} />
                <button type="button" className="btn" onClick={() => setEditCourse(true)}>
                  {isInterest ? "Edit interest" : "Edit course"}
                </button>
              </PageHead>
              {editCourse && <CourseDialog course={o.course} open onClose={() => setEditCourse(false)} />}
              <div className="grid cols-2">
                {isInterest ? (
                  <Card title="Goal" tint>
                    {o.course.description ? (
                      <p className="small pre">{o.course.description}</p>
                    ) : (
                      <p className="small muted">
                        No goal yet. Your assistant asks for it at the start of a session, or add it with Edit interest.
                      </p>
                    )}
                  </Card>
                ) : (
                <Card title="Next exam" tint>
                  {active ? (
                    <div className="stack" style={{ gap: 6 }}>
                      <div style={{ fontWeight: 650 }}>
                        {active.name} · {dateLabel(active.due_date)}
                      </div>
                      <div className="small muted">
                        {active.days_left >= 0 ? `${plural(active.days_left, "day")} left` : "Date passed"} ·{" "}
                        {plural(active.concepts_in_scope, "concept")} in scope
                      </div>
                      <div className="small pre">{active.scope_description}</div>
                    </div>
                  ) : (
                    <p className="small muted">No exam or midterm is set. Your assistant asks for it at the start of a study session.</p>
                  )}
                </Card>
                )}
                <Card title="Progress" tint>
                  <div className="stack">
                    <StudyMeter progress={o.progress} />
                    <BandMeter progress={o.progress} />
                    <p className="tiny muted">{o.note}</p>
                  </div>
                </Card>
              </div>

              <nav className="tabs" aria-label="Course sections">
                {tabs.map((t) => (
                  <Link key={t.id} to={`?tab=${t.id}`} aria-current={tab === t.id ? "page" : undefined} replace>
                    {t.label}
                    {counts[t.id] !== null && <span className="n">{counts[t.id]}</span>}
                  </Link>
                ))}
              </nav>

              {tab === "concepts" && <ConceptsTab o={o} />}
              {tab === "targets" && !isInterest && <TargetsTab targets={o.targets} activeId={o.active_target_id} courseId={o.course.id} />}
              {tab === "materials" && (
                <FolderBrowser
                  courseId={o.course.id}
                  folderId={params.get("folder")}
                  href={(id) => `?tab=materials${id ? `&folder=${id}` : ""}`}
                />
              )}
              {tab === "notes" && (
                <div className="stack">
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <NewNoteButton courseId={o.course.id} />
                  </div>
                  <NoteList courseId={o.course.id} />
                </div>
              )}
              {tab === "simulations" && <QuizTable quizzes={o.quizzes} />}
              {tab === "answers" && <AnswersTab courseId={o.course.id} />}
            </>
          );
        }}
      </Async>
    </div>
  );
}

const STUDY_FILTERS: (StudyStatus | "all")[] = ["all", "not_studied", "studied", "known"];

function ConceptsTab({ o }: { o: CourseOverview }) {
  const [filter, setFilter] = useState<StudyStatus | "all">("all");
  const [text, setText] = useState("");
  const rows = useMemo(() => {
    const needle = text.trim().toLocaleLowerCase();
    return o.concepts.filter(
      (c) => (filter === "all" || c.study_status === filter) && (!needle || c.term.toLocaleLowerCase().includes(needle)),
    );
  }, [o.concepts, filter, text]);

  if (o.concepts.length === 0) {
    return <Empty title="No concepts yet">Your assistant creates concepts from your material when it reads it with you.</Empty>;
  }
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" role="group" aria-label="Filter by study status">
          {STUDY_FILTERS.map((f) => (
            <button key={f} type="button" className="chip chip-filter" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? `All ${o.concepts.length}` : `${STUDY_LABEL[f]} ${o.progress.study[f]}`}
            </button>
          ))}
        </div>
        <label style={{ minWidth: 220 }}>
          <span className="sr-only">Find a concept</span>
          <input type="search" placeholder="Find a concept" value={text} onChange={(e) => setText(e.target.value)} />
        </label>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Concept</th>
              <th>Study</th>
              <th>Knowledge</th>
              <th>Difficulty</th>
              <th>Next review</th>
              <th>Where in the material</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <ConceptTr key={c.id} c={c} />
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="muted small">No concept matches.</p>}
    </div>
  );
}

function ConceptTr({ c }: { c: ConceptRow }) {
  return (
    <tr>
      <td>
        <Link to={`/concepts/${c.id}`} style={{ fontWeight: 600 }}>
          {c.term}
        </Link>
      </td>
      <td>
        <StudyChip status={c.study_status} />
      </td>
      <td>
        <BandChip band={c.band} />
      </td>
      <td>
        <Difficulty value={c.difficulty} source={c.difficulty_source} />
      </td>
      <td>
        {c.review ? (
          <span className={c.review.is_due ? "chip warn" : undefined} title={c.review.reason ?? undefined}>
            {c.review.is_due ? "Due" : dateLabel(c.review.due_at)}
          </span>
        ) : (
          <span className="muted small">Not scheduled</span>
        )}
      </td>
      <td className="small muted">{c.sections.map((s) => s.label).join(", ") || "—"}</td>
    </tr>
  );
}

const BLOOM = ["", "Remember", "Understand", "Apply", "Analyse", "Evaluate", "Create"];
const pct = (x: unknown) => `${Math.round(Number(x) * 100)}%`;

/** The assistant's exam-profile fields, summarised as plain text (never rendered as markup). */
function ItemTypes({ value }: { value: TargetProfile["item_types"] }) {
  if (!value?.length) return <span className="muted">—</span>;
  return <>{value.map((v) => `${v.type} ${pct(v.share)}`).join(" · ")}</>;
}

function BloomMix({ value }: { value: TargetProfile["bloom_mix"] }) {
  const entries = Object.entries(value ?? {}).sort(([a], [b]) => Number(a) - Number(b));
  if (!entries.length) return <span className="muted">—</span>;
  return <>{entries.map(([level, share]) => `${BLOOM[Number(level)] ?? `Level ${level}`} ${pct(share)}`).join(" · ")}</>;
}

function TopicWeights({ value }: { value: TargetProfile["topic_weights"] }) {
  if (!value?.length) return <span className="muted">—</span>;
  return <>{value.map((w) => `${w.label} ×${w.weight}`).join(" · ")}</>;
}

const GOAL: Record<string, string> = { long_term: "Remember it long-term", exam_only: "Only for this exam" };

function TargetsTab({ targets, activeId, courseId }: { targets: Target[]; activeId: string | null; courseId: string }) {
  const [editing, setEditing] = useState<Target | null>(null);
  const [adding, setAdding] = useState(false);
  const dialogs = (
    <>
      {editing && (
        <TargetDialog key={editing.id} target={{ ...editing, course_id: courseId }} open onClose={() => setEditing(null)} />
      )}
      {adding && <TargetDialog courseId={courseId} open onClose={() => setAdding(false)} />}
    </>
  );
  if (targets.length === 0) {
    return (
      <>
        <Empty title="No exams or midterms yet">
          Add one here, or your assistant asks what you prepare for at the start of a study session and records it.
          <div style={{ marginTop: 10 }}>
            <button type="button" className="btn primary" onClick={() => setAdding(true)}>
              Add exam
            </button>
          </div>
        </Empty>
        {dialogs}
      </>
    );
  }
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <Link to="/exams" className="btn">
          Timeline
        </Link>
        <button type="button" className="btn primary" onClick={() => setAdding(true)}>
          Add exam
        </button>
      </div>
      {dialogs}
      {targets.map((t) => (
        <Card
          key={t.id}
          title={t.name}
          meta={`${TARGET_KIND[t.kind] ?? t.kind} · ${dateLabel(t.due_date)}`}
          action={
            <span className="row">
              {t.id === activeId ? (
                <span className="chip solid">Active</span>
              ) : (
                <span className={t.status === "passed" ? "chip good" : "chip"}>{t.status}</span>
              )}
              <Link to={`/exams/${t.id}`} className="btn small">
                Readiness
              </Link>
              <button type="button" className="btn small" onClick={() => setEditing(t)}>
                Edit
              </button>
            </span>
          }
        >
          <div className="stack">
            {!!t.duplicates?.length && (
              <div className="notice warn small">
                This looks like the same exam as{" "}
                {t.duplicates.map((id) => targets.find((x) => x.id === id)?.name ?? "another entry").join(", ")} (probably
                recorded from two chats). <Link to="/exams">Merge or delete it in Exams</Link>.
              </div>
            )}
            <dl className="kv">
              <dt>When</dt>
              <dd>
                {dateLabel(t.due_date)} ({t.days_left >= 0 ? `in ${plural(t.days_left, "day")}` : "passed"})
              </dd>
              <dt>Scope in your words</dt>
              <dd className="pre">{t.scope_description}</dd>
              <dt>Mapped to</dt>
              <dd>
                {t.scope.length === 0
                  ? "—"
                  : t.scope
                      .map((s) =>
                        s.kind === "pages" && s.pages
                          ? `${s.filename ?? "material"} pp. ${s.pages[0]}–${s.pages[1]}`
                          : s.kind === "source"
                            ? `${s.filename ?? "material"} (whole)`
                            : s.kind,
                      )
                      .join("; ")}{" "}
                · {plural(t.concepts_in_scope, "concept")}
              </dd>
              {t.goal && (
                <>
                  <dt>Goal</dt>
                  <dd>{GOAL[t.goal] ?? t.goal}</dd>
                </>
              )}
              {t.result && (
                <>
                  <dt>Result</dt>
                  <dd>{t.result}</dd>
                </>
              )}
              {t.notes && (
                <>
                  <dt>Notes</dt>
                  <dd className="pre">{t.notes}</dd>
                </>
              )}
            </dl>
            {t.profile && (
              <details>
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>Exam style from an old paper</summary>
                <div className="stack" style={{ marginTop: 10 }}>
                  <dl className="kv">
                    <dt>Question types</dt>
                    <dd>
                      <ItemTypes value={t.profile.item_types} />
                    </dd>
                    <dt>Thinking levels</dt>
                    <dd>
                      <BloomMix value={t.profile.bloom_mix} />
                    </dd>
                    <dt>Topic weights</dt>
                    <dd>
                      <TopicWeights value={t.profile.topic_weights} />
                    </dd>
                    <dt>Examples</dt>
                    <dd>
                      {t.profile.example_items?.length ? (
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {t.profile.example_items.map((x, i) => (
                            <li key={i} className="pre">
                              {x}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </dd>
                    {t.profile.notes && (
                      <>
                        <dt>Notes</dt>
                        <dd className="pre">{t.profile.notes}</dd>
                      </>
                    )}
                  </dl>
                  <p className="tiny muted">
                    Analysed by {t.profile.derived_by === "assistant" ? "your assistant" : t.profile.derived_by} on {dateTime(t.profile.created_at)}.
                  </p>
                </div>
              </details>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}

/** A strength or gap as the grader stored it: usually text, sometimes {text} / {point}. */
function itemText(x: unknown): string {
  if (typeof x === "string") return x;
  if (x && typeof x === "object") {
    const o = x as Record<string, unknown>;
    for (const k of ["text", "point", "description", "label"]) if (typeof o[k] === "string") return o[k] as string;
  }
  return "";
}

const CONFIDENCE: Record<string, string> = { high: "high", medium: "medium", low: "low" };

/** The learner's exact answer and the explanation of its grade, opened from the Answers tab. */
function AnswerDetail({ row }: { row: AttemptRow }) {
  const q = useQuery({ queryKey: ["attempt", row.attempt_id], queryFn: () => get<AttemptDetail>(`/attempts/${row.attempt_id}`) });
  return (
    <Async q={q} lines={3}>
      {(a) => {
        const current = a.assessments.find((s) => s.id === a.effective_assessment_id) ?? a.assessments.at(-1);
        const strengths = (current?.strengths ?? []).map(itemText).filter(Boolean);
        const gaps = (current?.gaps ?? []).map(itemText).filter(Boolean);
        const earlier = a.assessments.filter((s) => s.id !== current?.id);
        return (
          <div className="stack answer-detail" style={{ gap: 10 }}>
            <div>
              <div className="tiny muted">
                Your answer · {a.answer_mode === "open_notes" ? "with notes or material" : "from memory"} · {dateTime(a.submitted_at)}
              </div>
              {(a.kind !== "answer" || a.answer_text) && (
                <div className="answer pre">{a.kind === "answer" ? a.answer_text : ATTEMPT_KIND[a.kind] ?? a.kind}</div>
              )}
              <SavedPhotos ids={a.photos ?? []} label="Photos of your work" />
            </div>
            {!current ? (
              <div className="stack" style={{ gap: 8 }}>
                <p className="small muted" style={{ margin: 0 }}>
                  {a.status === "saved_awaiting_evaluation" ? "Not graded yet: ask your assistant for feedback." : "No grade recorded."}
                </p>
                {a.kind === "answer" && <SelfAssessOffer attemptId={a.id} />}
              </div>
            ) : (
              <div className="feedback stack" style={{ gap: 8 }}>
                <SelfCheckNote attempt={a} />
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <GradeChip grade={current.grade} status={current.status} />
                  <SelfTag a={current} />
                  <span className="tiny muted">
                    {gradedBy(current.evaluator_kind, row.grader)} · confidence {CONFIDENCE[current.confidence] ?? current.confidence}
                    {current.status === "provisional" && " · provisional"}
                    {current.evidence_refs.length > 0 && ` · based on ${plural(current.evidence_refs.length, "passage")} of your material`}
                  </span>
                </div>
                {current.feedback && <div className="pre small">{current.feedback}</div>}
                {strengths.length > 0 && (
                  <div className="small">
                    <strong>What was good</strong>
                    <ul>
                      {strengths.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {gaps.length > 0 && (
                  <div className="small">
                    <strong>What was missing</strong>
                    <ul>
                      {gaps.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {current.remediation && (
                  <div className="small">
                    <strong>Next step</strong>
                    <div className="pre">{current.remediation}</div>
                  </div>
                )}
                <div className="tiny muted">AI grades are study feedback, not a validated score.</div>
              </div>
            )}
            {earlier.length > 0 && (
              <details className="small">
                <summary style={{ cursor: "pointer" }}>Earlier grades ({earlier.length})</summary>
                <ul>
                  {earlier.map((s) => (
                    <li key={s.id}>
                      {dateTime(s.created_at)} · {s.grade ?? "ungraded"}/4 · {s.status}
                      {s.feedback && <div className="pre muted">{s.feedback}</div>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        );
      }}
    </Async>
  );
}

export function AnswersTab({ courseId }: { courseId: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["attempts", courseId],
    queryFn: () => get<AttemptRow[]>("/attempts", { course_id: courseId, limit: 200 }),
  });
  return (
    <Async q={q}>
      {(rows) =>
        rows.length === 0 ? (
          <Empty title="No answers yet">Answers you give in your assistant's forms are saved here word for word.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Saved</th>
                  <th>Question</th>
                  <th>Answer</th>
                  <th>Grade</th>
                  <th>Captured</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <Fragment key={a.attempt_id}>
                  <tr className={open === a.attempt_id ? "row-open" : undefined}>
                    <td className="small nowrap" title={dateTime(a.submitted_at)}>
                      {relativeDay(a.submitted_at)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="linklike row-toggle"
                        aria-expanded={open === a.attempt_id}
                        aria-controls={`answer-${a.attempt_id}`}
                        onClick={() => setOpen(open === a.attempt_id ? null : a.attempt_id)}
                        title="Show your answer and the grade explanation"
                      >
                        <span aria-hidden="true">{open === a.attempt_id ? "▾ " : "▸ "}</span>
                        {a.question}
                      </button>
                      {a.quiz_id && (
                        <div className="tiny">
                          <Link to={`/simulations/${a.quiz_id}`}>From a simulation</Link>
                        </div>
                      )}
                    </td>
                    <td className="small">{ATTEMPT_KIND[a.kind] ?? a.kind}</td>
                    <td>
                      {a.status === "saved_awaiting_evaluation" ? (
                        <span className="chip">Awaiting feedback</span>
                      ) : (
                        <GradeChip grade={a.grade} status={a.assessment_status} />
                      )}
                    </td>
                    <td className="small muted">{CAPTURED_VIA[a.captured_via] ?? a.captured_via}</td>
                  </tr>
                  {open === a.attempt_id && (
                    <tr id={`answer-${a.attempt_id}`} className="detail-row">
                      <td colSpan={5}>
                        <AnswerDetail row={a} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </Async>
  );
}
