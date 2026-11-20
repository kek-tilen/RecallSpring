import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "../api";
import { dateLabel, dateTime, plural, relativeDay } from "../format";
import { useDeletedTargets } from "../queries";
import type { TimelineTarget } from "../types";
import { CourseDot, useInvalidateOrganisation } from "./organise";
import { Card, Confirm, ErrorNote } from "./ui";

const DISMISSED_KEY = "rs-not-duplicates";

function readDismissed(): string[] {
  try {
    return JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

/** Groups of exams that look like the same one (same course; same name, or same type and date). */
export function duplicateGroups(targets: TimelineTarget[]): TimelineTarget[][] {
  const byId = new Map(targets.map((t) => [t.id, t]));
  const seen = new Set<string>();
  const groups: TimelineTarget[][] = [];
  for (const t of targets) {
    if (!t.duplicates.length || seen.has(t.id)) continue;
    const group = [t, ...t.duplicates.map((id) => byId.get(id)).filter((x): x is TimelineTarget => Boolean(x))];
    group.forEach((g) => seen.add(g.id));
    groups.push(group.sort((a, b) => a.created_at.localeCompare(b.created_at)));
  }
  return groups;
}

function groupKey(group: TimelineTarget[]): string {
  return group
    .map((t) => t.id)
    .sort()
    .join("+");
}

function Facts({ t }: { t: TimelineTarget }) {
  const facts = [
    `added ${dateTime(t.created_at)}`,
    t.profile ? "has the old-paper analysis" : null,
    t.simulations ? plural(t.simulations, "simulation") : null,
    t.scope.length ? "mapped to material" : null,
  ].filter(Boolean);
  return <span className="small muted">{facts.join(" · ")}</span>;
}

function DuplicateCard({ group, onDismiss }: { group: TimelineTarget[]; onDismiss: () => void }) {
  const refresh = useInvalidateOrganisation();
  const [keep, setKeep] = useState<TimelineTarget | null>(null);
  const merge = useMutation({
    mutationFn: async (kept: TimelineTarget) => {
      for (const other of group.filter((t) => t.id !== kept.id)) {
        await request(`/targets/${other.id}/merge`, { method: "POST", json: { into_id: kept.id } });
      }
    },
    onSuccess: () => {
      setKeep(null);
      refresh();
    },
  });
  const first = group[0]!;
  // Suggest keeping the one that carries the most (old-paper analysis, simulations, mapping), else the oldest.
  const suggested = [...group].sort(
    (a, b) =>
      Number(Boolean(b.profile)) - Number(Boolean(a.profile)) ||
      b.simulations - a.simulations ||
      b.scope.length - a.scope.length ||
      a.created_at.localeCompare(b.created_at),
  )[0]!;
  return (
    <div className="notice warn stack" style={{ gap: 10 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong className="row" style={{ gap: 8 }}>
          <CourseDot color={first.course_color} />
          {first.course_title}: {group.length} entries look like the same exam
        </strong>
        <button type="button" className="btn small ghost" onClick={onDismiss}>
          They are different
        </button>
      </div>
      <span className="small">Probably recorded from two chats. Choose the one to keep; the other is merged into it.</span>
      <ul className="list">
        {group.map((t) => (
          <li key={t.id} className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div>
                <strong>{t.name}</strong> · {dateLabel(t.due_date)}
                {t.id === suggested.id && <span className="chip good" style={{ marginLeft: 8 }}>Suggested</span>}
              </div>
              <div className="small pre">{t.scope_description}</div>
              <Facts t={t} />
            </div>
            <button type="button" className={t.id === suggested.id ? "btn small primary" : "btn small"} onClick={() => setKeep(t)}>
              Keep this one
            </button>
          </li>
        ))}
      </ul>
      {merge.error && <ErrorNote error={merge.error} />}
      <Confirm
        open={keep !== null}
        title={`Keep ${keep?.name ?? ""} and merge the other?`}
        confirmLabel="Merge"
        busy={merge.isPending}
        onConfirm={() => keep && merge.mutate(keep)}
        onClose={() => setKeep(null)}
      >
        The old-paper analysis and simulations of the other entry move to {keep?.name}; its scope mapping is used if{" "}
        {keep?.name} has none, and its description is added to the notes. The other entry is then deleted; you can restore it
        from Recently deleted for 30 days.
        {merge.error && <ErrorNote error={merge.error} />}
      </Confirm>
    </div>
  );
}

export function DuplicatesPanel({ targets }: { targets: TimelineTarget[] }) {
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const groups = duplicateGroups(targets).filter((g) => !dismissed.includes(groupKey(g)));
  if (!groups.length) return null;
  function dismiss(group: TimelineTarget[]) {
    const next = [...dismissed, groupKey(group)];
    setDismissed(next);
    try {
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
    } catch {
      /* remembered for this page only */
    }
  }
  return (
    <section className="stack" aria-label="Possible duplicate exams">
      {groups.map((g) => (
        <DuplicateCard key={groupKey(g)} group={g} onDismiss={() => dismiss(g)} />
      ))}
    </section>
  );
}

export function RecentlyDeleted() {
  const q = useDeletedTargets();
  const refresh = useInvalidateOrganisation();
  const restore = useMutation({
    mutationFn: (id: string) => request(`/targets/${id}/restore`, { method: "POST" }),
    onSuccess: refresh,
  });
  if (!q.data?.length) return null;
  return (
    <Card title="Recently deleted" meta="Restorable for 30 days">
      <ul className="list">
        {q.data.map((t) => (
          <li key={t.id} className="row" style={{ justifyContent: "space-between" }}>
            <span className="row" style={{ gap: 8 }}>
              <CourseDot color={t.course_color} />
              <span>
                <strong>{t.name}</strong> · {t.course_title} · {dateLabel(t.due_date)}
                {t.deleted_at && <span className="small muted"> · deleted {relativeDay(t.deleted_at)}</span>}
              </span>
            </span>
            <button type="button" className="btn small" onClick={() => restore.mutate(t.id)} disabled={restore.isPending}>
              Restore
            </button>
          </li>
        ))}
      </ul>
      {restore.error && <ErrorNote error={restore.error} />}
    </Card>
  );
}
