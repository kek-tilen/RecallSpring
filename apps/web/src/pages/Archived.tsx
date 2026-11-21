import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router";
import { request } from "../api";
import { CourseDot, KIND_LABEL } from "../components/organise";
import { Async, Card, Empty, ErrorNote, PageHead } from "../components/ui";
import { CATEGORY_LABEL, dateLabel, plural } from "../format";
import { LIBRARY_KEYS, ORGANISATION_KEYS, useArchived } from "../queries";
import type { ArchivedView } from "../types";
import { useQueryClient } from "@tanstack/react-query";

/** Restore anything archived; afterwards everything that lists courses, groups or material is refreshed. */
function useRestore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, method, json }: { path: string; method?: "POST" | "PATCH"; json: unknown }) => request(path, { method, json }),
    onSuccess: () => [...ORGANISATION_KEYS, ...LIBRARY_KEYS].forEach((key) => void qc.invalidateQueries({ queryKey: [...key] })),
  });
}

function RestoreButton({ label, onClick, busy }: { label: string; onClick: () => void; busy: boolean }) {
  return (
    <button type="button" className="btn small" onClick={onClick} disabled={busy} aria-label={label}>
      Restore
    </button>
  );
}

/** Courses archived on their own (not as part of an archived semester or group). */
function looseCourses(view: ArchivedView) {
  const archivedGroups = new Set(view.groups.map((g) => g.id));
  return view.courses.filter((c) => !c.group_id || !archivedGroups.has(c.group_id));
}

/** Archived semesters (and other groups) and courses. Courses in an archived semester come back with it. */
export function ArchivedCourses({ view, compact }: { view: ArchivedView; compact?: boolean }) {
  const restore = useRestore();
  const loose = looseCourses(view);
  if (view.groups.length === 0 && view.courses.length === 0) {
    return <p className="small muted">No archived semesters or courses.</p>;
  }
  return (
    <div className="stack">
      {restore.error && <ErrorNote error={restore.error} />}
      {view.groups.length > 0 && (
        <ul className="list" aria-label="Archived semesters and groups">
          {view.groups.map((g) => {
            const inside = view.courses.filter((c) => c.group_id === g.id);
            return (
              <li key={g.id} className="row" style={{ justifyContent: "space-between" }}>
                <span className="stack" style={{ gap: 2 }}>
                  <span>
                    <span className="kind">{KIND_LABEL[g.kind]}</span> <strong>{g.path || g.name}</strong>
                  </span>
                  <span className="tiny muted">
                    {g.archived_at ? `Archived ${dateLabel(g.archived_at)}` : "Archived"}
                    {inside.length > 0 && ` · ${inside.map((c) => c.title).join(", ")}`}
                  </span>
                </span>
                <RestoreButton
                  label={`Restore ${g.name} with everything in it`}
                  busy={restore.isPending}
                  onClick={() => restore.mutate({ path: `/groups/${g.id}/archive`, json: { archived: false } })}
                />
              </li>
            );
          })}
        </ul>
      )}
      {loose.length > 0 && (
        <ul className="list" aria-label="Archived courses">
          {loose.map((c) => (
            <li key={c.id} className="row" style={{ justifyContent: "space-between" }}>
              <span className="stack" style={{ gap: 2 }}>
                <span className="row" style={{ gap: 6 }}>
                  <CourseDot color={c.color} />
                  <Link to={`/courses/${c.id}`} style={{ fontWeight: 600 }}>
                    {c.title}
                  </Link>
                  {c.kind === "interest" && <span className="chip">Interest</span>}
                </span>
                <span className="tiny muted">
                  {c.group_path || (c.kind === "interest" ? "Interest" : "Not filed")}
                  {c.long_term_retention ? " · due reviews continue as maintenance" : ""}
                  {!compact && (
                    <>
                      {" · "}
                      <Link to={`/library/course/${c.id}`}>Material</Link>
                    </>
                  )}
                </span>
              </span>
              <RestoreButton
                label={`Restore ${c.title}`}
                busy={restore.isPending}
                onClick={() => restore.mutate({ path: `/courses/${c.id}`, method: "PATCH", json: { archived: false } })}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ArchivedMaterial({ view }: { view: ArchivedView }) {
  const restore = useRestore();
  if (view.folders.length === 0 && view.sources.length === 0) return <p className="small muted">No archived folders or files.</p>;
  return (
    <div className="stack">
      {restore.error && <ErrorNote error={restore.error} />}
      {view.folders.length > 0 && (
        <ul className="list" aria-label="Archived folders">
          {view.folders.map((f) => (
            <li key={f.id} className="row" style={{ justifyContent: "space-between" }}>
              <span className="stack" style={{ gap: 2 }}>
                <span className="row" style={{ gap: 6 }}>
                  <span className="folder-icon small" aria-hidden="true" />
                  <Link to={`/library/course/${f.course_id}?folder=${f.id}`} style={{ fontWeight: 600 }}>
                    {f.path}
                  </Link>
                </span>
                <span className="tiny muted row" style={{ gap: 6 }}>
                  <CourseDot color={f.course.color} />
                  {f.course.title} · {plural(f.files, "file")}
                  {f.archived_at && ` · archived ${dateLabel(f.archived_at)}`}
                </span>
              </span>
              <RestoreButton
                label={`Restore the folder ${f.name}`}
                busy={restore.isPending}
                onClick={() => restore.mutate({ path: `/folders/${f.id}/archive`, json: { archived: false } })}
              />
            </li>
          ))}
        </ul>
      )}
      {view.sources.length > 0 && (
        <ul className="list" aria-label="Archived files">
          {view.sources.map((s) => (
            <li key={s.id} className="row" style={{ justifyContent: "space-between" }}>
              <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                <Link to={`/library/${s.id}`} style={{ fontWeight: 600, overflowWrap: "anywhere" }}>
                  {s.filename}
                </Link>
                <span className="tiny muted row" style={{ gap: 6 }}>
                  <CourseDot color={s.course.color} />
                  {s.course.title}
                  {s.folder ? ` › ${s.folder}` : ""} · {CATEGORY_LABEL[s.category] ?? s.category}
                  {s.archived_at && ` · archived ${dateLabel(s.archived_at)}`}
                </span>
              </span>
              <RestoreButton
                label={`Restore ${s.filename}`}
                busy={restore.isPending}
                onClick={() => restore.mutate({ path: "/sources/archive", json: { source_ids: [s.id], archived: false } })}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ArchivedPage() {
  const q = useArchived();
  return (
    <div className="page">
      <PageHead
        title="Archived"
        sub="Semesters, courses, folders and files you put away. Nothing here was deleted; restore anything with one click."
        crumbs={[{ to: "/library", label: "Library" }]}
      />
      <Async q={q} lines={5}>
        {(view) =>
          view.groups.length + view.courses.length + view.folders.length + view.sources.length === 0 ? (
            <Empty title="Nothing archived">
              Archive a finished semester on the Courses page, or folders and files in the Library, to keep them out of the way.
            </Empty>
          ) : (
            <div className="grid cols-2" style={{ alignItems: "start" }}>
              <Card title="Semesters and courses" meta={plural(view.groups.length + looseCourses(view).length, "item")}>
                <ArchivedCourses view={view} />
              </Card>
              <Card title="Folders and files" meta={plural(view.folders.length + view.sources.length, "item")}>
                <ArchivedMaterial view={view} />
                <p className="tiny muted" style={{ marginTop: 10 }}>
                  Archived material is left out of search, but your assistant can still read the parts it already cited.
                </p>
              </Card>
            </div>
          )
        }
      </Async>
    </div>
  );
}
