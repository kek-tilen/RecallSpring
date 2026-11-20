import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";
import { request } from "../api";
import { bytes } from "../format";
import { useCourses, useUploadLimits } from "../queries";
import type { MaterialCategory, Source } from "../types";
import { ErrorNote } from "./ui";

// Until the server's list has loaded (it also lists code files); the server checks every file again.
const FALLBACK_ACCEPT =
  ".pdf,.docx,.pptx,.ppsx,.xlsx,.odt,.odp,.ods,.md,.markdown,.txt,.csv,.tsv,.srt,.vtt,.ipynb,.tex,.png,.jpg,.jpeg,.webp";
const MB = 1024 * 1024;

function extension(name: string): string {
  return (/\.[^.]+$/.exec(name)?.[0] ?? "").toLowerCase();
}
const CLAUDE_IMAGE_BYTES = 4_500_000; // Claude can look at images up to this size
const MAX_SIDE = 2400; // plenty for handwriting; keeps phone photos small

/** Phone photos are often too large for Claude: shrink them in the browser (the server never decodes images). */
async function shrinkImage(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.size <= CLAUDE_IMAGE_BYTES) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file; // keep the original if the browser cannot decode it
  }
}

const CATEGORY_OPTIONS: [MaterialCategory, string][] = [
  ["material", "Lecture material"],
  ["notes", "My notes"],
  ["exercises", "Exercises"],
  ["past_paper", "Past papers"],
  ["other", "Other"],
];

/** Drag-and-drop with click-to-browse. Extraction runs in the background worker; the list polls its state. */
export function Upload({ courseId: fixedCourse }: { courseId?: string }) {
  const courses = useCourses();
  const [courseId, setCourseId] = useState(fixedCourse ?? "");
  const [category, setCategory] = useState<MaterialCategory>("material");
  const [over, setOver] = useState(false);
  const [done, setDone] = useState<Source[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const limits = useUploadLimits();
  const chosen = fixedCourse ?? (courseId || courses.data?.[0]?.id || "");
  const groups = limits.data?.extensions;
  const accept = groups ? [...groups.document, ...groups.text, ...groups.image].join(",") : FALLBACK_ACCEPT;

  /** Documents may be large (pictures, scans); text files need far less. Photos are shrunk before upload. */
  function limitFor(file: File): number | null {
    const l = limits.data;
    if (file.type.startsWith("image/")) return null;
    if (!l) return 100 * MB;
    return l.extensions.text.includes(extension(file.name)) ? l.text_bytes : l.document_bytes;
  }

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const out: Source[] = [];
      for (const original of files) {
        const file = await shrinkImage(original);
        const form = new FormData();
        form.set("course_id", chosen);
        form.set("category", category);
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
      void qc.invalidateQueries({ queryKey: ["upload-limits"] });
    },
  });

  function send(list: FileList | null) {
    setLocalError(null);
    const files = Array.from(list ?? []);
    if (!files.length) return;
    const tooBig = files.find((f) => {
      const limit = limitFor(f);
      return limit !== null && f.size > limit;
    });
    if (tooBig) {
      setLocalError(
        `${tooBig.name} is ${bytes(tooBig.size)}; the limit for this type of file is ${bytes(limitFor(tooBig) ?? 0)}. ` +
          "Split it, or compress the PDF (scans and pictures make files large; the text stays small).",
      );
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
      <label className="field">
        File as
        <select value={category} onChange={(e) => setCategory(e.target.value as MaterialCategory)}>
          {CATEGORY_OPTIONS.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <div
        className={over ? "dropzone over" : "dropzone"}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
      >
        <strong style={{ color: "var(--ink)" }}>Drop lecture files, notes or photos here</strong>
        <span className="small">
          PDF, Word, PowerPoint, Excel, OpenDocument, Markdown, text, CSV, subtitles (.srt, .vtt), notebooks (.ipynb),
          LaTeX, code, or photos. Up to {bytes(limits.data?.document_bytes ?? 100 * MB)} per document and{" "}
          {bytes(limits.data?.text_bytes ?? 10 * MB)} per text file; large photos are shrunk so Claude can look at them.
        </span>
        <button type="button" className="btn small" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? "Uploading…" : "Choose files"}
        </button>
        <input
          ref={input}
          type="file"
          accept={accept}
          multiple
          hidden
          onChange={(e) => {
            send(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {limits.data && (
        <span className="small muted">
          Library: {bytes(limits.data.library_used_bytes)} of {bytes(limits.data.library_bytes)} used.
          {!limits.data.page_renderer_available &&
            " With LibreOffice installed on the RecallSpring computer, Claude can also look at whole slides and Word pages."}
        </span>
      )}
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
