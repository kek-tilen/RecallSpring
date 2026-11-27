import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation } from "react-router";
import { request } from "../api";
import { CourseDot, GroupDialog, KIND_LABEL, NewInterestDialog, cc, isFocused, useInvalidateOrganisation } from "../components/organise";
import { NewCourseDialog, RecentlyDeletedCourses } from "../components/CourseForms";
import { StudyIn } from "../components/StudyIn";
import { Async, Chevron, Confirm, Empty, ErrorNote, PageHead, SectionMenu, StudyMeter } from "../components/ui";
import { dateLabel, plural } from "../format";
import { useArchived, useCourseSummary, useGroups } from "../queries";
import { ArchivedCourses } from "./Archived";
import type { CourseSummary, Group } from "../types";

// Courses as drawn (UI direction, 2026-11-27): one row per course in groups that open and close, interests apart;
// material and notes live inside each course, its settings behind Course settings on the course page.

/** Sections the learner closed on Courses (group IDs, "loose", "interests", "archived"), remembered on the device. */
export const COLLAPSED_STORE = "rs.courses.collapsed";

function readCollapsed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_STORE) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function useCollapse(id: string): [boolean, () => void] {
  const [closed, setClosed] = useState(() => readCollapsed().has(id));
  function toggle() {
    const all = readCollapsed();
    if (closed) all.delete(id);
    else all.add(id);
    try {
      localStorage.setItem(COLLAPSED_STORE, JSON.stringify([...all]));
    } catch {
      /* only a convenience */
    }
    setClosed(!closed);
  }
  return [closed, toggle];
}

/** The quiet heading of a section that opens and closes, with how much it holds on the right. */
function SectionToggle({ open, onToggle, children, count }: { open: boolean; onToggle: () => void; children: React.ReactNode; count: string }) {
  return (
    <>
      <button type="button" className="group-toggle" aria-expanded={open} onClick={onToggle}>
        <Chevron open={open} />
        {children}
      </button>
      <span className="group-count">{count}</span>
    </>
  );
}

/** Courses in a group and everything inside it. */
function coursesInside(group: Group, groups: Group[], courses: CourseSummary[], showArchived: boolean): number {
  const own = courses.filter((c) => c.group_id === group.id && (showArchived || c.status !== "archived")).length;
  return groups
    .filter((g) => g.parent_id === group.id && (showArchived || g.status === "active"))
    .reduce((n, g) => n + coursesInside(g, groups, courses, showArchived), own);
}

const LAST_STATUS: Record<string, string> = { passed: "passed", failed: "not passed yet", cancelled: "cancelled" };

function inDays(n: number): string {
  if (n < 0) return "date passed";
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  return `in ${n} days`;
}

/** What a course works towards, in one quiet line under its name. */
function courseLine(c: CourseSummary): string {
  if (c.status === "archived") return c.long_term_retention ? "Archived: due reviews continue as maintenance" : "Archived";
  if (c.kind === "interest") return c.description || "No goal yet: your assistant asks for it in your first session";
  if (c.active_target) return `${c.active_target.name} · ${inDays(c.active_target.days_left)}`;
  if (c.last_target) return `${c.last_target.name} · ${LAST_STATUS[c.last_target.status] ?? "result not recorded"} · no exam coming up`;
  return "No exam or midterm set yet";
}

function CourseRow({ c }: { c: CourseSummary }) {
  return (
    <li className={`course-row ${cc(c.color)} ${c.status === "archived" ? "archived" : ""}`}>
      <div className="course-row-name">
        <Link to={`/courses/${c.id}`} className="course-row-title">
          <CourseDot color={c.color} />
          {c.title}
        </Link>
        <span className="small muted course-row-line">
          {courseLine(c)}
          {isFocused(c) && ` · Focus until ${dateLabel(c.focus_until ?? "")}`}
        </span>
      </div>
      <div className="course-row-meter">
        <StudyMeter progress={c.progress} compact />
        <span className="tiny muted">{plural(c.progress.concepts, "concept")}</span>
      </div>
      <span className="small muted course-row-due">{c.due_reviews > 0 ? `${c.due_reviews} due` : ""}</span>
      <span className="course-row-act">{c.status !== "archived" && <StudyIn course={c} quiet />}</span>
    </li>
  );
}

function CourseRows({ courses, label }: { courses: CourseSummary[]; label: string }) {
  return (
    <ul className="course-rows" aria-label={label}>
      {courses.map((c) => (
        <CourseRow key={c.id} c={c} />
      ))}
    </ul>
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
  const [closed, toggle] = useCollapse(group.id);
  const filled = children.length > 0 || own.length > 0;
  const open = !filled || !closed;
  const name = (
    <>
      <span className="sr-only">{KIND_LABEL[group.kind]} </span>
      {group.name}
    </>
  );
  return (
    <section className={`group ${archived ? "archived" : ""}`} aria-label={`${KIND_LABEL[group.kind]} ${group.name}`}>
      <div className="group-head">
        <Heading>
          {filled ? (
            <SectionToggle open={open} onToggle={toggle} count={plural(coursesInside(group, groups, courses, showArchived), "course")}>
              {name}
            </SectionToggle>
          ) : (
            <span className="group-toggle">{name}</span>
          )}
          {archived && <span className="chip">Archived</span>}
        </Heading>
        <SectionMenu label={`Actions for ${group.name}`}>
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
          <button type="button" className="btn small ghost" onClick={() => (archived ? archive.mutate(false) : setConfirm(true))}>
            {archived ? "Restore" : "Archive"}
          </button>
        </SectionMenu>
      </div>
      {archive.error && !confirm && <ErrorNote error={archive.error} />}
      {filled && open && (
        <div className="group-children">
          {own.length > 0 && <CourseRows courses={own} label={`Courses in ${group.name}`} />}
          {children.map((g) => (
            <GroupBlock key={g.id} group={g} groups={groups} courses={courses} showArchived={showArchived} depth={depth + 1} />
          ))}
        </div>
      )}
      {children.length === 0 && own.length === 0 && (
        <p className="small muted">
          Empty. File a course here in its Course settings{group.kind === "semester" ? "" : ", or add a semester inside"}.
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
  const location = useLocation();
  // The welcome page's Continue opens Courses with a new course started (2026-11-27).
  const [addingCourse, setAddingCourse] = useState(() => Boolean((location.state as { newCourse?: boolean } | null)?.newCourse));
  const [looseClosed, toggleLoose] = useCollapse("loose");
  const [interestsClosed, toggleInterests] = useCollapse("interests");
  const [archiveClosed, toggleArchive] = useCollapse("archived");
  const archivedCount = archived.data ? archived.data.groups.length + archived.data.courses.length : 0;
  return (
    <div className="page courses-page">
      <PageHead title="Courses">
        <button type="button" className="btn" onClick={() => setAddingCourse(true)}>
          + New course
        </button>
        <SectionMenu label="More">
          <button type="button" className="btn small ghost" onClick={() => setCreating(true)}>
            New university, faculty or semester
          </button>
          <button type="button" className="btn small ghost" onClick={() => setAddingInterest(true)}>
            New interest
          </button>
          <Link to="/library/import" className="btn small ghost">
            Move in
          </Link>
          <Link to="/library" className="btn small ghost">
            All material
          </Link>
          <Link to="/notes" className="btn small ghost">
            All notes
          </Link>
        </SectionMenu>
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
                Add one with <strong>New course</strong>, or plan your semester in a planning chat with your assistant (see the <Link to="/guide">Guide</Link>):
                it creates your courses and files them under your university, faculty and semester.
              </Empty>
            );
          }
          return (
            <div className="stack courses-groups">
              {roots.map((g) => (
                <GroupBlock key={g.id} group={g} groups={all} courses={courses} showArchived={showArchived} depth={0} />
              ))}
              {loose.length > 0 && (
                <section className="group" aria-label="Courses not filed in a semester">
                  {roots.length > 0 && (
                    <div className="group-head">
                      <h2>
                        <SectionToggle open={!looseClosed} onToggle={toggleLoose} count={plural(loose.length, "course")}>
                          Not filed
                        </SectionToggle>
                      </h2>
                    </div>
                  )}
                  {(roots.length === 0 || !looseClosed) && <CourseRows courses={loose} label="Courses not filed" />}
                </section>
              )}
              <section className="group" aria-label="Interests">
                <div className="group-head">
                  <h2>
                    {interests.length > 0 ? (
                      <SectionToggle open={!interestsClosed} onToggle={toggleInterests} count={plural(interests.length, "interest")}>
                        Interests
                      </SectionToggle>
                    ) : (
                      <span className="group-toggle">Interests</span>
                    )}
                  </h2>
                  <SectionMenu label="Actions for Interests">
                    <button type="button" className="btn small ghost" onClick={() => setAddingInterest(true)}>
                      Add interest
                    </button>
                  </SectionMenu>
                </div>
                {interests.length > 0 ? (
                  !interestsClosed && <CourseRows courses={interests} label="Interests" />
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
      <section id="archived" className="group courses-archived" aria-label="Archived">
        <div className="group-head">
          <h2>
            {archivedCount > 0 ? (
              <SectionToggle open={!archiveClosed} onToggle={toggleArchive} count={plural(archivedCount, "item")}>
                Archived
              </SectionToggle>
            ) : (
              <span className="group-toggle">Archived</span>
            )}
          </h2>
          <SectionMenu label="Actions for Archived">
            <Link to="/library/archived" className="btn small ghost">
              Archived folders and files
            </Link>
          </SectionMenu>
        </div>
        {(archivedCount === 0 || !archiveClosed) && (
          <Async q={archived} lines={2}>
            {(view) => <ArchivedCourses view={view} compact />}
          </Async>
        )}
      </section>
      <RecentlyDeletedCourses />
      {creating && <GroupDialog open onClose={() => setCreating(false)} />}
      {addingInterest && <NewInterestDialog open onClose={() => setAddingInterest(false)} />}
      {addingCourse && <NewCourseDialog open onClose={() => setAddingCourse(false)} />}
    </div>
  );
}
