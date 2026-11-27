import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { get } from "../api";
import { StudyIn } from "../components/StudyIn";
import { Async, PageHead } from "../components/ui";
import { WaitingForGrade } from "../components/WaitingForGrade";
import { plural } from "../format";
import { courseTitles, useCourses } from "../queries";
import type { ReviewQuestions } from "../types";
import { ReviewAnswer, type AnswerKind } from "./Answer";

interface Done {
  term: string;
  kind: AnswerKind;
  unsure: boolean;
}

/**
 * Review now (UI direction, 2026-11-27): the concepts of a course that are due, one saved question each, answered from
 * memory here; then one summary and Grade my answers in…. The list is fixed when the review starts.
 */
export function ReviewRunPage() {
  const { courseId = "" } = useParams();
  const title = courseTitles(useCourses().data)[courseId] ?? "this course";
  const q = useQuery({
    queryKey: ["review-run", courseId],
    queryFn: () => get<ReviewQuestions>("/reviews/questions", { course_id: courseId }),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const [done, setDone] = useState<Done[]>([]);
  return (
    <div className="page review-run">
      <Async q={q} lines={4}>
        {(r) => {
          const item = r.items[done.length];
          if (r.items.length > 0 && item) {
            return (
              <>
                <div className="review-run-top">
                  <Link to="/review" className="muted small">
                    <span aria-hidden="true">✕</span> End review
                  </Link>
                  <span className="muted small">
                    {done.length + 1} of {r.items.length}
                  </span>
                </div>
                <ol className="review-progress" aria-hidden="true">
                  {r.items.map((i, n) => (
                    <li key={i.concept_id} className={n < done.length ? "done" : n === done.length ? "now" : undefined} />
                  ))}
                </ol>
                <p className="muted small review-run-what">
                  {title} · {item.term} · from memory
                </p>
                <ReviewAnswer
                  key={item.question_id}
                  questionId={item.question_id}
                  onSaved={(kind, unsure) => setDone((d) => [...d, { term: item.term, kind, unsure }])}
                />
              </>
            );
          }
          return <Finished done={done} r={r} courseId={courseId} title={title} />;
        }}
      </Async>
    </div>
  );
}

function Finished({ done, r, courseId, title }: { done: Done[]; r: ReviewQuestions; courseId: string; title: string }) {
  const answered = done.filter((d) => d.kind === "answer").length;
  return (
    <>
      <PageHead title={done.length ? "Review done" : `Review ${title}`} />
      {done.length > 0 ? (
        <>
          <p className="review-run-sum">
            {answered > 0
              ? `${plural(answered, "answer")} saved. Each is waiting for a grade; the next review dates follow the grades.`
              : "Nothing to grade: the concepts you did not know come back soon."}
          </p>
          <ul className="review-done">
            {done.map((d) => (
              <li key={d.term}>
                <span>{d.term}</span>
                <span className="muted small">{d.kind === "dont_know" ? "I don't know" : d.unsure ? "Saved · unsure" : "Saved"}</span>
              </li>
            ))}
          </ul>
          <WaitingForGrade courseId={courseId} />
        </>
      ) : (
        r.without_question.length === 0 && <p className="muted">Nothing is due in {title} now.</p>
      )}
      {r.without_question.length > 0 && (
        <div className="review-run-without">
          <p className="small">
            {r.without_question.map((c) => c.term).join(", ")} {r.without_question.length === 1 ? "has" : "have"} no saved question to answer here
            yet. Your assistant asks new ones:
          </p>
          <StudyIn course={{ id: courseId, title }} review={{}} />
        </div>
      )}
      <p>
        <Link to="/review" className="btn">
          Back to Review
        </Link>
      </p>
    </>
  );
}
