import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { get, request } from "../api";
import { CourseDot } from "../components/organise";
import { Async, Empty, ErrorNote, GradeChip, PageHead } from "../components/ui";
import { GRADE_LABEL, dateLabel, gradeLabel, plural, shortDay } from "../format";
import { courseTitles, useCourses, useQuiz, useQuizzes } from "../queries";
import type { AttemptRow, CourseColor, QuizComparison, QuizSummary } from "../types";
import { AnswerDetail } from "./Course";

// Results (UI direction, 2026-11-27): "How did I answer?" Two views: simulations with their versions side by side,
// and every answer with its grade (filter by course and grade); each answer's feedback opens in place.

/** One simulation with its retakes: the first version is the benchmark, later ones follow in order. */
interface Family {
  first: QuizSummary;
  versions: QuizSummary[];
}

export function families(quizzes: QuizSummary[]): Family[] {
  const byId = new Map(quizzes.map((q) => [q.id, q]));
  const root = (q: QuizSummary): QuizSummary => {
    let at = q;
    for (let i = 0; at.retake_of && byId.has(at.retake_of) && i < 50; i += 1) at = byId.get(at.retake_of)!;
    return at;
  };
  const groups = new Map<string, QuizSummary[]>();
  for (const q of quizzes) groups.set(root(q).id, [...(groups.get(root(q).id) ?? []), q]);
  return [...groups.entries()]
    .map(([id, list]) => ({ first: byId.get(id)!, versions: list.sort((a, b) => (a.version ?? 1) - (b.version ?? 1)) }))
    .sort((a, b) => b.versions.at(-1)!.created_at.localeCompare(a.versions.at(-1)!.created_at));
}

function score(q: QuizSummary): string {
  if (q.status === "open") return "Not submitted";
  return `${q.earned_points ?? 0}/${q.max_points ?? 0}`;
}

function familyNote(f: Family): string {
  // "23 Nov": the course shows as its colour; its name is read out (UI direction, 2026-11-27)
  const parts = [shortDay(f.first.created_at).replace(/^\S+ /, "")];
  if (f.versions.length > 1) parts.push(plural(f.versions.length, "version"));
  if (f.first.mode === "diagnostic") parts.push("check first");
  if (f.first.status === "open") parts.push("not submitted");
  return parts.join(" · ");
}

function ViewTabs({ tab, base = "/simulations?" }: { tab: "simulations" | "answers"; base?: string }) {
  return (
    <nav className="views" aria-label="Results">
      <Link to={base.replace(/[?&]$/, "")} aria-current={tab === "simulations" ? "page" : undefined} replace={base !== "/simulations?"}>
        Simulations
      </Link>
      <Link to={`${base}view=answers`} aria-current={tab === "answers" ? "page" : undefined} replace={base !== "/simulations?"}>
        Answers
      </Link>
    </nav>
  );
}

export function ResultsPage() {
  const [params] = useSearchParams();
  const tab = params.get("view") === "answers" ? "answers" : "simulations";
  return (
    <div className="page">
      <div className="results-head">
        <PageHead title="Results" />
        <ViewTabs tab={tab} />
      </div>
      {tab === "simulations" ? <Simulations /> : <Answers />}
    </div>
  );
}

/** A course's Results tab: the same two views, for this course only. */
export function CourseResults({ courseId, answers }: { courseId: string; answers: boolean }) {
  return (
    <div className="stack">
      <ViewTabs tab={answers ? "answers" : "simulations"} base="?tab=results&" />
      {answers ? <Answers courseId={courseId} /> : <Simulations courseId={courseId} />}
    </div>
  );
}

// ---------------------------------------------------------------- simulations

function Simulations({ courseId }: { courseId?: string }) {
  const q = useQuizzes();
  const courses = useCourses();
  const colors = new Map((courses.data ?? []).map((c) => [c.id, c.color]));
  const titles = courseTitles(courses.data);
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <Async q={q} lines={5}>
      {(quizzes) => {
        const list = families(courseId ? quizzes.filter((x) => x.course_id === courseId) : quizzes);
        if (list.length === 0) {
          return <Empty title="No simulations yet">Ask your assistant for a midterm simulation once you have studied the material.</Empty>;
        }
        const chosen = list.find((f) => f.first.id === picked) ?? list[0]!;
        return (
          <>
            <div className="results-layout">
              <ul className="results-list" aria-label="Simulations">
                {list.map((f) => (
                  <li key={f.first.id}>
                    <FamilyRow f={f} color={colors.get(f.first.course_id)} course={titles[f.first.course_id] ?? ""} on={f === chosen} pick={() => setPicked(f.first.id)} />
                  </li>
                ))}
              </ul>
              <section className="results-detail" aria-labelledby="results-detail-title">
                <FamilyDetail f={chosen} />
              </section>
            </div>
            {!courseId && <LatestAnswers />}
          </>
        );
      }}
    </Async>
  );
}

function FamilyRow({ f, color, course, on, pick }: { f: Family; color: CourseColor | null | undefined; course: string; on: boolean; pick: () => void }) {
  const body = (
    <>
      <span className="results-row-what">
        <span className="results-row-title">
          <CourseDot color={color} /> {f.first.title}
        </span>
        <span className="muted small">
          {course && <span className="sr-only">{course}, </span>}
          {familyNote(f)}
        </span>
      </span>
      <span className="results-score">{score(f.first)}</span>
    </>
  );
  return (
    <>
      {/* Larger screens: pick it to see its versions beside the list. Phones: open the simulation. */}
      <button type="button" className={on ? "results-row on" : "results-row"} aria-pressed={on} onClick={pick}>
        {body}
      </button>
      <Link to={`/simulations/${f.first.id}`} className="results-row results-row-link">
        {body}
      </Link>
      {f.versions.slice(1).map((v) => (
        <Link key={v.id} to={`/simulations/${v.id}`} className="results-row results-row-link results-version">
          <span className="results-row-what">
            <span>Version {v.version} · seen questions</span>
            <span className="muted small">{v.same_day_practice ? "Practice only · same day" : dateLabel(v.created_at)}</span>
          </span>
          <span className="results-score">{score(v)}</span>
        </Link>
      ))}
    </>
  );
}

/** What the newest version is, in one line (UI direction, 2026-11-27). */
function versionNote(f: Family, c: QuizComparison | null): string {
  const last = f.versions.at(-1)!;
  if (f.first.status === "open") return "Not submitted yet: answer it here or in your assistant's form.";
  if (f.versions.length === 1) {
    return f.first.pending_items ? `${plural(f.first.pending_items, "answer")} still waiting for a grade.` : "One version so far.";
  }
  const scope = c?.versions.at(-1)?.scope;
  const what =
    scope === "not_full" ? `Version ${last.version} has only the questions without full points` : `Version ${last.version} repeats every question`;
  return `${what}; ${last.same_day_practice ? "practice only, not counted in readiness" : "version 1 stays the benchmark"}.`;
}

function FamilyDetail({ f }: { f: Family }) {
  const last = f.versions.at(-1)!;
  const q = useQuiz(f.first.id);
  return (
    <>
      <h2 id="results-detail-title" className="results-h">
        {f.first.title}
      </h2>
      <Async q={q} lines={4}>
        {(quiz) => (
          <>
            <p className="muted small results-detail-note">{versionNote(f, quiz.comparison ?? null)}</p>
            {quiz.comparison ? <Versions c={quiz.comparison} /> : <OneVersion items={quiz.items} />}
            <div className="results-actions">
              {last.status === "submitted" && last.mode === "practice" && <RetakeMissed f={f} c={quiz.comparison ?? null} />}
              <Link to={`/simulations/${last.id}`} className={last.status === "open" ? "btn small primary" : "btn small"}>
                {last.status === "open" ? "Answer it" : "Open answers"}
              </Link>
            </div>
          </>
        )}
      </Async>
    </>
  );
}

/** Retake without full points: a new version with only the questions the newest version did not get fully. */
function RetakeMissed({ f, c }: { f: Family; c: QuizComparison | null }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const last = f.versions.at(-1)!;
  const at = c ? c.versions.findIndex((v) => v.quiz_id === last.id) : -1;
  const missed = c && at >= 0 ? c.questions.filter((q) => q.versions[at] && (q.versions[at]!.earned ?? 0) < q.points).length : null;
  const waiting = !!last.pending_items;
  const go = useMutation({
    mutationFn: () => request<{ quiz_id: string }>(`/quizzes/${last.id}/retake`, { method: "POST", json: { scope: "not_full" } }),
    onSuccess: (made) => {
      void qc.invalidateQueries({ queryKey: ["quizzes"] });
      navigate(`/simulations/${made.quiz_id}`);
    },
  });
  return (
    <>
      <button
        type="button"
        className="btn small primary"
        disabled={go.isPending || waiting || missed === 0}
        title={waiting ? "Waits until every answer is graded." : missed === 0 ? "Every question has full points." : undefined}
        onClick={() => go.mutate()}
      >
        Retake without full points
      </button>
      {go.error && <ErrorNote error={go.error} />}
    </>
  );
}

function short(text: string, n = 70): string {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

/** A small grade chip as in the drawing ("Partial 2"); the full label is its accessible name. */
function Grade({ grade }: { grade: number }) {
  const tone = grade >= 3 ? "grade-mini good" : grade >= 1 ? "grade-mini warn" : "grade-mini bad";
  return (
    <span className={tone} title={gradeLabel(grade)} aria-label={gradeLabel(grade)}>
      {GRADE_LABEL[grade] ?? "Grade"} {grade}
    </span>
  );
}

function Versions({ c }: { c: QuizComparison }) {
  return (
    <table className="results-versions">
      <thead>
        <tr>
          <th scope="col">Question</th>
          {c.versions.map((v) => (
            <th key={v.quiz_id} scope="col">
              Version {v.version}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {c.questions.map((q) => (
          <tr key={q.question_id}>
            <td>{short(q.prompt)}</td>
            {q.versions.map((v, i) => (
              <td key={c.versions[i]!.quiz_id}>
                {!v ? (
                  <span className="muted">–</span>
                ) : v.grade === null ? (
                  <span className="muted small">{v.earned === null ? "waiting" : `${v.earned}/${q.points}`}</span>
                ) : (
                  <Grade grade={v.grade} />
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OneVersion({ items }: { items: { question_id: string; prompt: string; points: number; earned?: number | null; grade?: number | null }[] }) {
  return (
    <ul className="results-items">
      {items.map((i) => (
        <li key={i.question_id}>
          <span>{short(i.prompt)}</span>
          {i.grade !== null && i.grade !== undefined ? <Grade grade={i.grade} /> : <span className="muted small">{i.earned === null || i.earned === undefined ? "–" : `${i.earned}/${i.points}`}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Phones: the latest graded answers under the simulations, as in the drawing. */
function LatestAnswers() {
  const q = useAttempts();
  const graded = (q.data ?? []).filter((a) => a.grade !== null).slice(0, 5);
  if (graded.length === 0) return null;
  return (
    <section className="results-latest" aria-labelledby="results-latest-title">
      <h2 id="results-latest-title" className="results-h">
        Latest answers
      </h2>
      <ul className="results-answers">
        {graded.map((a) => (
          <li key={a.attempt_id}>
            <AnswerLine a={a} />
          </li>
        ))}
      </ul>
      <Link to="/simulations?view=answers" className="small">
        All answers
      </Link>
    </section>
  );
}

// ---------------------------------------------------------------- answers

const useAttempts = () => useQuery({ queryKey: ["attempts", "all"], queryFn: () => get<AttemptRow[]>("/attempts", { limit: 200 }) });

function AnswerLine({ a }: { a: AttemptRow }) {
  const what = a.concepts?.map((c) => c.term).join(", ") || short(a.question, 60);
  return (
    <>
      <span className="results-answer-what">
        <span>{what}</span>
        {a.feedback && <span className="muted small">{short(a.feedback.split(/(?<=[.!?])\s/)[0] ?? a.feedback, 80)}</span>}
      </span>
      {a.grade !== null ? <GradeChip grade={a.grade} status={a.assessment_status} /> : <span className="muted small">{a.kind === "answer" ? "Waiting for a grade" : "Not graded"}</span>}
    </>
  );
}

const GRADES = [
  ["all", "All grades"],
  ["waiting", "Waiting for a grade"],
  ["4", "Transfer (4)"],
  ["3", "Solid (3)"],
  ["2", "Partial (2)"],
  ["1", "Fragile (1)"],
  ["0", "No evidence (0)"],
] as const;

function Answers({ courseId }: { courseId?: string }) {
  const q = useAttempts();
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  const [picked, setCourse] = useState("all");
  const course = courseId ?? picked;
  const [grade, setGrade] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Async q={q} lines={6}>
      {(rows) => {
        const shown = rows.filter(
          (a) =>
            (course === "all" || a.course_id === course) &&
            (grade === "all" || (grade === "waiting" ? a.grade === null && a.kind === "answer" : a.grade === Number(grade))),
        );
        return (
          <>
            <div className="results-filters">
              {!courseId && (
              <label className="field">
                Course
                <select value={course} onChange={(e) => setCourse(e.target.value)}>
                  <option value="all">All courses</option>
                  {(courses.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </select>
              </label>
              )}
              <label className="field">
                Grade
                <select value={grade} onChange={(e) => setGrade(e.target.value)}>
                  {GRADES.map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {shown.length === 0 ? (
              <p className="muted">{rows.length === 0 ? "No answers yet." : "No answers match these filters."}</p>
            ) : (
              <ul className="results-answers" aria-label="Answers">
                {shown.map((a) => (
                  <li key={a.attempt_id} className={open === a.attempt_id ? "open" : undefined}>
                    <button
                      type="button"
                      className="results-answer"
                      aria-expanded={open === a.attempt_id}
                      onClick={() => setOpen(open === a.attempt_id ? null : a.attempt_id)}
                    >
                      <AnswerLine a={a} />
                    </button>
                    <span className="muted tiny results-answer-meta">
                      {titles[a.course_id] ?? ""} · {dateLabel(a.submitted_at)}
                      {a.quiz_id && (
                        <>
                          {" · "}
                          <Link to={`/simulations/${a.quiz_id}`}>simulation</Link>
                        </>
                      )}
                    </span>
                    {open === a.attempt_id && <AnswerDetail row={a} />}
                  </li>
                ))}
              </ul>
            )}
            <p className="tiny muted">AI grades are study feedback, not a score.</p>
          </>
        );
      }}
    </Async>
  );
}
