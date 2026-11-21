import { Link, useParams } from "react-router";
import { Async, BandChip, Card, Difficulty, Empty, GradeChip, PageHead, StudyChip } from "../components/ui";
import { ATTEMPT_KIND, CAPTURED_VIA, DIFFICULTY_SOURCE, STUDY_SOURCE, dateLabel, dateTime, gradedBy, plural, relativeDay } from "../format";
import { useConcept, useCourses } from "../queries";

export function ConceptPage() {
  const { conceptId = "" } = useParams();
  const q = useConcept(conceptId);
  const courses = useCourses();
  return (
    <div className="page">
      <Async q={q} lines={8}>
        {(c) => {
          const course = courses.data?.find((x) => x.id === c.course_id);
          return (
            <>
              <PageHead
                title={c.term}
                crumbs={[
                  { to: "/courses", label: "Courses" },
                  { to: `/courses/${c.course_id}`, label: course?.title ?? "Course" },
                ]}
              >
                <StudyChip status={c.study_status} />
                <BandChip band={c.band} />
              </PageHead>

              <div className="split">
                <div className="stack" style={{ gap: 20 }}>
                  <Card title="What it is">
                    {c.definition_draft ? (
                      <p className="reading pre">{c.definition_draft}</p>
                    ) : (
                      <p className="muted small">No short definition recorded. Claude explains it from your material.</p>
                    )}
                  </Card>

                  <Card title="Your answers" meta={plural(c.attempts.length, "answer")}>
                    {c.attempts.length === 0 ? (
                      <Empty title="No answers yet">
                        {c.study_status === "not_studied"
                          ? "Study this concept with Claude first; practice comes after."
                          : "Ask Claude for a question or a simulation on this concept."}
                      </Empty>
                    ) : (
                      <ul className="list">
                        {c.attempts.map((a) => (
                          <li key={a.attempt_id} className="stack" style={{ gap: 8 }}>
                            <div className="row" style={{ justifyContent: "space-between" }}>
                              <span className="small muted" title={dateTime(a.submitted_at)}>
                                {dateTime(a.submitted_at)} · {CAPTURED_VIA[a.captured_via] ?? a.captured_via}
                                {a.quiz && (
                                  <>
                                    {" · "}
                                    <Link to={`/simulations/${a.quiz.id}`}>{a.quiz.title}</Link>
                                    {a.quiz.mode === "diagnostic" && " (diagnostic)"}
                                  </>
                                )}
                              </span>
                              {a.status === "saved_awaiting_evaluation" ? (
                                <span className="chip">Answer saved · feedback pending</span>
                              ) : (
                                <GradeChip grade={a.grade} status={a.assessment_status} />
                              )}
                            </div>
                            {a.question && <div style={{ fontWeight: 600 }}>{a.question}</div>}
                            <div className="answer pre">{a.kind === "answer" ? a.answer : ATTEMPT_KIND[a.kind] ?? a.kind}</div>
                            {a.feedback && (
                              <div className="feedback">
                                <div className="tiny muted">Feedback from {gradedBy(a.graded_by, a.grader)}</div>
                                <div className="pre small">{a.feedback}</div>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </Card>
                </div>

                <div className="stack" style={{ gap: 20 }}>
                  <Card title="Review">
                    {c.review ? (
                      <dl className="kv">
                        <dt>Next</dt>
                        <dd>
                          {c.review.is_due ? <span className="chip warn">Due now</span> : `${dateLabel(c.review.due_at)} (${relativeDay(c.review.due_at)})`}
                        </dd>
                        <dt>Why</dt>
                        <dd className="small">{c.review.reason ?? "—"}</dd>
                        <dt>Evidence</dt>
                        <dd>
                          {plural(c.review.evidence_count, "graded answer")}, {plural(c.review.lapse_count, "lapse")}
                        </dd>
                        <dt>Last review</dt>
                        <dd>{dateLabel(c.review.last_review_at)}</dd>
                      </dl>
                    ) : (
                      <p className="small muted">Not scheduled yet. The first graded answer schedules a review.</p>
                    )}
                  </Card>
                  <Card title="Study">
                    <dl className="kv">
                      <dt>Status</dt>
                      <dd>
                        <StudyChip status={c.study_status} />
                      </dd>
                      {c.studied_at && (
                        <>
                          <dt>Since</dt>
                          <dd>
                            {dateLabel(c.studied_at)}
                            {c.study_source && ` · ${STUDY_SOURCE[c.study_source] ?? c.study_source}`}
                          </dd>
                        </>
                      )}
                      <dt>Difficulty</dt>
                      <dd className="row">
                        <Difficulty value={c.difficulty} source={c.difficulty_source} />
                        <span className="small muted">{DIFFICULTY_SOURCE[c.difficulty_source] ?? c.difficulty_source}</span>
                      </dd>
                    </dl>
                  </Card>
                  <Card title="In your material">
                    {c.sections.length === 0 ? (
                      <p className="small muted">Not linked to a section (inferred by Claude).</p>
                    ) : (
                      <ul className="list small">
                        {c.sections.map((s) => (
                          <li key={s.section_id}>
                            <div>{s.filename}</div>
                            <div className="muted">{s.label}</div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Card>
                  <p className="tiny muted">{c.note}</p>
                </div>
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}
