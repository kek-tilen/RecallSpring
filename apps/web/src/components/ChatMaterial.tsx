import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { get } from "../api";
import type { Course, Source } from "../types";
import { ErrorNote, Loading, Modal } from "./ui";

/** A file a conversation may use, as the server reports it. */
export interface ChosenFile {
  id: string;
  course_id: string;
  filename: string;
  kind: string;
  category: string;
  has_text: boolean;
  /** RecallSpring is still extracting its text. */
  reading?: boolean;
}

export const MAX_FILES = 20;

const CATEGORY: Record<string, string> = {
  material: "Material",
  notes: "Notes",
  exercises: "Exercises",
  past_paper: "Past papers",
  chat: "Chats",
  other: "Other",
};

/**
 * Choose which of the learner's files ChatGPT may see in one conversation. Only excerpts of these files that match
 * each message are sent, and only when a message is sent; nothing else from RecallSpring is.
 */
export function MaterialPicker({
  open,
  chosen,
  busy,
  error,
  onSave,
  onClose,
}: {
  open: boolean;
  chosen: string[];
  busy?: boolean;
  error?: unknown;
  onSave: (ids: string[], files: Source[]) => void;
  onClose: () => void;
}) {
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => get<Course[]>("/courses"), enabled: open });
  const sources = useQuery({ queryKey: ["sources", "all"], queryFn: () => get<Source[]>("/sources"), enabled: open });
  const [picked, setPicked] = useState<string[]>(chosen);
  const [query, setQuery] = useState("");
  const [lastOpen, setLastOpen] = useState(open);
  if (open !== lastOpen) {
    // Start from what the conversation uses each time the dialog opens.
    setLastOpen(open);
    if (open) {
      setPicked(chosen);
      setQuery("");
    }
  }
  const q = query.trim().toLocaleLowerCase();
  const groups = useMemo(() => {
    const all = sources.data ?? [];
    return (courses.data ?? [])
      .map((c) => ({
        course: c,
        files: all.filter(
          (s) =>
            s.course_id === c.id &&
            (!q || s.filename.toLocaleLowerCase().includes(q) || (s.folder ?? "").toLocaleLowerCase().includes(q)),
        ),
      }))
      .filter((g) => g.files.length > 0);
  }, [courses.data, sources.data, q]);
  const full = picked.length >= MAX_FILES;

  function toggle(id: string) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX_FILES ? p : [...p, id]));
  }
  function toggleCourse(ids: string[], on: boolean) {
    setPicked((p) => (on ? [...p, ...ids.filter((id) => !p.includes(id))].slice(0, MAX_FILES) : p.filter((x) => !ids.includes(x))));
  }

  return (
    <Modal open={open} title="Material for this conversation" onClose={onClose} wide>
      <p className="small" style={{ margin: 0 }}>
        With each message, RecallSpring sends ChatGPT the parts of these files that best match it (about 30,000
        characters at most; small files whole). ChatGPT cites them as S1, S2, … and you can see what was sent under each
        message. Nothing else from RecallSpring is sent: no notes, grades or other files. Up to {MAX_FILES} files.
      </p>
      <label className="field">
        <span className="sr-only">Search files</span>
        <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search files or folders" />
      </label>
      <div className="material-list">
        {courses.error || sources.error ? (
          <ErrorNote error={courses.error ?? sources.error} />
        ) : !courses.data || !sources.data ? (
          <Loading lines={4} />
        ) : groups.length === 0 ? (
          <p className="small muted">{q ? "No file matches." : "Your library has no files yet."}</p>
        ) : (
          groups.map(({ course, files }) => {
            const usable = files.filter((f) => f.section_count > 0).map((f) => f.id);
            const allOn = usable.length > 0 && usable.every((id) => picked.includes(id));
            return (
              <fieldset key={course.id} className="material-course">
                <legend className="row" style={{ gap: 8 }}>
                  <strong>{course.title}</strong>
                  {usable.length > 1 && (
                    <button type="button" className="linklike tiny" onClick={() => toggleCourse(usable, !allOn)}>
                      {allOn ? "Clear course" : "Choose all"}
                    </button>
                  )}
                </legend>
                {files.map((f) => {
                  const noText = f.section_count === 0;
                  const on = picked.includes(f.id);
                  return (
                    <label key={f.id} className={noText ? "material-file muted" : "material-file"}>
                      <input type="checkbox" checked={on} disabled={noText || (full && !on)} onChange={() => toggle(f.id)} />
                      <span className="material-name">{f.filename}</span>
                      <span className="tiny muted">
                        {[CATEGORY[f.category] ?? f.category, f.folder, noText ? "no text to send" : null].filter(Boolean).join(" · ")}
                      </span>
                    </label>
                  );
                })}
              </fieldset>
            );
          })
        )}
      </div>
      {error ? <ErrorNote error={error} /> : null}
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span className="small muted">
          {picked.length === 0 ? "No files: ChatGPT sees only the conversation." : `${picked.length} of ${MAX_FILES} files chosen`}
        </span>
        <span className="row" style={{ gap: 8 }}>
          {picked.length > 0 && (
            <button type="button" className="btn ghost" onClick={() => setPicked([])}>
              Clear
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => onSave(picked, (sources.data ?? []).filter((f) => picked.includes(f.id)))}>
            Use these files
          </button>
        </span>
      </div>
    </Modal>
  );
}
