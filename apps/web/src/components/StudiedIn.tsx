import { useMutation, useQueryClient } from "@tanstack/react-query";
import { request } from "../api";
import { ASSISTANTS } from "../assistant";
import { keys, useAssistants, useCourses } from "../queries";
import type { AssistantKey } from "../types";
import { ErrorNote } from "./ui";

const NAME: Record<AssistantKey, string> = { claude: "Claude Desktop", codex: "Codex", antigravity: "Antigravity", chatgpt: "ChatGPT" };
const ANY = "any";

/**
 * Course page: the assistant this course is usually studied in (2026-11-27), only when the learner uses more than one.
 * Wording only: Today's button and the tips name it; every connected assistant still works with every course.
 */
export function StudiedInControl({ courseId }: { courseId: string }) {
  const qc = useQueryClient();
  const courses = useCourses();
  const status = useAssistants();
  const own = courses.data?.find((c) => c.id === courseId)?.usually_studied_in ?? null;
  const save = useMutation({
    mutationFn: (assistant: AssistantKey | null) => request(`/courses/${courseId}/studied-in`, { method: "PUT", json: { assistant } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.courses }),
  });
  const s = status.data;
  if (!s) return null;
  // The assistants the learner uses: connected ones, the mix, or the single choice.
  const used = ASSISTANTS.map((a) => a.key).filter(
    (k) => s.items.some((i) => i.key === k && i.connected) || (s.mix ?? []).includes(k) || s.chosen === k,
  );
  if (used.length < 2 && !own) return null;
  const options = own && !used.includes(own) ? [...used, own] : used;
  return (
    <div className="stack" style={{ gap: 4 }}>
      <label className="row small" style={{ gap: 8, flexWrap: "wrap" }}>
        <span>Usually studied in</span>
        <select
          style={{ width: "auto" }}
          value={own ?? ANY}
          disabled={save.isPending || !courses.data}
          onChange={(e) => save.mutate(e.target.value === ANY ? null : (e.target.value as AssistantKey))}
          aria-describedby="studied-in-hint"
        >
          <option value={ANY}>Any</option>
          {options.map((k) => (
            <option key={k} value={k}>
              {NAME[k]}
            </option>
          ))}
        </select>
      </label>
      <span id="studied-in-hint" className="tiny muted">
        Today&apos;s button and the tips for this course name it. Every connected assistant still works with every course.
      </span>
      {save.error && <ErrorNote error={save.error} />}
    </div>
  );
}
