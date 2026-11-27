import { plural } from "../format";
import { useWaitingAnswers } from "../queries";
import { StudyIn, gradeMessage } from "./StudyIn";

/**
 * "N answers waiting for a grade" with Grade my answers in… (UI direction, 2026-11-27): answers saved in the app wait
 * for an assistant's grade; until then their next review date stays open. Nothing shows when none wait.
 */
export function WaitingForGrade({ courseId }: { courseId?: string }) {
  const w = useWaitingAnswers(courseId).data;
  if (!w?.total) return null;
  return (
    <section className="waiting" aria-labelledby={`waiting-${courseId ?? "all"}`}>
      <h2 id={`waiting-${courseId ?? "all"}`} className="waiting-title">
        {plural(w.total, "answer")} waiting for a grade
      </h2>
      <p className="small muted">Their next review dates are set once they are graded.</p>
      <StudyIn ask={{ label: "Grade my answers", message: gradeMessage(w) }} />
    </section>
  );
}
