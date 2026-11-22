import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { request } from "../api";
import { addDays, dateLabel, todayIso } from "../format";
import { ORGANISATION_KEYS, useGroups } from "../queries";
import type { CourseColor, CourseInfo, Group } from "../types";
import { DeleteCourseDialog } from "./CourseForms";
import { ErrorNote, Modal } from "./ui";

export const COLORS: { id: CourseColor; label: string }[] = [
  { id: "blue", label: "Blue" },
  { id: "orange", label: "Orange" },
  { id: "aqua", label: "Aqua" },
  { id: "yellow", label: "Yellow" },
  { id: "magenta", label: "Magenta" },
  { id: "green", label: "Green" },
  { id: "violet", label: "Violet" },
  { id: "red", label: "Red" },
];

export const KIND_LABEL: Record<Group["kind"], string> = {
  university: "University",
  faculty: "Faculty",
  semester: "Semester",
  other: "Group",
};

export function cc(color: CourseColor | null | undefined): string {
  return color ? `cc-${color}` : "";
}

export function CourseDot({ color }: { color: CourseColor | null | undefined }) {
  return <span className={`course-dot ${cc(color)}`} aria-hidden="true" />;
}

export function useInvalidateOrganisation() {
  const qc = useQueryClient();
  return () => ORGANISATION_KEYS.forEach((key) => void qc.invalidateQueries({ queryKey: [...key] }));
}

export function ColorPicker({ value, onChange }: { value: CourseColor | null; onChange: (c: CourseColor | null) => void }) {
  return (
    <div className="swatches" role="radiogroup" aria-label="Course colour">
      <button type="button" role="radio" aria-checked={value === null} aria-label="No colour" title="No colour" className="swatch none" onClick={() => onChange(null)} />
      {COLORS.map((c) => (
        <button
          key={c.id}
          type="button"
          role="radio"
          aria-checked={value === c.id}
          aria-label={c.label}
          title={c.label}
          className={`swatch ${cc(c.id)}`}
          onClick={() => onChange(c.id)}
        />
      ))}
    </div>
  );
}

/** "University › Faculty › Semester" for a group id. */
export function groupPath(groups: Group[] | undefined, id: string | null): string {
  const byId = new Map((groups ?? []).map((g) => [g.id, g]));
  const names: string[] = [];
  let current = id ? byId.get(id) : undefined;
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    names.unshift(current.name);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return names.join(" › ");
}

function descendants(groups: Group[], id: string): Set<string> {
  const out = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const g of groups) {
      if (g.parent_id && out.has(g.parent_id) && !out.has(g.id)) {
        out.add(g.id);
        grew = true;
      }
    }
  }
  return out;
}

function GroupSelect({ value, onChange, groups, exclude, label, emptyLabel }: {
  value: string;
  onChange: (id: string) => void;
  groups: Group[];
  exclude?: Set<string>;
  label: string;
  emptyLabel: string;
}) {
  const options = groups
    .filter((g) => !exclude?.has(g.id))
    .map((g) => ({ id: g.id, path: groupPath(groups, g.id), archived: g.status === "archived" }))
    .sort((a, b) => a.path.localeCompare(b.path));
  return (
    <label className="field">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{emptyLabel}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.path}
            {o.archived ? " (archived)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

export function CourseDialog({ course, open, onClose }: { course: CourseInfo; open: boolean; onClose: () => void }) {
  const groups = useGroups();
  const refresh = useInvalidateOrganisation();
  const [title, setTitle] = useState(course.title);
  const [color, setColor] = useState<CourseColor | null>(course.color);
  const [groupId, setGroupId] = useState(course.group_id ?? "");
  const [retain, setRetain] = useState(course.long_term_retention);
  const [archived, setArchived] = useState(course.status === "archived");
  const [kind, setKind] = useState<CourseInfo["kind"]>(course.kind);
  const [goal, setGoal] = useState(course.description ?? "");
  const [deleting, setDeleting] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      if (title.trim() !== course.title) body.title = title.trim();
      if (color !== course.color) body.color = color;
      if (kind !== course.kind) body.kind = kind;
      if (kind === "interest" && goal.trim() !== (course.description ?? "")) body.description = goal.trim() || null;
      if (kind === "course" && (groupId || null) !== course.group_id) body.group_id = groupId || null;
      if (retain !== course.long_term_retention) body.long_term_retention = retain;
      if (archived !== (course.status === "archived")) body.archived = archived;
      return request<CourseInfo>(`/courses/${course.id}`, { method: "PATCH", json: body });
    },
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  if (deleting) return <DeleteCourseDialog course={course} open={open} onClose={onClose} />;
  return (
    <Modal open={open} title={kind === "interest" ? "Edit interest" : "Edit course"} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label className="field">
          Title
          <input type="text" value={title} maxLength={200} required onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as CourseInfo["kind"])}>
            <option value="course">University course: planned by its exams</option>
            <option value="interest">Personal interest: no exam, no deadline</option>
          </select>
          {kind === "interest" && course.kind === "course" && (
            <span className="hint">
              It leaves its semester. Upcoming exams need a result, or must be cancelled or deleted first.
            </span>
          )}
        </label>
        {kind === "interest" && (
          <label className="field">
            Goal
            <span className="hint">What you want to be able to do, in your own words. Your assistant teaches toward it.</span>
            <textarea rows={3} maxLength={5000} value={goal} onChange={(e) => setGoal(e.target.value)} />
          </label>
        )}
        <div className="field">
          Colour
          <span className="hint">Marks this course on the exam timeline and in lists, always next to its name.</span>
          <ColorPicker value={color} onChange={setColor} />
        </div>
        {kind === "course" && (
          <GroupSelect
            label="Semester"
            emptyLabel="Not filed in a semester"
            value={groupId}
            onChange={setGroupId}
            groups={groups.data ?? []}
          />
        )}
        <label className="row small">
          <input type="checkbox" checked={retain} onChange={(e) => setRetain(e.target.checked)} />
          Keep reviewing it after the course ends (long-term memory)
        </label>
        <label className="row small">
          <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
          Archived: hidden from today's plan{retain ? "; due reviews stay as maintenance" : ""}
        </label>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn ghost danger-text" style={{ marginRight: "auto" }} onClick={() => setDeleting(true)}>
            Delete {course.kind === "interest" ? "interest" : "course"}…
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={save.isPending}>
            Save
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** A personal interest: something learned in free time, without an exam or deadline. */
export function NewInterestDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const refresh = useInvalidateOrganisation();
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const save = useMutation({
    mutationFn: () =>
      request<CourseInfo>("/courses", {
        method: "POST",
        json: { title: title.trim(), kind: "interest", description: goal.trim() || null },
      }),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  return (
    <Modal open={open} title="New interest" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="small muted">
          Something you learn in your free time, without an exam or deadline: data analysis, machine learning, a
          language. Your courses come first unless you choose otherwise in Settings.
        </p>
        <label className="field">
          Name
          <input
            type="text"
            required
            maxLength={200}
            value={title}
            placeholder="e.g. Data analysis"
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label className="field">
          Goal
          <span className="hint">What you want to be able to do. You can also leave it empty and your assistant asks.</span>
          <textarea rows={3} maxLength={5000} value={goal} onChange={(e) => setGoal(e.target.value)} />
        </label>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={save.isPending || !title.trim()}>
            Add interest
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function isFocused(course: Pick<CourseInfo, "focus_until">): boolean {
  return !!course.focus_until && course.focus_until >= todayIso();
}

/** Put one course or interest first in the plan until a day, or end that focus. */
export function FocusControl({ course }: { course: Pick<CourseInfo, "id" | "title" | "status" | "focus_until"> }) {
  const qc = useQueryClient();
  const today = todayIso();
  const [open, setOpen] = useState(false);
  const [until, setUntil] = useState(addDays(today, 6));
  const save = useMutation({
    mutationFn: (courseId: string | null) =>
      request<unknown>("/settings/focus", { method: "PUT", json: { course_id: courseId, until: courseId ? until : null } }),
    onSuccess: () => {
      setOpen(false);
      for (const key of [["courses"], ["dashboard"], ["settings"]]) void qc.invalidateQueries({ queryKey: key });
    },
  });
  if (course.status === "archived") return null;
  if (isFocused(course)) {
    return (
      <span className="row small" style={{ gap: 8 }}>
        <span className="chip solid">Focus until {dateLabel(course.focus_until ?? today)}</span>
        <button type="button" className="btn small" onClick={() => save.mutate(null)} disabled={save.isPending}>
          End focus
        </button>
        {save.error && <ErrorNote error={save.error} />}
      </span>
    );
  }
  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        Focus on this
      </button>
      <Modal open={open} title={`Focus on ${course.title}`} onClose={() => setOpen(false)}>
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(course.id);
          }}
        >
          <p className="small">
            It comes first in your plan until the day you choose; other courses and interests get the time that is
            left. Today shows any exam that becomes tight or at risk because of it. There is one focus at a time, so
            this replaces any other.
          </p>
          <label className="field">
            Until
            <input
              type="date"
              required
              min={today}
              max={addDays(today, 60)}
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
          {save.error && <ErrorNote error={save.error} />}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={save.isPending}>
              Focus
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}

export function GroupDialog({ group, parentId, open, onClose }: {
  group?: Group;
  parentId?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const groups = useGroups();
  const refresh = useInvalidateOrganisation();
  const [kind, setKind] = useState<Group["kind"]>(group?.kind ?? (parentId ? "semester" : "university"));
  const [name, setName] = useState(group?.name ?? "");
  const [parent, setParent] = useState(group?.parent_id ?? parentId ?? "");
  const [startsOn, setStartsOn] = useState(group?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(group?.ends_on ?? "");
  const save = useMutation({
    mutationFn: () => {
      const body = {
        kind,
        name: name.trim(),
        parent_id: parent || null,
        starts_on: startsOn || null,
        ends_on: endsOn || null,
      };
      return group
        ? request<Group>(`/groups/${group.id}`, { method: "PATCH", json: body })
        : request<Group>("/groups", { method: "POST", json: body });
    },
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  const exclude = group ? descendants(groups.data ?? [], group.id) : undefined;
  return (
    <Modal open={open} title={group ? `Edit ${KIND_LABEL[group.kind].toLowerCase()}` : "New group"} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid cols-2" style={{ gap: 12 }}>
          <label className="field">
            Level
            <select value={kind} onChange={(e) => setKind(e.target.value as Group["kind"])}>
              <option value="university">University</option>
              <option value="faculty">Faculty</option>
              <option value="semester">Semester</option>
              <option value="other">Other group</option>
            </select>
          </label>
          <label className="field">
            Name
            <input type="text" value={name} maxLength={200} required placeholder={kind === "semester" ? "5th semester" : ""} onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
        <GroupSelect label="Inside" emptyLabel="Top level" value={parent} onChange={setParent} groups={groups.data ?? []} exclude={exclude} />
        <div className="grid cols-2" style={{ gap: 12 }}>
          <label className="field">
            Starts
            <input type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} />
          </label>
          <label className="field">
            Ends
            <input type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
          </label>
        </div>
        {save.error && <ErrorNote error={save.error} />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={save.isPending || !name.trim()}>
            {group ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
