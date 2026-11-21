import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { request } from "../api";
import {
  CourseDialog,
  CourseDot,
  GroupDialog,
  KIND_LABEL,
  NewInterestDialog,
  cc,
  isFocused,
  useInvalidateOrganisation,
} from "../components/organise";
import { Async, Confirm, Empty, ErrorNote, PageHead, StudyMeter } from "../components/ui";
import { dateLabel, plural } from "../format";
import { useArchived, useCourseSummary, useGroups } from "../queries";
import { ArchivedCourses } from "./Archived";
import type { CourseSummary, Group } from "../types";

function CourseCard({ c }: { c: CourseSummary }) {
  const [editing, setEditing] = useState(false);
  return (
    <article className={`card stack course-card ${cc(c.color)} ${c.status === "archived" ? "archived" : ""}`}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <h3 className="row" style={{ gap: 8, overflowWrap: "anywhere" }}>
            <CourseDot color={c.color} />
            <Link to={`/courses/${c.id}`}>{c.title}</Link>
            {isFocused(c) && <span className="chip solid">Focus until {dateLabel(c.focus_until ?? "")}</span>}
          </h3>
          {c.description && c.kind !== "interest" && <p className="muted small">{c.description}</p>}
        </div>
        <button type="button" className="btn small ghost" onClick={() => setEditing(true)} aria-label={`Edit ${c.title}`}>
          Edit
        </button>
      </div>
      {c.status === "archived" ? (
        <div className="notice small muted">Archived{c.long_term_retention ? ": due reviews continue as maintenance." : "."}</div>
      ) : c.kind === "interest" ? (
        <div className="notice small">
          {c.description ? (
            <>
              <strong>Goal:</strong> {c.description}
            </>
          ) : (
            <span className="muted">No goal yet: Claude asks for it in your first session.</span>
          )}
        </div>
      ) : c.active_target ? (
        <div className="notice small">
          <strong>{c.active_target.name}</strong> on {dateLabel(c.active_target.due_date)} ·{" "}
          {c.active_target.days_left >= 0 ? `${plural(c.active_target.days_left, "day")} left` : "date passed"}
        </div>
      ) : (
        <div className="notice small muted">No exam or kolokvij set yet.</div>
      )}
      <StudyMeter progress={c.progress} />
      <div className="row small muted" style={{ gap: 16 }}>
        <span>{plural(c.progress.concepts, "concept")}</span>
        <span>{plural(c.sources, "material")}</span>
        <span>{plural(c.notes, "note")}</span>
        <span>{plural(c.simulations, "simulation")}</span>
        {c.due_reviews > 0 && <span className="chip warn">{c.due_reviews} due</span>}
      </div>
      {editing && <CourseDialog course={c} open onClose={() => setEditing(false)} />}
    </article>
  );
}

function GroupBlock({ group, groups, courses, showArchived, depth }: {
  group: Group;
  groups: Group[];
  courses: CourseSummary[];
  showArchived: boolean;
  depth: number;
}) {
  const refresh = useInvalidateOrganisation();
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const archive = useMutation({
    mutationFn: (archived: boolean) => request(`/groups/${group.id}/archive`, { method: "POST", json: { archived } }),
    onSuccess: () => {
      setConfirm(false);
      refresh();
    },
  });
  const children = groups.filter((g) => g.parent_id === group.id && (showArchived || g.status === "active"));
  const own = courses.filter((c) => c.group_id === group.id && (showArchived || c.status !== "archived"));
  const archived = group.status === "archived";
  const Heading = depth === 0 ? "h2" : "h3";
  return (
    <section className={`group ${archived ? "archived" : ""}`} aria-label={`${KIND_LABEL[group.kind]} ${group.name}`}>
      <div className="group-head">
        <Heading>
          <span className="kind">{KIND_LABEL[group.kind]}</span>
          {group.name}
          {archived && <span className="chip">Archived</span>}
        </Heading>
        <div className="row">
          {(group.starts_on || group.ends_on) && (
            <span className="small muted">
              {group.starts_on ? dateLabel(group.starts_on) : "…"} – {group.ends_on ? dateLabel(group.ends_on) : "…"}
            </span>
          )}
          {!archived && (
            <button type="button" className="btn small ghost" onClick={() => setAdding(true)}>
              Add inside
            </button>
          )}
          <button type="button" className="btn small ghost" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button type="button" className="btn small" onClick={() => (archived ? archive.mutate(false) : setConfirm(true))}>
            {archived ? "Restore" : "Archive"}
          </button>
        </div>
      </div>
      {archive.error && !confirm && <ErrorNote error={archive.error} />}
      {(children.length > 0 || own.length > 0) && (
        <div className="group-children">
          {own.length > 0 && (
            <div className="grid cols-2">
              {own.map((c) => (
                <CourseCard key={c.id} c={c} />
              ))}
            </div>
          )}
          {children.map((g) => (
            <GroupBlock key={g.id} group={g} groups={groups} courses={courses} showArchived={showArchived} depth={depth + 1} />
          ))}
        </div>
      )}
      {children.length === 0 && own.length === 0 && (
        <p className="small muted">
          Empty. File a course here with its Edit button{group.kind === "semester" ? "" : ", or add a semester inside"}.
        </p>
      )}
      {editing && <GroupDialog group={group} open onClose={() => setEditing(false)} />}
      {adding && <GroupDialog parentId={group.id} open onClose={() => setAdding(false)} />}
      <Confirm
        open={confirm}
        title={`Archive ${group.name}?`}
        confirmLabel="Archive"
        busy={archive.isPending}
        onConfirm={() => archive.mutate(true)}
        onClose={() => setConfirm(false)}
      >
        Everything inside is archived too: nested groups and their courses leave today's plan. Nothing is deleted;
        courses kept for long-term memory still get their due reviews as maintenance. You can restore it any time.
        {archive.error && <ErrorNote error={archive.error} />}
      </Confirm>
    </section>
  );
}

export function CoursesPage() {
  const q = useCourseSummary();
  const groups = useGroups();
  const showArchived = false; // archived groups and courses are listed in their own section below
  const archived = useArchived();
  const [creating, setCreating] = useState(false);
  const [addingInterest, setAddingInterest] = useState(false);
  return (
    <div className="page">
      <PageHead
        title="Courses"
        sub="Organised by university, faculty and semester, plus your own interests. Each shows its next exam or goal and progress."
      >
        <a href="#archived" className="btn ghost">
          Archived{archived.data ? ` (${archived.data.groups.length + archived.data.courses.length})` : ""}
        </a>
        <button type="button" className="btn" onClick={() => setCreating(true)}>
          New university, faculty or semester
        </button>
        <button type="button" className="btn" onClick={() => setAddingInterest(true)}>
          New interest
        </button>
      </PageHead>
      <Async q={q} lines={6}>
        {(courses) => {
          const all = groups.data ?? [];
          const known = new Set(all.map((g) => g.id));
          const roots = all.filter((g) => (!g.parent_id || !known.has(g.parent_id)) && (showArchived || g.status === "active"));
          const visible = (c: CourseSummary) => showArchived || c.status !== "archived";
          const loose = courses.filter((c) => c.kind !== "interest" && (!c.group_id || !known.has(c.group_id)) && visible(c));
          const interests = courses.filter((c) => c.kind === "interest" && visible(c));
          if (courses.length === 0 && all.length === 0) {
            return (
              <Empty title="No courses yet">
                In Claude, use <strong>Plan semester</strong> from the + menu (or see the <Link to="/guide">Guide</Link>). Claude creates
                your courses and files them under your university, faculty and semester.
              </Empty>
            );
          }
          return (
            <div className="stack" style={{ gap: 28 }}>
              {roots.map((g) => (
                <GroupBlock key={g.id} group={g} groups={all} courses={courses} showArchived={showArchived} depth={0} />
              ))}
              {loose.length > 0 && (
                <section className="group" aria-label="Courses not filed in a semester">
                  {roots.length > 0 && (
                    <div className="group-head">
                      <h2>
                        <span className="kind">Not filed</span>
                      </h2>
                    </div>
                  )}
                  <div className="grid cols-2">
                    {loose.map((c) => (
                      <CourseCard key={c.id} c={c} />
                    ))}
                  </div>
                </section>
              )}
              <section className="group" aria-label="Interests">
                <div className="group-head">
                  <h2>
                    <span className="kind">Interests</span>
                    Outside university
                  </h2>
                  <button type="button" className="btn small ghost" onClick={() => setAddingInterest(true)}>
                    Add interest
                  </button>
                </div>
                {interests.length > 0 ? (
                  <div className="grid cols-2">
                    {interests.map((c) => (
                      <CourseCard key={c.id} c={c} />
                    ))}
                  </div>
                ) : (
                  <p className="small muted">
                    Learn something in your free time, without an exam: data analysis, machine learning, a language.
                    Your courses come first: interests get the time left while every exam is on track, unless you
                    choose a share of each day in Settings or focus on one for a while.
                  </p>
                )}
              </section>
            </div>
          );
        }}
      </Async>
      <section id="archived" className="group" aria-label="Archived" style={{ marginTop: 28 }}>
        <div className="group-head">
          <h2>
            <span className="kind">Archived</span>
            Put away, nothing deleted
          </h2>
          <Link to="/library/archived" className="btn small ghost">
            Archived folders and files
          </Link>
        </div>
        <Async q={archived} lines={2}>
          {(view) => <ArchivedCourses view={view} compact />}
        </Async>
      </section>
      {creating && <GroupDialog open onClose={() => setCreating(false)} />}
      {addingInterest && <NewInterestDialog open onClose={() => setAddingInterest(false)} />}
    </div>
  );
}
