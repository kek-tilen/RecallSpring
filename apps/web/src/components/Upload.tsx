import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";
import { ApiError, request } from "../api";
import { bytes } from "../format";
import { useCourses, useUploadLimits } from "../queries";
import type { ImportResult, MaterialCategory, Source } from "../types";
import { ErrorNote } from "./ui";

// Until the server's list has loaded (it also lists code files); the server checks every file again.
const FALLBACK_ACCEPT =
  ".pdf,.docx,.pptx,.ppsx,.xlsx,.odt,.odp,.ods,.md,.markdown,.txt,.csv,.tsv,.srt,.vtt,.ipynb,.tex,.png,.jpg,.jpeg,.webp";
const MB = 1024 * 1024;
const MAX_FOLDER_FILES = 500;
const SKIPPED_DIRS = new Set(["__macosx", ".git", "node_modules", "__pycache__", ".ipynb_checkpoints"]);

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

export const CATEGORY_OPTIONS: [MaterialCategory, string][] = [
  ["material", "Lecture material"],
  ["notes", "My notes"],
  ["exercises", "Exercises"],
  ["past_paper", "Past papers"],
  ["other", "Other"],
];

/** A file and the folder it came from inside an uploaded or dropped folder ("Week 3/Slides"). */
interface Picked {
  file: File;
  dir: string | null;
}

/** Hidden and system files (.DS_Store, __MACOSX, Thumbs.db) are never uploaded. */
function isJunk(p: Picked): boolean {
  const parts = [...(p.dir ? p.dir.split("/") : []), p.file.name];
  return (
    parts.some((s) => s.startsWith(".") || SKIPPED_DIRS.has(s.toLowerCase())) ||
    ["thumbs.db", "desktop.ini"].includes(p.file.name.toLowerCase())
  );
}

function fromInput(list: FileList | null): Picked[] {
  return Array.from(list ?? []).map((file) => {
    const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath ?? "";
    const dir = rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : null;
    return { file, dir };
  });
}

/** Files of dropped folders, with their folders; plain files as they are. */
async function fromDrop(dt: DataTransfer): Promise<Picked[]> {
  const entries = Array.from(dt.items)
    .map((i) => i.webkitGetAsEntry?.())
    .filter((e): e is FileSystemEntry => !!e);
  if (!entries.some((e) => e.isDirectory)) return Array.from(dt.files).map((file) => ({ file, dir: null }));
  const out: Picked[] = [];
  async function walk(entry: FileSystemEntry, dir: string): Promise<void> {
    if (out.length > MAX_FOLDER_FILES) return;
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
      out.push({ file, dir: dir || null });
      return;
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const inner = dir ? `${dir}/${entry.name}` : entry.name;
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
      if (batch.length === 0) break;
      for (const e of batch) await walk(e, inner);
    }
  }
  for (const e of entries) await walk(e, "");
  return out;
}

/**
 * Drag-and-drop with click-to-browse: files, whole folders (their folders become library folders) and ZIPs (unpacked
 * on the server, folders kept). Extraction runs in the background worker; the list polls its state.
 */
export function Upload({
  courseId: fixedCourse,
  folderId,
  onImported,
}: {
  courseId?: string;
  folderId?: string | null;
  /** Called after an upload with what was saved and what was left out (Chat adds the files to a conversation). */
  onImported?: (result: ImportResult) => void;
}) {
  const courses = useCourses();
  const [courseId, setCourseId] = useState(fixedCourse ?? "");
  const [category, setCategory] = useState<MaterialCategory>("material");
  const [over, setOver] = useState(false);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const limits = useUploadLimits();
  const chosen = fixedCourse ?? (courseId || courses.data?.[0]?.id || "");
  const groups = limits.data?.extensions;
  const accept = (groups ? [...groups.document, ...groups.text, ...groups.image].join(",") : FALLBACK_ACCEPT) + ",.zip";
  const allowed = new Set(accept.split(","));

  /** Documents may be large (pictures, scans); text files need far less. Photos are shrunk before upload. */
  function limitFor(file: File): number | null {
    const l = limits.data;
    if (file.type.startsWith("image/") || extension(file.name) === ".zip") return null;
    if (!l) return 100 * MB;
    return l.extensions.text.includes(extension(file.name)) ? l.text_bytes : l.document_bytes;
  }

  const upload = useMutation({
    mutationFn: async (picked: Picked[]) => {
      const result: ImportResult = { imported: [], skipped: [] };
      const single = picked.length === 1;
      setProgress({ done: 0, total: picked.length });
      for (const [i, p] of picked.entries()) {
        try {
          const form = new FormData();
          form.set("course_id", chosen);
          form.set("category", category);
          if (folderId) form.set("folder_id", folderId);
          if (extension(p.file.name) === ".zip") {
            form.set("file", p.file);
            const r = await request<ImportResult>("/sources/zip", { form });
            result.imported.push(...r.imported);
            result.skipped.push(...r.skipped);
          } else {
            const limit = limitFor(p.file);
            const label = p.dir ? `${p.dir}/${p.file.name}` : p.file.name;
            if (!allowed.has(extension(p.file.name))) {
              result.skipped.push({ name: label, reason: "this type of file is not supported" });
              continue;
            }
            if (limit !== null && p.file.size > limit) {
              result.skipped.push({ name: label, reason: `larger than ${bytes(limit)}` });
              continue;
            }
            if (p.dir) form.set("folder_path", p.dir);
            form.set("file", await shrinkImage(p.file));
            result.imported.push(await request<Source>("/sources", { form }));
          }
        } catch (e) {
          if (single || !(e instanceof ApiError) || e.status === 0 || e.status === 401) throw e;
          result.skipped.push({ name: p.dir ? `${p.dir}/${p.file.name}` : p.file.name, reason: e.message });
        } finally {
          setProgress({ done: i + 1, total: picked.length });
        }
      }
      return result;
    },
    onSettled: () => {
      setProgress(null);
      for (const key of ["sources", "folders", "courses", "dashboard", "upload-limits"]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    },
    onSuccess: (result) => {
      setDone(result);
      onImported?.(result);
    },
  });

  function send(all: Picked[]) {
    setLocalError(null);
    setDone(null);
    const picked = all.filter((p) => !isJunk(p));
    if (!picked.length) return;
    if (picked.length > MAX_FOLDER_FILES) {
      setLocalError(`That is more than ${MAX_FOLDER_FILES} files. Put the folder into a ZIP and upload the ZIP instead.`);
      return;
    }
    const first = picked[0]!;
    const limit = limitFor(first.file);
    if (picked.length === 1 && limit !== null && first.file.size > limit) {
      setLocalError(
        `${first.file.name} is ${bytes(first.file.size)}; the limit for this type of file is ${bytes(limit)}. ` +
          "Split it, or compress the PDF (scans and pictures make files large; the text stays small).",
      );
      return;
    }
    if (!chosen) {
      setLocalError("Create a course first: ask your assistant in a planning chat (see the Guide).");
      return;
    }
    upload.mutate(picked);
  }

  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    void fromDrop(e.dataTransfer).then(send, () => send(Array.from(e.dataTransfer.files).map((file) => ({ file, dir: null }))));
  }

  const shown = done?.imported.slice(0, 8) ?? [];
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
        <strong style={{ color: "var(--ink)" }}>Drop lecture files, notes, photos, a whole folder or a ZIP here</strong>
        <span className="small">
          PDF, Word, PowerPoint, Excel, OpenDocument, Markdown, text, CSV, subtitles (.srt, .vtt), notebooks (.ipynb),
          LaTeX, code, or photos. Up to {bytes(limits.data?.document_bytes ?? 100 * MB)} per document and{" "}
          {bytes(limits.data?.text_bytes ?? 10 * MB)} per text file; large photos are shrunk so your assistant can look at them.
          Folders inside a folder or ZIP become library folders.
        </span>
        <div className="row" style={{ gap: 8, justifyContent: "center" }}>
          <button type="button" className="btn small" onClick={() => input.current?.click()} disabled={upload.isPending}>
            Choose files
          </button>
          <button type="button" className="btn small ghost" onClick={() => folderInput.current?.click()} disabled={upload.isPending}>
            Choose a folder
          </button>
        </div>
        {progress && (
          <span className="small" role="status">
            Uploading {progress.done + (progress.done < progress.total ? 1 : 0)} of {progress.total}…
          </span>
        )}
        <input
          ref={input}
          type="file"
          accept={accept}
          multiple
          hidden
          onChange={(e) => {
            send(fromInput(e.target.files));
            e.target.value = "";
          }}
        />
        <input
          ref={folderInput}
          type="file"
          multiple
          hidden
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          onChange={(e) => {
            send(fromInput(e.target.files));
            e.target.value = "";
          }}
        />
      </div>
      {limits.data && (
        <span className="small muted">
          Library: {bytes(limits.data.library_used_bytes)} of {bytes(limits.data.library_bytes)} used.
          {!limits.data.page_renderer_available &&
            " With LibreOffice installed on the RecallSpring computer, your assistant can also look at whole slides and Word pages."}
        </span>
      )}
      {localError && <div className="notice warn">{localError}</div>}
      {upload.error && <ErrorNote error={upload.error} />}
      {done && !upload.isPending && <ImportSummary result={done} shown={shown} />}
    </div>
  );
}

/** What an upload or import added, and what it left out with the reason. */
export function ImportSummary({ result, shown }: { result: ImportResult; shown?: Source[] }) {
  const list = shown ?? result.imported.slice(0, 8);
  const more = result.imported.length - list.length;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {result.imported.length > 0 && (
        <div className="notice small" role="status">
          Added {list.map((s) => (s.folder ? `${s.folder} / ${s.filename}` : s.filename)).join(", ")}
          {more > 0 ? ` and ${more} more` : ""}.
          {result.imported.some((s) => s.duplicate_of_id) && " Some files were already in your library; RecallSpring kept one copy."}{" "}
          Text extraction runs in the background.
        </div>
      )}
      {result.imported.length === 0 && result.skipped.length > 0 && (
        <div className="notice small" role="status">
          Nothing new was added.
        </div>
      )}
      {result.skipped.length > 0 && (
        <details className="notice warn small">
          <summary>
            {result.skipped.length} {result.skipped.length === 1 ? "file was" : "files were"} left out
          </summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {result.skipped.slice(0, 100).map((s, i) => (
              <li key={i} style={{ overflowWrap: "anywhere" }}>
                {s.name}: {s.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
