import { useState } from "react";
import { useSources } from "../queries";
import type { ImportResult, Source } from "../types";
import { Async, Modal } from "./ui";
import { Upload } from "./Upload";

/** What a note links: the file's ID, name and kind (pictures are shown in the note, other files are links). */
export type PickedFile = Pick<Source, "id" | "filename" | "kind" | "course_id">;

/** The Markdown a note uses for a file: a picture on its own line, any other file as a link. */
export function refText(file: Pick<Source, "id" | "filename" | "kind">): string {
  const name = file.filename.replace(/[[\]\n\r]/g, " ").trim() || "file";
  return file.kind === "image" ? `![${name}](source:${file.id})` : `[${name}](source:${file.id})`;
}

/**
 * Pick files for a note: one already in the Library (the note's course first) or a new upload, which is saved in
 * the Library under the note's course with the usual checks. The note only stores a reference; the file stays in
 * the Library.
 */
export function NoteAttachDialog({
  open,
  courseId,
  onClose,
  onPicked,
}: {
  open: boolean;
  courseId: string;
  onClose: () => void;
  onPicked: (files: PickedFile[]) => void;
}) {
  const [tab, setTab] = useState<"library" | "upload">("library");
  return (
    <Modal open={open} title="Insert a file" onClose={onClose} wide>
      <div className="row" role="group" aria-label="Where the file comes from">
        <button type="button" className="chip-filter" aria-pressed={tab === "library"} onClick={() => setTab("library")}>
          From Library
        </button>
        <button type="button" className="chip-filter" aria-pressed={tab === "upload"} onClick={() => setTab("upload")}>
          Upload new
        </button>
      </div>
      {open && tab === "library" && <LibraryPick courseId={courseId} onPick={(f) => {
            onPicked([f]);
            onClose();
          }} />}
      {open && tab === "upload" && (
        <>
          <p className="small" style={{ margin: 0 }}>
            The file is saved in your Library under this note&apos;s course, and the note links to it. Pictures are shown in the
            note.
          </p>
          <Upload
            courseId={courseId}
            onImported={(result: ImportResult) => {
              if (result.imported.length) onPicked(result.imported);
              if (!result.skipped.length) onClose(); // otherwise the dialog stays open and lists what was left out
            }}
          />
        </>
      )}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}

function LibraryPick({ courseId, onPick }: { courseId: string; onPick: (file: PickedFile) => void }) {
  const q = useSources();
  const [search, setSearch] = useState("");
  return (
    <Async q={q}>
      {(sources) => {
        const needle = search.trim().toLowerCase();
        const shown = sources
          .filter((s) => !needle || s.filename.toLowerCase().includes(needle) || (s.folder ?? "").toLowerCase().includes(needle))
          // The note's own course first, then the rest; newest first within each.
          .sort((a, b) => Number(b.course_id === courseId) - Number(a.course_id === courseId) || b.uploaded_at.localeCompare(a.uploaded_at))
          .slice(0, 50);
        return (
          <div className="stack">
            <label>
              <span className="sr-only">Search your Library</span>
              <input type="search" className="inline-input" placeholder="Search by file name or folder" value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
            </label>
            {shown.length === 0 ? (
              <p className="small muted">{sources.length ? "No file matches." : "Your Library is empty. Upload a file instead."}</p>
            ) : (
              <ul className="list small" aria-label="Library files">
                {shown.map((s) => (
                  <li key={s.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                    <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }} title={s.filename}>
                      {s.filename}
                      <span className="muted">
                        {" "}
                        · {s.kind}
                        {s.course_id !== courseId ? " · other course" : ""}
                        {s.folder ? ` · ${s.folder}` : ""}
                      </span>
                    </span>
                    <button type="button" className="btn small" onClick={() => onPick(s)} aria-label={`Insert ${s.filename}`}>
                      Insert
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      }}
    </Async>
  );
}
