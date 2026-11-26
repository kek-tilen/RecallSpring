import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { request } from "../api";
import { CopyButton } from "../components/Copy";
import { StudyIn } from "../components/StudyIn";
import { AwaitingGrade, QuizForm } from "../components/QuizForm";
import { MathText } from "../components/Markdown";
import { Async, Card, Empty, ErrorNote, GradeChip, PageHead } from "../components/ui";
import { ATTEMPT_KIND, dateLabel, dateTime, gradedBy, plural } from "../format";
import { courseTitles, keys, useCourses, useQuiz, useQuizzes } from "../queries";
import type { QuizComparison, QuizItemView, QuizSummary, QuizView } from "../types";

/** A retake answers seen questions; the first version stays the benchmark (2026-11-26). */
export function VersionChips({ q }: { q: { version?: number; same_day_practice?: boolean } }) {
  if (!q.version || q.version < 2) return null;
  return (
    <>
      <span className="chip" title="The same questions again; the first version stays the benchmark.">
        Version {q.version} · seen questions
      </span>
      {q.same_day_practice && (
        <span className="chip" title="Taken the same day as an earlier version: it does not change your review schedule.">
          Practice only
        </span>
      )}
    </>
  );
}

export function similarMessage(quiz: { quiz_id: string; title: string; course_id: string }) {
  return `Let's do a new simulation like "${quiz.title}" (quiz_id ${quiz.quiz_id}, course_id ${quiz.course_id}): similar, new questions on the same topics, kinds and Bloom levels, never the same questions.`;
}

/** Take a submitted simulation again, or ask for similar, new questions (2026-11-26). */
function Retake({ quiz, course }: { quiz: QuizView; course: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const missed = quiz.items.filter((i) => (i.earned ?? 0) < i.points).length;
  const pending = quiz.pending_items ?? 0;
  const go = useMutation({
    mutationFn: (scope: "all" | "not_full") =>
      request<{ quiz_id: string; version: number }>(`/quizzes/${quiz.quiz_id}/retake`, { method: "POST", json: { scope } }),
    onSuccess: (made) => {
      void qc.invalidateQueries({ queryKey: ["quizzes"] });
      void qc.invalidateQueries({ queryKey: keys.course(quiz.course_id) });
      navigate(`/simulations/${made.quiz_id}`);
    },
  });
  return (
    <Card title="Take it again">
      <div className="stack" style={{ gap: 10 }}>
        <p className="small" style={{ margin: 0 }}>
          A retake is a new version with the same questions; this one stays as it is, and the versions are compared per
          question. The first version stays the benchmark. Taken the same day as an earlier version, a retake is practice only:
          it does not change your review schedule.
        </p>
        <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
          <button type="button" className="btn small" disabled={go.isPending} onClick={() => go.mutate("all")}>
            Retake all questions
          </button>
          <button
            type="button"
            className="btn small"
            disabled={go.isPending || pending > 0 || missed === 0}
            onClick={() => go.mutate("not_full")}
          >
            Retake questions without full points ({missed})
          </button>
          <StudyIn course={{ id: quiz.course_id, title: course }} ask={{ label: "Similar, new questions", message: similarMessage(quiz) }} />
        </div>
        {pending > 0 && <span className="tiny muted">Retaking only the missed questions waits until every answer is graded.</span>}
        {go.error && <ErrorNote error={go.error} />}
      </div>
    </Card>
  );
}

function points(v: { earned: number | null } | null, max: number) {
  if (!v) return "—";
  return v.earned === null ? "awaiting a grade" : `${v.earned} / ${max}`;
}

/** Every version side by side, per question of the first version (2026-11-26). */
function Comparison({ c, current }: { c: QuizComparison; current: string }) {
  return (
    <Card title="All versions" meta={plural(c.versions.length, "version")}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Question</th>
              {c.versions.map((v) => (
                <th key={v.quiz_id} className="nowrap">
                  {v.quiz_id === current ? (
                    `Version ${v.version}`
                  ) : (
                    <Link to={`/simulations/${v.quiz_id}`}>Version {v.version}</Link>
                  )}
                  <div className="tiny muted">
                    {v.version === 1 ? "Benchmark" : v.scope === "not_full" ? "Missed only" : "All questions"}
                    {v.same_day_practice ? " · practice only" : ""}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.questions.map((q) => (
              <tr key={q.question_id}>
                <td>
                  {q.position}. <MathText text={q.prompt.length > 90 ? `${q.prompt.slice(0, 90)}…` : q.prompt} />
                </td>
                {q.versions.map((v, i) => (
                  <td key={c.versions[i]!.quiz_id} className="nowrap">
                    {points(v, q.points)}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <td>
                <strong>Total</strong>
              </td>
              {c.versions.map((v) => (
                <td key={v.quiz_id} className="nowrap">
                  {v.status === "submitted" ? `${v.earned_points} / ${v.max_points}` : "Not submitted"}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Score({ q }: { q: Pick<QuizSummary, "status" | "earned_points" | "max_points" | "pending_items"> }) {
  if (q.status === "open") return <span className="chip warn">Not submitted</span>;
  return (
    <span className="row" style={{ gap: 6 }}>
      <strong>
        {q.earned_points} / {q.max_points}
      </strong>
      {!!q.pending_items && <span className="chip">{q.pending_items} awaiting a grade</span>}
    </span>
  );
}

export function QuizTable({ quizzes, titles }: { quizzes: QuizSummary[]; titles?: Record<string, string> }) {
  if (quizzes.length === 0) {
    return <Empty title="No simulations yet">Ask your assistant for a midterm simulation once you have studied the material.</Empty>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Simulation</th>
            {titles && <th>Course</th>}
            <th>Questions</th>
            <th>Created</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {quizzes.map((q) => (
            <tr key={q.id}>
              <td>
                <Link to={`/simulations/${q.id}`} style={{ fontWeight: 600 }}>
                  {q.title}
                </Link>
                {q.mode === "diagnostic" && <span className="chip" style={{ marginLeft: 8 }}>Diagnostic</span>}
                {(q.version ?? 1) > 1 && (
                  <span style={{ marginLeft: 8 }}>
                    <VersionChips q={q} />
                  </span>
                )}
              </td>
              {titles && <td className="small">{titles[q.course_id] ?? ""}</td>}
              <td>{q.items}</td>
              <td className="small nowrap">{dateLabel(q.created_at)}</td>
              <td>
                <Score q={q} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SimulationsPage() {
  const q = useQuizzes();
  const courses = useCourses();
  return (
    <div className="page">
      <PageHead
        title="Simulations"
        sub="Midterm and exam simulations. Answer open ones here or in your assistant's form; multiple-choice is graded from the answer key, open answers by your assistant."
      />
      <Async q={q}>{(quizzes) => <QuizTable quizzes={quizzes} titles={courseTitles(courses.data)} />}</Async>
    </div>
  );
}

function Item({ item, submitted }: { item: QuizItemView; submitted: boolean }) {
  const picked = item.answer?.match(/^([A-H])\)/)?.[1];
  return (
    <li className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <strong>
          {item.position}. <MathText text={item.prompt} />
        </strong>
        <span className="small muted">
          {submitted && item.earned !== null && item.earned !== undefined ? `${item.earned} / ` : ""}
          {plural(item.points, "point")}
        </span>
      </div>
      {item.type === "mcq" && item.options && (
        <ul className="options">
          {item.options.map((o) => {
            const correct = submitted && item.correct_option === o.key;
            const mine = picked === o.key;
            return (
              <li key={o.key} className={[correct ? "correct" : "", mine ? "picked" : ""].join(" ")}>
                <span className="key">{o.key}</span>
                <span style={{ flex: 1 }}>
                  <MathText text={o.text} />
                </span>
                {mine && <span className="chip">Your answer</span>}
                {correct && <span className="chip good">Correct</span>}
              </li>
            );
          })}
        </ul>
      )}
      {submitted && item.type === "open" && (
        <div className="answer pre">{item.kind === "answer" ? item.answer : ATTEMPT_KIND[item.kind ?? ""] ?? "No answer"}</div>
      )}
      {submitted && item.type === "mcq" && !picked && <div className="small muted">{ATTEMPT_KIND[item.kind ?? ""] ?? "No answer"}</div>}
      {submitted && (
        <div className="row">
          {item.grade === null || item.grade === undefined ? (
            item.type === "open" && item.kind === "answer" ? (
              <span className="chip">Answer saved · waiting for a grade</span>
            ) : null
          ) : (
            <GradeChip grade={item.grade} status={item.assessment_status} />
          )}
          {item.unsure && <span className="chip">Unsure</span>}
          {item.guessing && <span className="chip">Guess</span>}
        </div>
      )}
      {item.feedback && (
        <div className="feedback">
          <div className="tiny muted">Feedback from {gradedBy(item.graded_by, item.grader)}</div>
          <div className="pre small">{item.feedback}</div>
        </div>
      )}
      {submitted && item.expected_points && item.expected_points.length > 0 && (
        <details>
          <summary className="small" style={{ cursor: "pointer" }}>
            What a full answer covers
          </summary>
          <ul className="small">
            {item.expected_points.map((p, i) => (
              <li key={i}>
                <MathText text={p} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

export function SimulationPage() {
  const { quizId = "" } = useParams();
  const q = useQuiz(quizId);
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  const [onlyMissed, setOnlyMissed] = useState(false);
  return (
    <div className="page">
      <Async q={q} lines={8}>
        {(quiz) => {
          const submitted = quiz.status === "submitted";
          const items = onlyMissed ? quiz.items.filter((i) => (i.earned ?? 0) < i.points) : quiz.items;
          return (
            <>
              <PageHead
                title={quiz.title}
                crumbs={[
                  { to: "/simulations", label: "Simulations" },
                  { to: `/courses/${quiz.course_id}?tab=simulations`, label: titles[quiz.course_id] ?? "Course" },
                ]}
                sub={
                  submitted
                    ? `Submitted ${quiz.submitted_at ? dateTime(quiz.submitted_at) : ""}`
                    : `Created ${dateTime(quiz.created_at)} · not submitted yet`
                }
              >
                {quiz.mode === "diagnostic" && <span className="chip">Diagnostic</span>}
                <VersionChips q={quiz} />
                {submitted && (
                  <Score
                    q={{ status: quiz.status, earned_points: quiz.earned_points ?? 0, max_points: quiz.max_points ?? 0, pending_items: quiz.pending_items ?? 0 }}
                  />
                )}
              </PageHead>
              {!submitted && (
                <>
                  <p className="small muted">
                    Answer here or in your assistant's form; both save to the same simulation. Answer keys appear after you submit.
                  </p>
                  <QuizForm key={quiz.quiz_id} quiz={quiz} />
                </>
              )}
              {submitted && !!quiz.pending_items && <AwaitingGrade quiz={quiz} />}
              {submitted && quiz.note && <p className="small muted">{quiz.note}</p>}
              {quiz.comparison && <Comparison c={quiz.comparison} current={quiz.quiz_id} />}
              {submitted && quiz.mode === "practice" && <Retake quiz={quiz} course={titles[quiz.course_id] ?? "this course"} />}
              {submitted && (
                <label className="row small">
                  <input type="checkbox" checked={onlyMissed} onChange={(e) => setOnlyMissed(e.target.checked)} />
                  Show only questions without full points
                </label>
              )}
              {submitted && (
                <Card>
                  <ol className="list" style={{ listStyle: "none" }}>
                    {items.map((i) => (
                      <Item key={i.question_id} item={i} submitted={submitted} />
                    ))}
                  </ol>
                </Card>
              )}
              <p className="tiny muted">
                Simulation ID: <span className="nowrap">{quiz.quiz_id}</span> <CopyButton text={quiz.quiz_id} label="Copy ID" className="btn small ghost" />
              </p>
            </>
          );
        }}
      </Async>
    </div>
  );
}
