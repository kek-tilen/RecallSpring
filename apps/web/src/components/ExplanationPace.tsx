import { useMutation, useQueryClient } from "@tanstack/react-query";
import { request } from "../api";
import { useSaveProfile } from "../pages/Welcome";
import { keys, useCourses, useSession } from "../queries";
import type { ExplanationPace } from "../types";
import { ErrorNote } from "./ui";

/**
 * Explanation pace (owner notes 2026-11-26, part D; migration 0035): how assistants explain new material. A default
 * in Settings, a course may choose its own. A request in a chat holds for that conversation; the assistant offers to
 * save it. Every pace explains completely; only the size of each part changes.
 */
export const PACES: { value: ExplanationPace; label: string; hint: string }[] = [
  { value: "step", label: "Step by step", hint: "One small part at a time, with a quick check before the next." },
  { value: "balanced", label: "Balanced", hint: "One section at a time with its examples, then a short check." },
  { value: "chunks", label: "Larger chunks", hint: "A whole topic in one go, then your questions and the checks." },
  { value: "auto", label: "Auto", hint: "Your assistant adapts: smaller steps for new or hard material, larger for familiar." },
];
const DEFAULT = "default";
const label = (p: ExplanationPace) => PACES.find((x) => x.value === p)?.label ?? p;
const hint = (p: ExplanationPace) => PACES.find((x) => x.value === p)?.hint ?? "";

/** Settings: the default for every course. */
export function ExplanationPaceDefault() {
  const user = useSession().data?.user;
  const save = useSaveProfile();
  if (!user) return null;
  const pace = user.explanation_pace ?? "auto";
  return (
    <div className="stack" style={{ gap: 8 }}>
      <label className="field">
        How your assistant explains new material
        <select
          value={pace}
          disabled={save.isPending}
          onChange={(e) => save.mutate({ explanation_pace: e.target.value as ExplanationPace })}
          aria-describedby="pace-default-hint"
        >
          {PACES.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <span id="pace-default-hint" className="hint">
          {hint(pace)} Every pace explains completely; only the size of each part changes. A course can choose its own on its page,
          and in a chat you can ask for another pace for that conversation.
        </span>
      </label>
      {save.error && <ErrorNote error={save.error} />}
    </div>
  );
}

/** Course page: this course's own pace, or the default. */
export function ExplanationPaceControl({ courseId }: { courseId: string }) {
  const qc = useQueryClient();
  const courses = useCourses();
  const user = useSession().data?.user;
  const own = courses.data?.find((c) => c.id === courseId)?.explanation_pace ?? null;
  const fallback = user?.explanation_pace ?? "auto";
  const save = useMutation({
    mutationFn: (pace: ExplanationPace | null) => request(`/courses/${courseId}/explanation-pace`, { method: "PUT", json: { pace } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.courses }),
  });
  return (
    <div className="stack" style={{ gap: 4 }}>
      <label className="row small" style={{ gap: 8, flexWrap: "wrap" }}>
        <span>Explanations</span>
        <select
          style={{ width: "auto" }}
          value={own ?? DEFAULT}
          disabled={save.isPending || !courses.data}
          onChange={(e) => save.mutate(e.target.value === DEFAULT ? null : (e.target.value as ExplanationPace))}
          aria-describedby="pace-course-hint"
        >
          <option value={DEFAULT}>Default ({label(fallback)})</option>
          {PACES.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      <span id="pace-course-hint" className="tiny muted">
        {hint(own ?? fallback)} The default is set in Settings.
      </span>
      {save.error && <ErrorNote error={save.error} />}
    </div>
  );
}
