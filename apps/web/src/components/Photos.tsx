import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { API, request } from "../api";
import { LIBRARY_KEYS } from "../queries";
import { shrinkImage } from "./Upload";

/** Photos of the learner's own work: saved first in the course Library, then linked to an answer or message. */
export const MAX_PHOTOS = 4;
export const ANSWER_FOLDER = "Answer photos";

export interface Photo {
  key: string;
  id: string | null; // the Library image once saved
  filename: string;
  preview: string;
  state: "saving" | "saved" | "failed";
  error?: string;
}

/** Image files in a paste or a drop (screenshots, photos); anything else is left to the page. */
export function imagesIn(data: DataTransfer | null): File[] {
  if (!data) return [];
  const files = [...data.files].filter((f) => f.type.startsWith("image/"));
  if (files.length) return files;
  return [...data.items].filter((i) => i.kind === "file" && i.type.startsWith("image/")).flatMap((i) => i.getAsFile() ?? []);
}

function named(file: File): File {
  if (file.name && file.name !== "image.png") return file;
  const d = new Date(); // local time, as the learner sees it
  const two = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}`;
  const ext = file.type === "image/jpeg" ? "jpg" : (file.type.split("/")[1] ?? "png");
  return new File([file], `pasted-${stamp}.${ext}`, { type: file.type });
}

/** Photos being added to one answer or message. ``courseId`` null: photos cannot be added (says why). */
export function usePhotos(courseId: string | null, folderPath: string | null) {
  const qc = useQueryClient();
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const urls = useRef<string[]>([]);
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);

  async function save(key: string, file: File) {
    try {
      const form = new FormData();
      form.set("course_id", courseId ?? "");
      form.set("category", "notes");
      if (folderPath) form.set("folder_path", folderPath);
      form.set("file", await shrinkImage(named(file)));
      const saved = await request<{ id: string; filename: string }>("/sources", { method: "POST", form });
      setPhotos((all) => all.map((p) => (p.key === key ? { ...p, id: saved.id, filename: saved.filename, state: "saved" } : p)));
      LIBRARY_KEYS.forEach((k) => void qc.invalidateQueries({ queryKey: [...k] }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Not saved.";
      setPhotos((all) => all.map((p) => (p.key === key ? { ...p, state: "failed", error: message } : p)));
    }
  }

  function add(files: File[]) {
    setNotice(null);
    if (!files.length) return;
    if (!courseId) {
      setNotice("Photos are saved in a course: choose a course to study first.");
      return;
    }
    const room = MAX_PHOTOS - photos.length;
    if (room <= 0) {
      setNotice(`At most ${MAX_PHOTOS} photos.`);
      return;
    }
    if (files.length > room) setNotice(`Only ${room} more photo${room === 1 ? "" : "s"} fit; the rest were left out.`);
    const added = files.slice(0, room).map((file) => {
      const preview = URL.createObjectURL(file);
      urls.current.push(preview);
      return { key: crypto.randomUUID(), id: null, filename: file.name || "pasted image", preview, state: "saving" as const, file };
    });
    setPhotos((all) => [...all, ...added.map(({ file: _f, ...p }) => p)]);
    added.forEach((p) => void save(p.key, p.file));
  }

  return {
    photos,
    notice,
    add,
    remove: (key: string) => setPhotos((all) => all.filter((p) => p.key !== key)),
    clear: () => setPhotos([]),
    ids: photos.flatMap((p) => (p.state === "saved" && p.id ? [p.id] : [])),
    saving: photos.some((p) => p.state === "saving"),
    /** Paste handler: takes images, leaves text to the field. */
    onPaste: (e: ClipboardEvent) => {
      const files = imagesIn(e.clipboardData);
      if (files.length) {
        e.preventDefault();
        add(files);
      }
    },
    /** Drop handlers for a whole form or card. */
    dropProps: {
      onDragOver: (e: DragEvent) => {
        if ([...e.dataTransfer.types].includes("Files")) e.preventDefault();
      },
      onDrop: (e: DragEvent) => {
        const files = imagesIn(e.dataTransfer);
        if (files.length) {
          e.preventDefault();
          add(files);
        }
      },
    },
  };
}

export type Photos = ReturnType<typeof usePhotos>;

/** Thumbnails of the photos added so far, each with a remove button. */
export function PhotoStrip({ photos, onRemove }: { photos: Photo[]; onRemove?: (key: string) => void }) {
  if (!photos.length) return null;
  return (
    <ul className="photo-strip" aria-label="Photos added">
      {photos.map((p, i) => (
        <li key={p.key} className={`photo-thumb is-${p.state}`}>
          <img src={p.preview} alt={`Photo ${i + 1}: ${p.filename}`} />
          <span className="photo-state tiny" role={p.state === "failed" ? "alert" : undefined}>
            {p.state === "saving" ? "Saving…" : p.state === "failed" ? (p.error ?? "Not saved") : "Saved"}
          </span>
          {onRemove && (
            <button type="button" className="photo-remove" aria-label={`Remove photo ${i + 1}`} onClick={() => onRemove(p.key)}>
              ×
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The optional "add a photo of your work" area of an answer form. */
export function AnswerPhotos({ photos }: { photos: Photos }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="photo-drop" {...photos.dropProps}>
      <PhotoStrip photos={photos.photos} onRemove={photos.remove} />
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <button type="button" className="btn small" onClick={() => input.current?.click()} disabled={photos.photos.length >= MAX_PHOTOS}>
          Add a photo
        </button>
        <span className="small muted">
          Solved it on paper? A photo of your work counts as your answer (optional). Paste it with Ctrl+V, drop it
          here or choose a file; you can also add a few words.
        </span>
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        multiple
        hidden
        onChange={(e) => {
          photos.add([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />
      {photos.notice && <p className="tiny muted" role="status" style={{ margin: 0 }}>{photos.notice}</p>}
    </div>
  );
}

/** Saved photos (of an answer or a message), opened full size in a new tab. */
export function SavedPhotos({ ids, label }: { ids: { id: string; filename?: string | null; available?: boolean }[]; label: string }) {
  if (!ids.length) return null;
  return (
    <ul className="photo-strip" aria-label={label}>
      {ids.map((p, i) =>
        p.available === false ? (
          <li key={p.id} className="photo-thumb is-failed">
            <span className="tiny muted">Photo {i + 1} was deleted</span>
          </li>
        ) : (
          <li key={p.id} className="photo-thumb">
            <a href={`${API}/sources/${p.id}/file`} target="_blank" rel="noreferrer">
              <img src={`${API}/sources/${p.id}/file`} alt={`Photo ${i + 1}${p.filename ? `: ${p.filename}` : ""}`} loading="lazy" />
            </a>
          </li>
        ),
      )}
    </ul>
  );
}
