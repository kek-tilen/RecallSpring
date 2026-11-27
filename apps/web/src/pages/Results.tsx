import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { get } from "../api";
import { CourseDot } from "../components/organise";
import { Async, Empty, GradeChip, PageHead } from "../components/ui";
import { dateLabel, plural } from "../format";
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
  const parts = [dateLabel(f.first.created_at)];
  if (f.versions.length > 1) parts.push(plural(f.versions.length, "version"));
  if (f.first.mode === "diagnostic") parts.push("check first");
  if (f.first.status === "open") parts.push("not submitted");
  return parts.join(" · ");
}

function ViewTabs({ tab }: { tab: "simulations" | "answers" }) {
  return (
    <nav className="views" aria-label="Results">
      <Link to="/simulations" aria-current={tab === "simulations" ? "page" : undefined}>
        Simulations
      </Link>
      <Link to="/simulations?view=answers" aria-current={tab === "answers" ? "page" : undefined}>
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

// ---------------------------------------------------------------- simulations

function Simulations() {
  const q = useQuizzes();
  const courses = useCourses();
  const colors = new Map((courses.data ?? []).map((c) => [c.id, c.color]));
  const titles = courseTitles(courses.data);
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <Async q={q} lines={5}>
      {(quizzes) => {
        const list = families(quizzes);
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
            <LatestAnswers />
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
          {course ? `${course} · ` : ""}
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

function FamilyDetail({ f }: { f: Family }) {
  const last = f.versions.at(-1)!;
  const q = useQuiz(f.first.id);
  return (
    <>
      <h2 id="results-detail-title" className="results-h">
        {f.first.title}
      </h2>
      <p className="muted small results-detail-note">
        {f.versions.length > 1
          ? `Version 1 is the benchmark; later versions answer seen questions${last.same_day_practice ? ", and one taken the same day is practice only, not counted in readiness" : ""}.`
          : f.first.status === "open"
            ? "Not submitted yet: answer it here or in your assistant's form."
            : f.first.pending_items
              ? `${plural(f.first.pending_items, "answer")} still waiting for a grade.`
              : "One version so far."}
      </p>
      <Async q={q} lines={4}>
        {(quiz) => (quiz.comparison ? <Versions c={quiz.comparison} /> : <OneVersion items={quiz.items} />)}
      </Async>
      <div className="results-actions">
        <Link to={`/simulations/${last.id}`} className="btn small primary">
          {last.status === "open" ? "Answer it" : "Open answers"}
        </Link>
        {last.status === "submitted" && last.mode === "practice" && (
          <Link to={`/simulations/${last.id}#retake`} className="btn small">
            Take it again
          </Link>
        )}
      </div>
    </>
  );
}

function short(text: string, n = 70): string {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

function Versions({ c }: { c: QuizComparison }) {
  return (
    <div className="table-wrap results-table">
      <table>
        <thead>
          <tr>
            <th>Question</th>
            {c.versions.map((v) => (
              <th key={v.quiz_id} className="nowrap">
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
                <td key={c.versions[i]!.quiz_id} className="nowrap">
                  {!v ? <span className="muted">–</span> : v.grade === null ? <span className="muted small">{v.earned === null ? "waiting" : `${v.earned}/${q.points}`}</span> : <GradeChip grade={v.grade} />}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OneVersion({ items }: { items: { question_id: string; prompt: string; points: number; earned?: number | null; grade?: number | null }[] }) {
  return (
    <ul className="results-items">
      {items.map((i) => (
        <li key={i.question_id}>
          <span>{short(i.prompt)}</span>
          {i.grade !== null && i.grade !== undefined ? <GradeChip grade={i.grade} /> : <span className="muted small">{i.earned === null || i.earned === undefined ? "–" : `${i.earned}/${i.points}`}</span>}
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

function Answers() {
  const q = useAttempts();
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  const [course, setCourse] = useState("all");
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
