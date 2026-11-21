import { useState } from "react";
import { Link, useParams } from "react-router";
import { CopyButton } from "../components/Copy";
import { AwaitingClaude, QuizForm } from "../components/QuizForm";
import { Async, Card, Empty, GradeChip, PageHead } from "../components/ui";
import { ATTEMPT_KIND, dateLabel, dateTime, gradedBy, plural } from "../format";
import { courseTitles, useCourses, useQuiz, useQuizzes } from "../queries";
import type { QuizItemView, QuizSummary } from "../types";

function Score({ q }: { q: Pick<QuizSummary, "status" | "earned_points" | "max_points" | "pending_items"> }) {
  if (q.status === "open") return <span className="chip warn">Not submitted</span>;
  return (
    <span className="row" style={{ gap: 6 }}>
      <strong>
        {q.earned_points} / {q.max_points}
      </strong>
      {!!q.pending_items && <span className="chip">{q.pending_items} awaiting Claude</span>}
    </span>
  );
}

export function QuizTable({ quizzes, titles }: { quizzes: QuizSummary[]; titles?: Record<string, string> }) {
  if (quizzes.length === 0) {
    return <Empty title="No simulations yet">Ask Claude for a kolokvij simulation once you have studied the material.</Empty>;
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
        sub="Kolokvij simulations. Answer open ones here or in Claude's form; multiple-choice is graded from the answer key, open answers by Claude."
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
          {item.position}. {item.prompt}
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
                <span style={{ flex: 1 }}>{o.text}</span>
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
              <span className="chip">Answer saved · waiting for Claude's grade</span>
            ) : null
          ) : (
            <GradeChip grade={item.grade} status={item.assessment_status} />
          )}
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
              <li key={i}>{p}</li>
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
                {submitted && (
                  <Score
                    q={{ status: quiz.status, earned_points: quiz.earned_points ?? 0, max_points: quiz.max_points ?? 0, pending_items: quiz.pending_items ?? 0 }}
                  />
                )}
              </PageHead>
              {!submitted && (
                <>
                  <p className="small muted">
                    Answer here or in Claude's form; both save to the same simulation. Answer keys appear after you submit.
                  </p>
                  <QuizForm key={quiz.quiz_id} quiz={quiz} />
                </>
              )}
              {submitted && !!quiz.pending_items && <AwaitingClaude quiz={quiz} />}
              {submitted && quiz.note && <p className="small muted">{quiz.note}</p>}
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
