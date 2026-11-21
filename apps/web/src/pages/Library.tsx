import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { API, get, request } from "../api";
import { CourseDot, groupPath } from "../components/organise";
import { Async, Card, Empty, ErrorNote, Highlighted, PageHead } from "../components/ui";
import { Upload } from "../components/Upload";
import { CATEGORY_LABEL, COUNT_LABEL, SOURCE_KIND, bytes, dateLabel, dateTime, parseNoteLabel, plural } from "../format";
import { LIBRARY_KEYS, useCourses, useFolders, useGroups, useSources } from "../queries";
import type { Course, Folder, Group, MaterialCategory, SearchHit, Section, Source } from "../types";

const STATE: Record<Source["parse_state"], { tone: string; label: string }> = {
  pending: { tone: "chip", label: "Queued" },
  processing: { tone: "chip", label: "Processing" },
  ready: { tone: "chip good", label: "Ready" },
  needs_attention: { tone: "chip warn", label: "Needs attention" },
  failed: { tone: "chip bad", label: "Failed" },
};
const CATEGORIES: MaterialCategory[] = ["material", "notes", "exercises", "past_paper", "other"];
const DRAG_TYPE = "application/x-recallspring-sources";

export function StateChip({ state }: { state: Source["parse_state"] }) {
  return <span className={STATE[state].tone}>{STATE[state].label}</span>;
}

export function useRefreshLibrary() {
  const qc = useQueryClient();
  return () => LIBRARY_KEYS.forEach((key) => void qc.invalidateQueries({ queryKey: [...key] }));
}

/** Move or archive material; every change can be undone from the same place or from Archived. */
export function useSourceActions() {
  const refresh = useRefreshLibrary();
  const move = useMutation({
    mutationFn: ({ ids, folderId }: { ids: string[]; folderId: string | null }) =>
      request("/sources/move", { json: { source_ids: ids, folder_id: folderId } }),
    onSuccess: refresh,
  });
  const archive = useMutation({
    mutationFn: ({ ids, archived }: { ids: string[]; archived: boolean }) =>
      request("/sources/archive", { json: { source_ids: ids, archived } }),
    onSuccess: refresh,
  });
  return { move, archive };
}

function draggedIds(e: DragEvent): string[] {
  try {
    const ids: unknown = JSON.parse(e.dataTransfer.getData(DRAG_TYPE) || "[]");
    return Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** A place material can be dropped on (folder tile or breadcrumb); the same moves are available without a mouse. */
function useDropTarget(onDrop: (ids: string[]) => void) {
  const [over, setOver] = useState(false);
  return {
    over,
    props: {
      onDragOver: (e: DragEvent) => {
        if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
        e.preventDefault();
        setOver(true);
      },
      onDragLeave: () => setOver(false),
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        setOver(false);
        const ids = draggedIds(e);
        if (ids.length) onDrop(ids);
      },
    },
  };
}

export function SourceTable({
  sources,
  titles,
  selected,
  onToggle,
  showFolder,
}: {
  sources: Source[];
  titles?: Record<string, string>;
  selected?: Set<string>;
  onToggle?: (id: string) => void;
  showFolder?: boolean;
}) {
  if (sources.length === 0) return null;
  const dragStart = (e: DragEvent, id: string) => {
    const ids = selected?.has(id) ? [...selected] : [id];
    e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(ids));
    e.dataTransfer.effectAllowed = "move";
  };
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {onToggle && (
              <th style={{ width: 1 }}>
                <span className="sr-only">Select</span>
              </th>
            )}
            <th>Material</th>
            <th>Kind</th>
            {titles && <th>Course</th>}
            {showFolder && <th>Folder</th>}
            <th>Text</th>
            <th>Pages</th>
            <th>Size</th>
            <th>Added</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.id} draggable={!!onToggle} onDragStart={(e) => dragStart(e, s.id)} className={selected?.has(s.id) ? "selected" : undefined}>
              {onToggle && (
                <td>
                  <input type="checkbox" checked={selected?.has(s.id) ?? false} onChange={() => onToggle(s.id)} aria-label={`Select ${s.filename}`} />
                </td>
              )}
              <td style={{ minWidth: 200, overflowWrap: "anywhere" }}>
                <Link to={`/library/${s.id}`} style={{ fontWeight: 600 }}>
                  {s.filename}
                </Link>
                {s.duplicate_of_id && <div className="tiny muted">Same file as another upload</div>}
              </td>
              <td className="small nowrap">{CATEGORY_LABEL[s.category] ?? s.category}</td>
              {titles && <td className="small">{titles[s.course_id] ?? ""}</td>}
              {showFolder && <td className="small">{s.folder ?? "Top level"}</td>}
              <td>{s.kind === "image" ? <span className="small muted">Photo</span> : <StateChip state={s.parse_state} />}</td>
              <td>{s.page_count ?? "—"}</td>
              <td className="small nowrap">{bytes(s.byte_size)}</td>
              <td className="small nowrap">{dateLabel(s.uploaded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Gallery({
  images,
  titles,
  selected,
  onToggle,
}: {
  images: Source[];
  titles?: Record<string, string>;
  selected?: Set<string>;
  onToggle?: (id: string) => void;
}) {
  return (
    <div className="gallery">
      {images.map((s) => (
        <div
          key={s.id}
          className={selected?.has(s.id) ? "thumb selected" : "thumb"}
          draggable={!!onToggle}
          onDragStart={(e) => {
            const ids = selected?.has(s.id) ? [...selected] : [s.id];
            e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(ids));
          }}
        >
          <Link to={`/library/${s.id}`}>
            <img src={`${API}/sources/${s.id}/file`} alt={s.filename} loading="lazy" />
          </Link>
          <span className="row" style={{ gap: 6, flexWrap: "nowrap", alignItems: "flex-start" }}>
            {onToggle && (
              <input type="checkbox" checked={selected?.has(s.id) ?? false} onChange={() => onToggle(s.id)} aria-label={`Select ${s.filename}`} />
            )}
            <span>{s.filename}</span>
          </span>
          {titles && <span className="muted tiny">{titles[s.course_id] ?? ""}</span>}
        </div>
      ))}
    </div>
  );
}

function Search() {
  const [draft, setDraft] = useState("");
  const [term, setTerm] = useState("");
  const q = useQuery({
    queryKey: ["search", term],
    queryFn: () => get<{ hits: SearchHit[]; note: string }>("/sources/search", { q: term, limit: 20 }),
    enabled: term.length > 1,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    setTerm(draft.trim());
  }
  return (
    <Card title="Search your material">
      <form className="row" onSubmit={submit} role="search">
        <label style={{ flex: 1, minWidth: 220 }}>
          <span className="sr-only">Search text</span>
          <input type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="A word or phrase in any language" />
        </label>
        <button type="submit" className="btn">
          Search
        </button>
      </form>
      {term.length > 1 && (
        <div style={{ marginTop: 14 }}>
          <Async q={q}>
            {(r) =>
              r.hits.length === 0 ? (
                <p className="small muted">No match for “{term}”. Archived material is not searched.</p>
              ) : (
                <ul className="list">
                  {r.hits.map((h) => (
                    <li key={h.section_id}>
                      <div className="small">
                        <Link to={`/library/${h.source_id}#${h.section_id}`}>{h.filename}</Link> · {h.citation_label}
                      </div>
                      <div className="small muted">
                        <Highlighted text={h.snippet} />
                      </div>
                    </li>
                  ))}
                </ul>
              )
            }
          </Async>
        </div>
      )}
    </Card>
  );
}

/** Groups and courses that are not archived (a course in an archived semester counts as archived). */
function activeCourses(courses: Course[], groups: Group[]): Course[] {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const groupArchived = (id: string | null): boolean => {
    const seen = new Set<string>();
    let g = id ? byId.get(id) : undefined;
    while (g && !seen.has(g.id)) {
      if (g.status === "archived") return true;
      seen.add(g.id);
      g = g.parent_id ? byId.get(g.parent_id) : undefined;
    }
    return false;
  };
  return courses.filter((c) => c.status !== "archived" && !groupArchived(c.group_id));
}

function CourseTile({ course, sources, folders }: { course: Course; sources: Source[]; folders: Folder[] }) {
  const own = sources.filter((s) => s.course_id === course.id);
  const photos = own.filter((s) => s.kind === "image").length;
  const ownFolders = folders.filter((f) => f.course_id === course.id && !f.hidden).length;
  const parts = [plural(own.length - photos, "file"), photos ? plural(photos, "photo") : null, ownFolders ? plural(ownFolders, "folder") : null];
  return (
    <Link to={`/library/course/${course.id}`} className="folder-tile">
      <span className="folder-icon" aria-hidden="true" />
      <span className="stack" style={{ gap: 2, minWidth: 0 }}>
        <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <CourseDot color={course.color} />
          <strong style={{ overflowWrap: "anywhere" }}>{course.title}</strong>
        </span>
        <span className="tiny muted">{parts.filter(Boolean).join(" · ")}</span>
      </span>
    </Link>
  );
}

export function LibraryPage() {
  const sources = useSources();
  const courses = useCourses();
  const groups = useGroups();
  const folders = useFolders();
  const titles = Object.fromEntries((courses.data ?? []).map((c) => [c.id, c.title]));
  return (
    <div className="page">
      <PageHead
        title="Library"
        sub="Your material by semester and course, in your own folders if you like. Claude cites the extracted text and can look at your photos."
      >
        <Link to="/library/import" className="btn">
          Move in
        </Link>
        <Link to="/library/archived" className="btn">
          Archived
        </Link>
      </PageHead>
      <Async q={courses} lines={4}>
        {(all) => {
          const list = activeCourses(all, groups.data ?? []);
          if (list.length === 0) {
            return <Empty title="No courses yet">Create a course in Claude, then add material here or ask Claude to import files.</Empty>;
          }
          const sections = new Map<string, Course[]>();
          for (const c of list) {
            const label = c.kind === "interest" ? "Interests" : groupPath(groups.data, c.group_id) || "Not filed";
            sections.set(label, [...(sections.get(label) ?? []), c]);
          }
          const order = [...sections.keys()].sort((a, b) => {
            const rank = (s: string) => (s === "Interests" ? 2 : s === "Not filed" ? 1 : 0);
            return rank(a) - rank(b) || a.localeCompare(b);
          });
          const recent = [...(sources.data ?? [])].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at)).slice(0, 6);
          return (
            <div className="stack" style={{ gap: 24 }}>
              {order.map((label) => (
                <section key={label} aria-label={label} className="stack" style={{ gap: 10 }}>
                  <h2 className="kind" style={{ margin: 0 }}>
                    {label}
                  </h2>
                  <div className="folder-grid">
                    {(sections.get(label) ?? []).map((c) => (
                      <CourseTile key={c.id} course={c} sources={sources.data ?? []} folders={folders.data ?? []} />
                    ))}
                  </div>
                </section>
              ))}
              {recent.length > 0 && (
                <Card title="Recently added">
                  <SourceTable sources={recent} titles={titles} showFolder />
                </Card>
              )}
            </div>
          );
        }}
      </Async>
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Search />
        <Card title="Add material">
          <Upload />
        </Card>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ one course, its folders and files

function FolderDialog({
  folder,
  courseId,
  parentId,
  folders,
  onClose,
}: {
  folder?: Folder;
  courseId: string;
  parentId: string | null;
  folders: Folder[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const refresh = useRefreshLibrary();
  const [name, setName] = useState(folder?.name ?? "");
  const [parent, setParent] = useState(folder ? folder.parent_id ?? "" : parentId ?? "");
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const blocked = new Set<string>();
  if (folder) {
    blocked.add(folder.id);
    let grew = true;
    while (grew) {
      grew = false;
      for (const f of folders) {
        if (f.parent_id && blocked.has(f.parent_id) && !blocked.has(f.id)) {
          blocked.add(f.id);
          grew = true;
        }
      }
    }
  }
  const options = folders.filter((f) => !blocked.has(f.id) && !f.hidden).sort((a, b) => a.path.localeCompare(b.path));
  const save = useMutation({
    mutationFn: () =>
      folder
        ? request(`/folders/${folder.id}`, { method: "PATCH", json: { name, parent_id: parent || null } })
        : request("/folders", { json: { course_id: courseId, parent_id: parent || null, name } }),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="folder-dialog-title">
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <h2 id="folder-dialog-title">{folder ? "Rename or move folder" : "New folder"}</h2>
        <label className="field">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required autoFocus />
        </label>
        <label className="field">
          Inside
          <select value={parent} onChange={(e) => setParent(e.target.value)}>
            <option value="">Top level of the course</option>
            {options.map((f) => (
              <option key={f.id} value={f.id}>
                {f.path}
              </option>
            ))}
          </select>
        </label>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={save.isPending || !name.trim()}>
            {folder ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function FolderTile({ folder, href, onDrop }: { folder: Folder; href: string; onDrop: (ids: string[]) => void }) {
  const drop = useDropTarget(onDrop);
  return (
    <Link to={href} className={drop.over ? "folder-tile over" : "folder-tile"} {...drop.props}>
      <span className="folder-icon" aria-hidden="true" />
      <span className="stack" style={{ gap: 2, minWidth: 0 }}>
        <strong style={{ overflowWrap: "anywhere" }}>{folder.name}</strong>
        <span className="tiny muted">
          {plural(folder.files, "file")}
          {folder.archived && " · archived"}
        </span>
      </span>
    </Link>
  );
}

function Crumb({ to, label, onDrop, current }: { to: string; label: string; onDrop: (ids: string[]) => void; current: boolean }) {
  const drop = useDropTarget(onDrop);
  return current ? (
    <span aria-current="page" style={{ fontWeight: 600 }}>
      {label}
    </span>
  ) : (
    <Link to={to} className={drop.over ? "crumb-drop over" : "crumb-drop"} {...drop.props}>
      {label}
    </Link>
  );
}

/** One course's material: its folders (optional, nestable) and the files and photos at the current level. */
export function FolderBrowser({ courseId, folderId, href }: { courseId: string; folderId: string | null; href: (folderId: string | null) => string }) {
  const folders = useFolders(courseId);
  const sources = useSources(courseId, true);
  const { move, archive } = useSourceActions();
  const refresh = useRefreshLibrary();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState<MaterialCategory | "all">("all");
  const [dialog, setDialog] = useState<"new" | "edit" | null>(null);
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState<{ text: string; undo?: () => void } | null>(null);
  const folderAction = useMutation({
    mutationFn: ({ path, method, json }: { path: string; method?: "POST" | "DELETE"; json?: unknown }) => request(path, { method, json }),
    onSuccess: refresh,
  });
  useEffect(() => {
    setSelected(new Set());
    setCategory("all");
    setStatus(null);
  }, [folderId]);

  if (folders.isPending || sources.isPending) return <Async q={folders.isPending ? folders : sources} lines={4}>{() => null}</Async>;
  if (folders.error || sources.error) return <ErrorNote error={folders.error ?? sources.error} />;
  const all = folders.data ?? [];
  const current = folderId ? all.find((f) => f.id === folderId) : undefined;
  if (folderId && !current) {
    return <Empty title="Folder not found">It may have been removed. <Link to={href(null)}>Back to the course's material</Link>.</Empty>;
  }
  const insideArchived = current?.hidden ?? false;
  const chain: Folder[] = [];
  for (let f = current; f; f = f.parent_id ? all.find((x) => x.id === f!.parent_id) : undefined) chain.unshift(f);
  const children = all
    .filter((f) => f.parent_id === (folderId ?? null) && (insideArchived || !f.archived))
    .sort((a, b) => a.name.localeCompare(b.name));
  const here = (sources.data ?? []).filter((s) => (s.folder_id ?? null) === (folderId ?? null) && !s.archived && (insideArchived || !s.hidden));
  const counts = Object.fromEntries(CATEGORIES.map((c) => [c, here.filter((s) => s.category === c).length]));
  const shown = category === "all" ? here : here.filter((s) => s.category === category);
  const files = shown.filter((s) => s.kind !== "image");
  const images = shown.filter((s) => s.kind === "image");
  const choices = all.filter((f) => !f.hidden && f.id !== folderId).sort((a, b) => a.path.localeCompare(b.path));
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const moveTo = (ids: string[], dest: string | null) => {
    const from = folderId;
    move.mutate(
      { ids, folderId: dest },
      {
        onSuccess: () => {
          setSelected(new Set());
          const name = dest ? all.find((f) => f.id === dest)?.path : "the top level";
          setStatus({ text: `Moved ${plural(ids.length, "item")} to ${name}.`, undo: () => move.mutate({ ids, folderId: from }) });
        },
      },
    );
  };
  const archiveSelected = () => {
    const ids = [...selected];
    archive.mutate(
      { ids, archived: true },
      {
        onSuccess: () => {
          setSelected(new Set());
          setStatus({ text: `Archived ${plural(ids.length, "item")}. Find them under Archived.`, undo: () => archive.mutate({ ids, archived: false }) });
        },
      },
    );
  };
  const empty = current ? current.files === 0 && !all.some((f) => f.parent_id === current.id) : false;

  return (
    <div className="stack" style={{ gap: 16 }}>
      <nav className="row small" aria-label="Folder path" style={{ gap: 6 }}>
        <Crumb to={href(null)} label="All material" current={!folderId} onDrop={(ids) => moveTo(ids, null)} />
        {chain.map((f) => (
          <span key={f.id} className="row" style={{ gap: 6 }}>
            <span aria-hidden="true">›</span>
            <Crumb to={href(f.id)} label={f.name} current={f.id === folderId} onDrop={(ids) => moveTo(ids, f.id)} />
          </span>
        ))}
      </nav>
      {insideArchived && (
        <div className="notice warn small">
          This folder is archived{current?.archived ? "" : " (a folder above it is)"}: hidden from the library and from search. Nothing in it
          was deleted.{" "}
          {current?.archived && (
            <button
              type="button"
              className="btn small"
              onClick={() => folderAction.mutate({ path: `/folders/${current.id}/archive`, json: { archived: false } })}
            >
              Restore folder
            </button>
          )}
        </div>
      )}
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" role="group" aria-label="Filter by kind">
          <button type="button" className="chip chip-filter" aria-pressed={category === "all"} onClick={() => setCategory("all")}>
            All {here.length}
          </button>
          {CATEGORIES.filter((c) => counts[c]).map((c) => (
            <button key={c} type="button" className="chip chip-filter" aria-pressed={category === c} onClick={() => setCategory(c)}>
              {CATEGORY_LABEL[c]} {counts[c]}
            </button>
          ))}
        </div>
        <div className="row">
          {!insideArchived && (
            <button type="button" className="btn small" onClick={() => setDialog("new")}>
              New folder
            </button>
          )}
          {current && (
            <>
              <button type="button" className="btn small ghost" onClick={() => setDialog("edit")}>
                Rename or move
              </button>
              {!current.archived && (
                <button
                  type="button"
                  className="btn small ghost"
                  onClick={() =>
                    folderAction.mutate(
                      { path: `/folders/${current.id}/archive`, json: { archived: true } },
                      {
                        onSuccess: () =>
                          setStatus({
                            text: `Archived the folder ${current.name} with everything in it.`,
                            undo: () => folderAction.mutate({ path: `/folders/${current.id}/archive`, json: { archived: false } }),
                          }),
                      },
                    )
                  }
                >
                  Archive folder
                </button>
              )}
              <button
                type="button"
                className="btn small ghost"
                disabled={!empty || folderAction.isPending}
                title={empty ? undefined : "Only an empty folder can be removed; archive it instead"}
                onClick={() => folderAction.mutate({ path: `/folders/${current.id}`, method: "DELETE" })}
              >
                Remove empty folder
              </button>
            </>
          )}
        </div>
      </div>
      {status && (
        <div className="notice small row" role="status" style={{ justifyContent: "space-between" }}>
          <span>{status.text}</span>
          {status.undo && (
            <button
              type="button"
              className="btn small ghost"
              onClick={() => {
                status.undo?.();
                setStatus(null);
              }}
            >
              Undo
            </button>
          )}
        </div>
      )}
      {(move.error || archive.error || folderAction.error) && <ErrorNote error={move.error ?? archive.error ?? folderAction.error} />}
      {folderAction.isSuccess && folderAction.variables?.method === "DELETE" && (
        <div className="notice small">
          Folder removed. <Link to={href(current?.parent_id ?? null)}>Go up</Link>
        </div>
      )}
      {children.length > 0 && (
        <div className="folder-grid">
          {children.map((f) => (
            <FolderTile key={f.id} folder={f} href={href(f.id)} onDrop={(ids) => moveTo(ids, f.id)} />
          ))}
        </div>
      )}
      {selected.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Selected material">
          <strong className="small">{plural(selected.size, "item")} selected</strong>
          <label className="row small" style={{ gap: 6 }}>
            Move to
            <select value={target} onChange={(e) => setTarget(e.target.value)} className="inline-input">
              <option value="">Top level of the course</option>
              {choices.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.path}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn small" disabled={move.isPending} onClick={() => moveTo([...selected], target || null)}>
            Move
          </button>
          <button type="button" className="btn small" disabled={archive.isPending} onClick={archiveSelected}>
            Archive
          </button>
          <button type="button" className="btn small ghost" onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      )}
      {files.length > 0 && <SourceTable sources={files} selected={selected} onToggle={toggle} />}
      {images.length > 0 && (
        <Card title="Photos" meta={plural(images.length, "image")}>
          <Gallery images={images} selected={selected} onToggle={toggle} />
          <p className="tiny muted" style={{ marginTop: 10 }}>
            Photos have no extracted text. Claude looks at one when you ask (for example “look at my notes from lecture 3”).
          </p>
        </Card>
      )}
      {here.length === 0 && children.length === 0 && (
        <Empty title={folderId ? "This folder is empty" : "No material yet"}>
          {folderId
            ? "Upload files here, or select files elsewhere and move them in (drag them onto the folder, or use Move to)."
            : "Drop a PDF, Word, PowerPoint, Excel, Markdown or text file or a photo below, or ask Claude to import one from your computer."}
        </Empty>
      )}
      {here.length > 1 && (
        <p className="tiny muted">Select files to move them into a folder or archive them; you can also drag them onto a folder or the path above.</p>
      )}
      {!insideArchived && (
        <Card title={current ? `Add material to ${current.name}` : "Add material"}>
          <Upload courseId={courseId} folderId={folderId} />
        </Card>
      )}
      {dialog && (
        <FolderDialog
          folder={dialog === "edit" ? current : undefined}
          courseId={courseId}
          parentId={folderId}
          folders={all}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

export function CourseLibraryPage() {
  const { courseId = "" } = useParams();
  const [params] = useSearchParams();
  const courses = useCourses();
  const groups = useGroups();
  const refresh = useRefreshLibrary();
  const restore = useMutation({
    mutationFn: () => request(`/courses/${courseId}`, { method: "PATCH", json: { archived: false } }),
    onSuccess: refresh,
  });
  const course = courses.data?.find((c) => c.id === courseId);
  const folderId = params.get("folder");
  const path = course ? groupPath(groups.data, course.group_id) : "";
  return (
    <div className="page">
      <PageHead
        title={
          <span className="row" style={{ gap: 10 }}>
            <CourseDot color={course?.color} />
            {course?.title ?? "Course"}
          </span>
        }
        sub={path || undefined}
        crumbs={[{ to: "/library", label: "Library" }]}
      >
        <Link to={`/courses/${courseId}`} className="btn small">
          Open course
        </Link>
      </PageHead>
      {course?.status === "archived" && (
        <div className="notice warn small" style={{ marginBottom: 16 }}>
          This course is archived.{" "}
          <button type="button" className="btn small" disabled={restore.isPending} onClick={() => restore.mutate()}>
            Restore course
          </button>
          {restore.error && <ErrorNote error={restore.error} />}
        </div>
      )}
      <FolderBrowser courseId={courseId} folderId={folderId} href={(id) => `/library/course/${courseId}${id ? `?folder=${id}` : ""}`} />
    </div>
  );
}

// ------------------------------------------------------------------ one file

const PAGE = 25;

function CategorySelect({ source }: { source: Source }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (category: MaterialCategory) => request<Source>(`/sources/${source.id}`, { method: "PATCH", json: { category } }),
    onSuccess: (updated) => {
      qc.setQueryData(["source", source.id], updated);
      void qc.invalidateQueries({ queryKey: ["sources"] });
      void qc.invalidateQueries({ queryKey: ["courses"] });
    },
  });
  return (
    <label>
      <span className="sr-only">Kind of material</span>
      <select
        className="inline-input"
        value={source.category}
        disabled={save.isPending}
        onChange={(e) => save.mutate(e.target.value as MaterialCategory)}
        aria-label="Kind of material"
      >
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {CATEGORY_LABEL[c]}
          </option>
        ))}
      </select>
    </label>
  );
}

function FolderSelect({ source }: { source: Source }) {
  const folders = useFolders(source.course_id);
  const { move } = useSourceActions();
  const options = (folders.data ?? []).filter((f) => !f.hidden || f.id === source.folder_id).sort((a, b) => a.path.localeCompare(b.path));
  return (
    <label>
      <span className="sr-only">Folder</span>
      <select
        className="inline-input"
        value={source.folder_id ?? ""}
        disabled={move.isPending}
        onChange={(e) => move.mutate({ ids: [source.id], folderId: e.target.value || null })}
        aria-label="Folder"
      >
        <option value="">Top level of the course</option>
        {options.map((f) => (
          <option key={f.id} value={f.id}>
            {f.path}
          </option>
        ))}
      </select>
    </label>
  );
}

function Details({ s }: { s: Source }) {
  return (
    <Card title="Details">
      <dl className="kv small">
        <dt>Type</dt>
        <dd>{SOURCE_KIND[s.kind] ?? s.kind.toUpperCase()}</dd>
        <dt>Size</dt>
        <dd>{bytes(s.byte_size)}</dd>
        {COUNT_LABEL[s.kind] && (
          <>
            <dt>{COUNT_LABEL[s.kind]}</dt>
            <dd>{s.page_count ?? "—"}</dd>
          </>
        )}
        <dt>Version</dt>
        <dd>{s.version}</dd>
        <dt>Added</dt>
        <dd>{dateTime(s.uploaded_at)}</dd>
        <dt>Via</dt>
        <dd>{s.origin === "paste" ? "Pasted text" : s.origin === "import" ? "Imported from ChatGPT" : "File upload"}</dd>
        {s.parsed_at && (
          <>
            <dt>Extracted</dt>
            <dd>{dateTime(s.parsed_at)}</dd>
          </>
        )}
        {s.archived_at && (
          <>
            <dt>Archived</dt>
            <dd>{dateTime(s.archived_at)}</dd>
          </>
        )}
      </dl>
      {s.parse_notes.length > 0 && (
        <ul className="small muted" style={{ marginTop: 12 }}>
          {s.parse_notes.map((n, i) => (
            <li key={i}>{parseNoteLabel(String(n))}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function SourcePage() {
  const { sourceId = "" } = useParams();
  const [offset, setOffset] = useState(0);
  const courses = useCourses();
  const { archive } = useSourceActions();
  const titles = Object.fromEntries((courses.data ?? []).map((c) => [c.id, c.title]));
  const source = useQuery({
    queryKey: ["source", sourceId],
    queryFn: () => get<Source>(`/sources/${sourceId}`),
    refetchInterval: (q) => (q.state.data && ["pending", "processing"].includes(q.state.data.parse_state) ? 2500 : false),
  });
  const sections = useQuery({
    queryKey: ["sections", sourceId, offset],
    queryFn: () => get<{ sections: Section[]; total: number }>(`/sources/${sourceId}/sections`, { offset, limit: PAGE }),
    enabled: source.data?.parse_state === "ready" || source.data?.parse_state === "needs_attention",
  });
  return (
    <div className="page">
      <Async q={source} lines={6}>
        {(s) => {
          const crumbs = [
            { to: "/library", label: "Library" },
            { to: `/library/course/${s.course_id}`, label: titles[s.course_id] ?? "Course" },
          ];
          if (s.folder_id && s.folder) crumbs.push({ to: `/library/course/${s.course_id}?folder=${s.folder_id}`, label: s.folder });
          let body: ReactNode;
          if (s.kind === "image") {
            body = (
              <Card title="Photo">
                <img className="image-full" src={`${API}/sources/${s.id}/file`} alt={s.filename} />
                <p className="tiny muted" style={{ marginTop: 10 }}>
                  {s.byte_size > 4_500_000
                    ? "This photo is larger than 4.5 MB, so Claude cannot look at it. Upload a smaller copy."
                    : "Claude can look at this photo when you ask in a chat of this course."}
                </p>
              </Card>
            );
          } else if (sections.data) {
            body = (
              <Card title="Extracted text" meta={`${plural(sections.data.total, "section")}`}>
                <ol className="list" style={{ listStyle: "none" }}>
                  {sections.data.sections.map((sec) => (
                    <li key={sec.id} id={sec.id} className="stack" style={{ gap: 4 }}>
                      <div className="small muted">
                        {sec.citation_label}
                        {sec.heading && ` · ${sec.heading}`}
                      </div>
                      <p className="reading pre small">{sec.text}</p>
                    </li>
                  ))}
                </ol>
                {sections.data.total > PAGE && (
                  <div className="row" style={{ justifyContent: "space-between", marginTop: 12 }}>
                    <button type="button" className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                      Previous
                    </button>
                    <span className="small muted">
                      {offset + 1}–{Math.min(offset + PAGE, sections.data.total)} of {sections.data.total}
                    </span>
                    <button type="button" className="btn small" disabled={offset + PAGE >= sections.data.total} onClick={() => setOffset(offset + PAGE)}>
                      Next
                    </button>
                  </div>
                )}
              </Card>
            );
          } else {
            body = (
              <Card title="Extracted text">
                <p className="muted small">
                  {sections.isPending && sections.fetchStatus !== "idle"
                    ? "Loading…"
                    : s.parse_state === "failed"
                      ? s.parse_message ?? "Text couldn't be extracted. Try a text-based file or paste the content."
                      : "Extraction is running in the background."}
                </p>
              </Card>
            );
          }
          return (
            <>
              <PageHead title={s.filename} crumbs={crumbs}>
                {s.kind !== "image" && <StateChip state={s.parse_state} />}
                <CategorySelect source={s} />
                <FolderSelect source={s} />
                <button
                  type="button"
                  className="btn small"
                  disabled={archive.isPending}
                  onClick={() => archive.mutate({ ids: [s.id], archived: !s.archived })}
                >
                  {s.archived ? "Restore" : "Archive"}
                </button>
                <a className="btn small" href={`${API}/sources/${s.id}/file`} download>
                  Download original
                </a>
              </PageHead>
              {s.hidden && (
                <div className="notice warn small" style={{ marginBottom: 16 }}>
                  {s.archived ? "This file is archived" : "This file is in an archived folder"}: hidden from the library and from search.
                  Claude can still read the parts it already cited.
                </div>
              )}
              {archive.error && <ErrorNote error={archive.error} />}
              <div className="split">
                <div className="stack">
                  {s.parse_message && <div className={s.parse_state === "failed" ? "notice bad" : "notice warn"}>{s.parse_message}</div>}
                  {body}
                </div>
                <Details s={s} />
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}
