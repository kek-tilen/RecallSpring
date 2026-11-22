import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { request } from "../api";
import { dateLabel } from "../format";
import { useGroups } from "../queries";
import type { CourseColor, CourseInfo } from "../types";
import { ColorPicker, CourseDot, groupPath, useInvalidateOrganisation } from "./organise";
import { Async, ErrorNote, Modal } from "./ui";

type Contents = {
  title: string;
  counts: Record<
    | "materials"
    | "folders"
    | "concepts"
    | "notes"
    | "exams"
    | "simulations"
    | "questions"
    | "answers"
    | "conversations"
    | "focus_blocks",
    number
  >;
  restorable_days: number;
};

type DeletedCourse = CourseInfo & { deleted_at: string | null };

const deletedKey = ["courses", "deleted"] as const;

/** A university course (planned by its exams) or a personal interest, created by hand. */
export function NewCourseDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const groups = useGroups();
  const refresh = useInvalidateOrganisation();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<CourseInfo["kind"]>("course");
  const [goal, setGoal] = useState("");
  const [color, setColor] = useState<CourseColor | null>(null);
  const [groupId, setGroupId] = useState("");
  const [retain, setRetain] = useState(true);
  const save = useMutation({
    mutationFn: async () => {
      const created = await request<CourseInfo>("/courses", {
        method: "POST",
        json: {
          title: title.trim(),
          kind,
          long_term_retention: retain,
          description: kind === "interest" ? goal.trim() || null : null,
        },
      });
      const extra: Record<string, unknown> = {};
      if (color) extra.color = color;
      if (kind === "course" && groupId) extra.group_id = groupId;
      if (Object.keys(extra).length === 0) return created;
      return request<CourseInfo>(`/courses/${created.id}`, { method: "PATCH", json: extra });
    },
    onSuccess: (course) => {
      refresh();
      onClose();
      navigate(`/courses/${course.id}`);
    },
  });
  const all = groups.data ?? [];
  return (
    <Modal open={open} title="New course" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <label className="field">
          Name
          <input
            type="text"
            required
            maxLength={200}
            value={title}
            placeholder="e.g. Digital forensics"
            onChange={(e) => setTitle(e.target.value)}
          />
          <span className="hint">Any language; it is shown exactly as you type it.</span>
        </label>
        <label className="field">
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as CourseInfo["kind"])}>
            <option value="course">University course: planned by its exams</option>
            <option value="interest">Personal interest: no exam, no deadline</option>
          </select>
        </label>
        {kind === "interest" && (
          <label className="field">
            Goal
            <span className="hint">What you want to be able to do. You can leave it empty and your assistant asks.</span>
            <textarea rows={3} maxLength={5000} value={goal} onChange={(e) => setGoal(e.target.value)} />
          </label>
        )}
        {kind === "course" && all.length > 0 && (
          <label className="field">
            Semester
            <select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
              <option value="">Not filed in a semester</option>
              {all
                .filter((g) => g.status === "active")
                .map((g) => (
                  <option key={g.id} value={g.id}>
                    {groupPath(all, g.id)}
                  </option>
                ))}
            </select>
          </label>
        )}
        <div className="field">
          Colour
          <span className="hint">Optional. Marks the course on the exam timeline and in lists.</span>
          <ColorPicker value={color} onChange={setColor} />
        </div>
        <label className="row small">
          <input type="checkbox" checked={retain} onChange={(e) => setRetain(e.target.checked)} />
          Keep reviewing it after the course ends (long-term memory)
        </label>
        <p className="small muted">
          Add material, exams and midterms on the course page, or let your assistant set them up in a planning chat.
        </p>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={save.isPending || !title.trim()}>
            Create {kind === "interest" ? "interest" : "course"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const LINES: [keyof Contents["counts"], string, string][] = [
  ["materials", "material", "materials"],
  ["folders", "folder", "folders"],
  ["concepts", "concept", "concepts"],
  ["notes", "note", "notes"],
  ["exams", "exam or midterm", "exams and midterms"],
  ["simulations", "simulation", "simulations"],
  ["questions", "question", "questions"],
  ["answers", "answer with its grades", "answers with their grades"],
  ["conversations", "Chat conversation", "Chat conversations"],
  ["focus_blocks", "focus block", "focus blocks"],
];

/**
 * Deleting a whole course. The learner must tick "I understand" and type the course name exactly; until both are
 * true the Delete button stays disabled. The server checks the name again and keeps everything restorable 30 days.
 */
export function DeleteCourseDialog({ course, open, onClose }: {
  course: Pick<CourseInfo, "id" | "title" | "kind">;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [understood, setUnderstood] = useState(false);
  const [typed, setTyped] = useState("");
  const contents = useQuery({
    queryKey: ["courses", course.id, "contents"],
    queryFn: () => request<Contents>(`/courses/${course.id}/contents`),
    enabled: open,
  });
  const matches = typed === course.title;
  const remove = useMutation({
    mutationFn: () => request(`/courses/${course.id}`, { method: "DELETE", json: { confirm_title: typed } }),
    onSuccess: () => {
      void qc.invalidateQueries(); // notes, material, reviews, simulations… all lose this course
      onClose();
      navigate("/courses");
    },
  });
  const noun = course.kind === "interest" ? "interest" : "course";
  return (
    <Modal open={open} title={`Delete ${course.title}?`} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (understood && matches) remove.mutate();
        }}
      >
        <div className="notice bad">
          <strong>Everything in this {noun} will be deleted:</strong>
          <Async q={contents} lines={3}>
            {(c) => {
              const shown = LINES.filter(([k]) => c.counts[k] > 0);
              return shown.length ? (
                <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 20 }} aria-label="What will be deleted">
                  {shown.map(([k, one, many]) => (
                    <li key={k}>
                      {c.counts[k]} {c.counts[k] === 1 ? one : many}
                    </li>
                  ))}
                  <li>its review schedule and progress</li>
                </ul>
              ) : (
                <p className="small" style={{ margin: "6px 0 0" }}>
                  It is empty: only the {noun} itself.
                </p>
              );
            }}
          </Async>
        </div>
        <p className="small muted">
          It disappears from every page, your plan and your assistants. You can restore it with everything in it for{" "}
          {contents.data?.restorable_days ?? 30} days under <strong>Courses → Recently deleted</strong>; after that it
          stays only in your backups.
        </p>
        <label className="row small">
          <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
          I understand that everything in this {noun} will be deleted.
        </label>
        <label className="field">
          Type the {noun} name to confirm: <strong className="course-name-to-type">{course.title}</strong>
          <textarea
            rows={2}
            value={typed}
            disabled={!understood}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={typed.length > 0 && !matches}
            onChange={(e) => setTyped(e.target.value)}
          />
          <span className="hint" aria-live="polite">
            {!understood
              ? "Tick the box above first."
              : matches
                ? "The name matches."
                : "It must match exactly, including capital letters, spaces and accents."}
          </span>
        </label>
        {remove.error && <ErrorNote error={remove.error} />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn danger" disabled={!understood || !matches || remove.isPending}>
            Delete {noun}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Courses deleted in the last 30 days, with Restore. Renders nothing when there are none. */
export function RecentlyDeletedCourses() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: deletedKey, queryFn: () => request<DeletedCourse[]>("/courses/deleted") });
  const restore = useMutation({
    mutationFn: (id: string) => request<CourseInfo>(`/courses/${id}/restore`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries(),
  });
  if (!q.data?.length) return null;
  return (
    <section id="recently-deleted" className="group" aria-label="Recently deleted" style={{ marginTop: 28 }}>
      <div className="group-head">
        <h2>
          <span className="kind">Recently deleted</span>
          Restorable for 30 days
        </h2>
      </div>
      {restore.error && <ErrorNote error={restore.error} />}
      <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {q.data.map((c) => (
          <li key={c.id} className="card row" style={{ justifyContent: "space-between" }}>
            <span className="row" style={{ gap: 8, minWidth: 0, overflowWrap: "anywhere" }}>
              <CourseDot color={c.color} />
              <strong>{c.title}</strong>
              {c.deleted_at && <span className="small muted">deleted {dateLabel(c.deleted_at.slice(0, 10))}</span>}
            </span>
            <button
              type="button"
              className="btn small"
              disabled={restore.isPending}
              onClick={() => restore.mutate(c.id)}
              aria-label={`Restore ${c.title}`}
            >
              Restore
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
