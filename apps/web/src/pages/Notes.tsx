import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, get, newKey, request } from "../api";
import { Async, Card, Empty, ErrorNote, PageHead } from "../components/ui";
import { dateTime, relativeDay } from "../format";
import { courseTitles, useCourses, useNotes } from "../queries";
import type { Note, NoteRevision } from "../types";

export function NewNoteButton({ courseId }: { courseId: string }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => request<Note>("/notes", { json: { course_id: courseId, client_note_id: newKey(), title: "Untitled note", body: "" } }),
    onSuccess: (note) => {
      void qc.invalidateQueries({ queryKey: ["notes"] });
      navigate(`/notes/${note.id}`);
    },
  });
  return (
    <>
      <button type="button" className="btn primary" onClick={() => create.mutate()} disabled={create.isPending || !courseId}>
        New note
      </button>
      {create.error && <ErrorNote error={create.error} />}
    </>
  );
}

export function NoteList({ courseId, titles }: { courseId?: string; titles?: Record<string, string> }) {
  const q = useNotes(courseId);
  return (
    <Async q={q}>
      {(notes) =>
        notes.length === 0 ? (
          <Empty title="No notes yet">Summaries you write after a learning session are saved here as notes.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Note</th>
                  {titles && <th>Course</th>}
                  <th>Saved</th>
                  <th>Revision</th>
                </tr>
              </thead>
              <tbody>
                {notes.map((n) => (
                  <tr key={n.id}>
                    <td>
                      <Link to={`/notes/${n.id}`} style={{ fontWeight: 600 }}>
                        {n.title}
                      </Link>
                      <div className="small muted" style={{ maxWidth: "60ch", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {n.body.slice(0, 160) || "Empty"}
                      </div>
                    </td>
                    {titles && <td className="small">{titles[n.course_id] ?? ""}</td>}
                    <td className="small nowrap" title={dateTime(n.saved_at)}>
                      {relativeDay(n.saved_at)}
                    </td>
                    <td className="small">{n.revision}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </Async>
  );
}

export function NotesPage() {
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  const [courseId, setCourseId] = useState("");
  const chosen = courseId || courses.data?.[0]?.id || "";
  return (
    <div className="page">
      <PageHead title="Notes" sub="Your own words: learning summaries and notes. Every save keeps a revision.">
        {courses.data && courses.data.length > 1 && (
          <label>
            <span className="sr-only">Course for the new note</span>
            <select className="inline-input" value={chosen} onChange={(e) => setCourseId(e.target.value)}>
              {courses.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
        )}
        <NewNoteButton courseId={chosen} />
      </PageHead>
      <NoteList titles={titles} />
    </div>
  );
}

type SaveState = { kind: "saved"; at: string } | { kind: "dirty" } | { kind: "saving" } | { kind: "conflict" } | { kind: "error"; error: unknown };

function Editor({ note }: { note: Note }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(note.body);
  const [state, setState] = useState<SaveState>({ kind: "saved", at: note.saved_at });
  const base = useRef(note.revision);
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef({ title, body });
  latest.current = { title, body };

  async function save() {
    const { title: t, body: b } = latest.current;
    setState({ kind: "saving" });
    try {
      const saved = await request<Note>(`/notes/${note.id}`, {
        method: "PATCH",
        json: { base_revision: base.current, title: t.trim() || "Untitled note", body: b },
      });
      base.current = saved.revision;
      qc.setQueryData(["note", note.id], saved);
      void qc.invalidateQueries({ queryKey: ["notes"] });
      void qc.invalidateQueries({ queryKey: ["note-revisions", note.id] });
      setState(latest.current.title === t && latest.current.body === b ? { kind: "saved", at: saved.saved_at } : { kind: "dirty" });
    } catch (error) {
      if (error instanceof ApiError && error.code === "revision_conflict") {
        setState({ kind: "conflict" });
        void qc.invalidateQueries({ queryKey: ["note-revisions", note.id] });
      } else setState({ kind: "error", error });
    }
  }

  function change(next: { title?: string; body?: string }) {
    if (next.title !== undefined) setTitle(next.title);
    if (next.body !== undefined) setBody(next.body);
    if (state.kind === "conflict") return;
    setState({ kind: "dirty" });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void save(), 1200);
  }

  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (state.kind === "dirty" || state.kind === "saving") e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [state.kind]);

  const status =
    state.kind === "saved"
      ? `Saved ${dateTime(state.at)}`
      : state.kind === "saving"
        ? "Saving…"
        : state.kind === "dirty"
          ? "Unsaved changes"
          : state.kind === "conflict"
            ? "Conflict"
            : "Not saved";

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="small muted" role="status" aria-live="polite">
          {status}
        </span>
        {state.kind === "dirty" && (
          <button type="button" className="btn small" onClick={() => void save()}>
            Save now
          </button>
        )}
      </div>
      {state.kind === "conflict" && (
        <div className="notice warn">
          This note changed elsewhere (for example in Claude). Both versions are kept in the revision list. Reload to continue from the
          newest version; your text below is still here to copy.
          <div style={{ marginTop: 8 }}>
            <button type="button" className="btn small" onClick={() => window.location.reload()}>
              Reload note
            </button>
          </div>
        </div>
      )}
      {state.kind === "error" && <ErrorNote error={state.error} />}
      <label>
        <span className="sr-only">Title</span>
        <input type="text" className="editor-title" value={title} maxLength={200} onChange={(e) => change({ title: e.target.value })} />
      </label>
      <label>
        <span className="sr-only">Note text</span>
        <textarea className="editor-body" value={body} onChange={(e) => change({ body: e.target.value })} spellCheck />
      </label>
    </div>
  );
}

function Revisions({ noteId }: { noteId: string }) {
  const q = useQuery({ queryKey: ["note-revisions", noteId], queryFn: () => get<NoteRevision[]>(`/notes/${noteId}/revisions`) });
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card title="Revisions">
      <Async q={q}>
        {(revs) =>
          revs.length === 0 ? (
            <p className="small muted">No earlier versions.</p>
          ) : (
            <ul className="list small">
              {[...revs].sort((a, b) => b.revision - a.revision || b.saved_at.localeCompare(a.saved_at)).map((r) => (
                <li key={r.id}>
                  <button type="button" className="btn ghost small" aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>
                    Rev {r.revision} · {dateTime(r.saved_at)}
                  </button>
                  {r.kind === "conflict" && <span className="chip warn">Conflict copy</span>}
                  {open === r.id && (
                    <div className="answer pre small" style={{ marginTop: 6, maxHeight: 280, overflow: "auto" }}>
                      <strong>{r.title}</strong>
                      {"\n"}
                      {r.body}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </Card>
  );
}

export function NotePage() {
  const { noteId = "" } = useParams();
  const q = useQuery({ queryKey: ["note", noteId], queryFn: () => get<Note>(`/notes/${noteId}`), staleTime: Infinity });
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  return (
    <div className="page">
      <Async q={q} lines={6}>
        {(note) => (
          <>
            <PageHead
              title="Note"
              crumbs={[
                { to: "/notes", label: "Notes" },
                { to: `/courses/${note.course_id}?tab=notes`, label: titles[note.course_id] ?? "Course" },
              ]}
            />
            <div className="split">
              <Editor key={note.id} note={note} />
              <Revisions noteId={note.id} />
            </div>
          </>
        )}
      </Async>
    </div>
  );
}

