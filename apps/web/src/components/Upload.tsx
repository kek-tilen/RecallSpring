import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";
import { request } from "../api";
import { bytes } from "../format";
import { useCourses } from "../queries";
import type { Source } from "../types";
import { ErrorNote } from "./ui";

const ACCEPT = ".pdf,.md,.markdown,.txt,application/pdf,text/markdown,text/plain";
const MAX_BYTES = 30 * 1024 * 1024;

/** Drag-and-drop with click-to-browse. Extraction runs in the background worker; the list polls its state. */
export function Upload({ courseId: fixedCourse }: { courseId?: string }) {
  const courses = useCourses();
  const [courseId, setCourseId] = useState(fixedCourse ?? "");
  const [over, setOver] = useState(false);
  const [done, setDone] = useState<Source[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const chosen = fixedCourse ?? (courseId || courses.data?.[0]?.id || "");

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const out: Source[] = [];
      for (const file of files) {
        const form = new FormData();
        form.set("course_id", chosen);
        form.set("file", file);
        out.push(await request<Source>("/sources", { form }));
      }
      return out;
    },
    onSuccess: (sources) => {
      setDone(sources);
      void qc.invalidateQueries({ queryKey: ["sources"] });
      void qc.invalidateQueries({ queryKey: ["courses"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  function send(list: FileList | null) {
    setLocalError(null);
    const files = Array.from(list ?? []);
    if (!files.length) return;
    const tooBig = files.find((f) => f.size > MAX_BYTES);
    if (tooBig) {
      setLocalError(`${tooBig.name} is ${bytes(tooBig.size)}; the limit is ${bytes(MAX_BYTES)}.`);
      return;
    }
    if (!chosen) {
      setLocalError("Create a course first (ask Claude, or use the connector's create_course).");
      return;
    }
    upload.mutate(files);
  }

  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    send(e.dataTransfer.files);
  }

  return (
    <div className="stack">
      {!fixedCourse && (
        <label className="field">
          Course
          <select value={chosen} onChange={(e) => setCourseId(e.target.value)} disabled={!courses.data?.length}>
            {courses.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
      )}
      <div
        className={over ? "dropzone over" : "dropzone"}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
      >
        <strong style={{ color: "var(--ink)" }}>Drop PDF, Markdown or text files here</strong>
        <span className="small">Up to 30 MB each. Scanned PDFs without a text layer are flagged, never guessed.</span>
        <button type="button" className="btn small" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? "Uploading…" : "Choose files"}
        </button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            send(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {localError && <div className="notice warn">{localError}</div>}
      {upload.error && <ErrorNote error={upload.error} />}
      {done.length > 0 && !upload.isPending && (
        <div className="notice small" role="status">
          Uploaded {done.map((s) => s.filename).join(", ")}.
          {done.some((s) => s.duplicate_of_id) && " Some files were already in your library; RecallSpring kept one copy."}{" "}
          Text extraction runs in the background.
        </div>
      )}
    </div>
  );
}
