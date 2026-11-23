/** Chat folders (ADR-012 §4): folders with one level of subfolders, an icon from a fixed set and a colour. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { request } from "../api";
import { useCourses } from "../queries";
import { Confirm, ErrorNote, Modal } from "./ui";

export interface ChatFolder {
  id: string;
  parent_id: string | null;
  name: string;
  icon: string;
  color: string | null;
  course: { id: string; title: string } | null;
  pinned: boolean;
  conversations: number;
}

/** Each icon as stroke paths on a 24×24 grid (the server accepts only these names). */
const PATHS: Record<string, string[]> = {
  folder: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
  book: ["M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z", "M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3", "M9 7h6"],
  school: ["M2 9l10-5 10 5-10 5z", "M6 11v5c3 2.5 9 2.5 12 0v-5", "M22 9v6"],
  flask: ["M9 3h6", "M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3", "M7.5 15h9"],
  function: ["M9 20c2 0 2.4-2 3-6l1-5c.6-4 1-6 3-6", "M8 10h8"],
  code: ["M8 8l-4 4 4 4", "M16 8l4 4-4 4", "M14 5l-4 14"],
  shield: ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"],
  globe: ["M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z", "M3 12h18", "M12 3c3 3 3 15 0 18", "M12 3c-3 3-3 15 0 18"],
  language: ["M4 5h8", "M8 3v2", "M6 5c0 4 2.5 6.5 6 8", "M10 5c0 4-2.5 6.5-6 8", "M13 21l4-9 4 9", "M14.5 18h5"],
  palette: [
    "M12 3a9 9 0 1 0 0 18c1 0 1.5-.7 1.5-1.4 0-1-1-1.6-1-2.6 0-.9.8-1.5 1.8-1.5H17a4 4 0 0 0 4-4C21 6.8 17 3 12 3z",
    "M7.5 11h.01",
    "M10.5 7h.01",
    "M15 7.5h.01",
  ],
  scale: ["M12 3v18", "M7 21h10", "M5 7h14", "M5 7l-3 6a3 3 0 0 0 6 0z", "M19 7l-3 6a3 3 0 0 0 6 0z"],
  heart: ["M20.8 8.6a5 5 0 0 0-8.8-3.2 5 5 0 0 0-8.8 3.2c0 5.4 8.8 11.4 8.8 11.4s8.8-6 8.8-11.4z"],
  bulb: ["M9 18h6", "M10 21h4", "M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"],
  calendar: ["M4 6h16v14H4z", "M4 10h16", "M8 3v4", "M16 3v4"],
  star: ["M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3l-5.5 2.9 1-6.2L3 9.6l6.2-.9z"],
  chat: ["M4 5h16v11H9l-5 4z"],
};
export const FOLDER_ICONS = Object.keys(PATHS);

/** An accessible palette (white text and the light page both work with each); "Custom…" picks any colour. */
export const FOLDER_COLORS: { value: string; name: string }[] = [
  { value: "#5f5e5a", name: "Grey" },
  { value: "#0f6e56", name: "Teal" },
  { value: "#185fa5", name: "Blue" },
  { value: "#534ab7", name: "Violet" },
  { value: "#993556", name: "Rose" },
  { value: "#a32d2d", name: "Red" },
  { value: "#854f0b", name: "Amber" },
  { value: "#3b6d11", name: "Green" },
];

export function FolderIcon({ icon, color, size = 18 }: { icon: string; color?: string | null; size?: number }) {
  const paths = PATHS[icon] ?? PATHS.folder ?? [];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      // The learner's colour goes through CSS, which lightens it on dark themes (styles.css, --folder-lift).
      className={color ? "chat-folder-icon tinted" : "chat-folder-icon"}
      style={color ? ({ "--fc": color } as CSSProperties) : undefined}
    >
      {paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

export interface FolderList {
  folders: ChatFolder[];
}

/** Create a folder (``parentId`` for a subfolder) or edit one; editing also offers Delete. */
export function FolderDialog<L extends FolderList>({
  open,
  folder,
  parentId,
  folders,
  onClose,
  onSaved,
}: {
  open: boolean;
  folder: ChatFolder | null;
  parentId?: string | null;
  folders: ChatFolder[];
  onClose: () => void;
  onSaved: (list: L) => void;
}) {
  const courses = useCourses();
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("folder");
  const [color, setColor] = useState<string | null>(null);
  const [course, setCourse] = useState("");
  const [pinned, setPinned] = useState(false);
  const [parent, setParent] = useState("");
  const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    if (!open) return;
    setName(folder?.name ?? "");
    setIcon(folder?.icon ?? "folder");
    setColor(folder?.color ?? null);
    setCourse(folder?.course?.id ?? "");
    setPinned(folder?.pinned ?? false);
    setParent(folder ? (folder.parent_id ?? "") : (parentId ?? ""));
    setConfirming(false);
  }, [open, folder, parentId]);

  const hasChildren = !!folder && folders.some((f) => f.parent_id === folder.id);
  // A subfolder goes only under a top-level folder; a folder with subfolders stays at the top level.
  const parents = folders.filter((f) => f.parent_id === null && f.id !== folder?.id);
  const save = useMutation({
    mutationFn: () => {
      const json = {
        name: name.trim(),
        icon,
        color,
        course_id: course || null,
        pinned,
        parent_id: parent || null,
      };
      return folder
        ? request<L>(`/ai/chatgpt/folders/${folder.id}`, { method: "PATCH", json })
        : request<L>("/ai/chatgpt/folders", { method: "POST", json });
    },
    onSuccess: (l) => {
      onSaved(l);
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => request<L>(`/ai/chatgpt/folders/${folder!.id}`, { method: "DELETE" }),
    onSuccess: (l) => {
      onSaved(l);
      setConfirming(false);
      onClose();
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) save.mutate();
  }
  const custom = color !== null && !FOLDER_COLORS.some((c) => c.value === color);
  const parentName = folder?.parent_id ? folders.find((f) => f.id === folder.parent_id)?.name : null;
  return (
    <>
      <Modal
        open={open && !confirming}
        title={folder ? "Folder settings" : parentId ? "New subfolder" : "New folder"}
        onClose={onClose}
      >
        <form className="stack folder-form" onSubmit={submit}>
          <label className="field">
            <span>Name</span>
            <input type="text" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} autoFocus required />
          </label>
          <fieldset className="folder-choice">
            <legend>Icon</legend>
            <div className="folder-icons" role="radiogroup" aria-label="Icon">
              {FOLDER_ICONS.map((i) => (
                <button
                  key={i}
                  type="button"
                  role="radio"
                  aria-checked={icon === i}
                  aria-label={i}
                  title={i}
                  className={icon === i ? "folder-icon-pick on" : "folder-icon-pick"}
                  onClick={() => setIcon(i)}
                >
                  <FolderIcon icon={i} color={color} size={20} />
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="folder-choice">
            <legend>Colour</legend>
            <div className="folder-colors" role="radiogroup" aria-label="Colour">
              <button
                type="button"
                role="radio"
                aria-checked={color === null}
                className={color === null ? "folder-swatch none on" : "folder-swatch none"}
                title="Default"
                aria-label="Default"
                onClick={() => setColor(null)}
              />
              {FOLDER_COLORS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  role="radio"
                  aria-checked={color === c.value}
                  aria-label={c.name}
                  title={c.name}
                  className={color === c.value ? "folder-swatch on" : "folder-swatch"}
                  style={{ "--fc": c.value } as CSSProperties}
                  onClick={() => setColor(c.value)}
                />
              ))}
              <label className={custom ? "folder-custom on" : "folder-custom"}>
                <input
                  type="color"
                  value={color ?? "#5f5e5a"}
                  onChange={(e) => setColor(e.target.value.toLowerCase())}
                  aria-label="Custom colour"
                />
                <span className="small">Custom…</span>
              </label>
            </div>
          </fieldset>
          <label className="field">
            <span>Course</span>
            <select value={course} onChange={(e) => setCourse(e.target.value)}>
              <option value="">No course</option>
              {(courses.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            <span className="tiny muted">
              A new conversation about this course goes into the folder when it is the only one linked to the course.
            </span>
          </label>
          {!hasChildren && parents.length > 0 && (
            <label className="field">
              <span>Inside</span>
              <select value={parent} onChange={(e) => setParent(e.target.value)}>
                <option value="">Top level</option>
                {parents.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="row small" style={{ gap: 8 }}>
            <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
            Pin to the top
          </label>
          {save.error && <ErrorNote error={save.error} />}
          <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
            {folder && (
              <button type="button" className="btn ghost" style={{ marginRight: "auto" }} onClick={() => setConfirming(true)}>
                Delete folder
              </button>
            )}
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={!name.trim() || save.isPending}>
              {folder ? "Save" : "Create"}
            </button>
          </div>
        </form>
      </Modal>
      {folder && (
        <Confirm
          open={open && confirming}
          title={`Delete “${folder.name}”?`}
          confirmLabel="Delete folder"
          danger
          busy={remove.isPending}
          onConfirm={() => remove.mutate()}
          onClose={() => setConfirming(false)}
        >
          <p>
            No conversation is deleted.{" "}
            {folder.conversations > 0 &&
              `Its ${folder.conversations === 1 ? "conversation moves" : `${folder.conversations} conversations move`} to ${
                parentName ? `“${parentName}”` : "No folder"
              }. `}
            {hasChildren && "Its subfolders move to the top level."}
          </p>
          {remove.error && <ErrorNote error={remove.error} />}
        </Confirm>
      )}
    </>
  );
}

/** "Move to…": a folder or subfolder, or No folder. */
export function MoveDialog<L extends FolderList>({
  open,
  conversationId,
  current,
  folders,
  onClose,
  onMoved,
}: {
  open: boolean;
  conversationId: string;
  current: string | null;
  folders: ChatFolder[];
  onClose: () => void;
  onMoved: (list: L) => void;
}) {
  const qc = useQueryClient();
  const [target, setTarget] = useState(current ?? "");
  useEffect(() => {
    if (open) setTarget(current ?? "");
  }, [open, current]);
  const move = useMutation({
    mutationFn: () =>
      request<L>(`/ai/chatgpt/conversations/${conversationId}/folder`, { method: "PUT", json: { folder_id: target || null } }),
    onSuccess: (l) => {
      onMoved(l);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(conversationId) });
      onClose();
    },
  });
  return (
    <Modal open={open} title="Move to…" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          move.mutate();
        }}
      >
        <div className="folder-targets" role="radiogroup" aria-label="Folder">
          <label className="folder-target">
            <input type="radio" name="move-to" checked={target === ""} onChange={() => setTarget("")} />
            <span>No folder</span>
          </label>
          {folders.map((f) => (
            <label key={f.id} className={f.parent_id ? "folder-target sub" : "folder-target"}>
              <input type="radio" name="move-to" checked={target === f.id} onChange={() => setTarget(f.id)} />
              <FolderIcon icon={f.icon} color={f.color} />
              <span>{f.name}</span>
            </label>
          ))}
        </div>
        {folders.length === 0 && <p className="small muted">No folders yet: create one with the folder button above the list.</p>}
        {move.error && <ErrorNote error={move.error} />}
        <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={move.isPending || target === (current ?? "")}>
            Move
          </button>
        </div>
      </form>
    </Modal>
  );
}
