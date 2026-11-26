import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ASSISTANTS } from "../assistant";
import { useAssistants, useSession } from "../queries";
import type { AssistantKey, AssistantsStatus } from "../types";

/**
 * "Study in…" on a course card (ADR-012 §3), and "Go through today's plan in…" on Home (2026-11-26): the same
 * menu with a planning message for all courses. "Review in…" on Review and on a concept page (2026-11-26): the same
 * menu with a review message, so a due concept leads to a question from memory. Only links the makers document are used:
 * - Claude Desktop: `claude://claude.ai/new?q=` prefills a new chat (support.claude.com, "Open Claude Desktop with a link").
 * - Codex (ChatGPT desktop app): `codex://new?prompt=` prefills a new chat (learn.chatgpt.com, Commands → Deep links).
 * - Antigravity has no documented link for a folder or a chat, so the start message is copied only.
 * Nothing is ever sent for the learner: the message waits in the composer (and on the clipboard).
 */
export const STUDY_IN_STORE = "rs.studyIn.last";

/** Swappable in tests: opening an app link leaves the page in a browser. */
export const launcher = {
  open(url: string) {
    window.location.href = url;
  },
};

export function startMessage(course: { id: string; title: string }) {
  return `Let's study ${course.title} (course_id ${course.id}).`;
}

/** A review from memory: everything due in a course, or one concept (its practice level, graded; 2026-11-26). */
export type ReviewOf = { concept?: { id: string; term: string }; due?: boolean };

export function reviewMessage(course: { id: string; title: string }, review: ReviewOf) {
  const c = review.concept;
  if (!c) return `Let's review what is due in ${course.title} (course_id ${course.id}): one question from memory per concept, then grade each.`;
  const verb = review.due === false ? "practise" : "review";
  return `Let's ${verb} ${c.term} from ${course.title} (concept_id ${c.id}, course_id ${course.id}): one new question from memory at my practice level, then grade it.`;
}

/** Home's "Go through today's plan in…": the assistant plans today across all courses (no course_id). */
export const PLAN_MESSAGE = "Let's go through today's plan in RecallSpring: all my courses, and how to split my time today.";

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** The learner's own assistants: the connected ones, else the welcome page's choice, else all four. */
export function offeredAssistants(status: AssistantsStatus | undefined, chosen: string | null | undefined): AssistantKey[] {
  const order = ASSISTANTS.map((a) => a.key);
  const connected = status?.items?.filter((i) => i.connected).map((i) => i.key) ?? [];
  const mix = status?.mix ?? [];
  const pick = connected.length
    ? connected
    : mix.length
      ? mix
      : chosen && chosen !== "mix" && order.includes(chosen as AssistantKey)
        ? [chosen as AssistantKey]
        : order;
  return order.filter((k) => pick.includes(k));
}

const LABEL: Record<AssistantKey, string> = {
  chatgpt: "Chat (ChatGPT)",
  claude: "Claude Desktop",
  codex: "Codex",
  antigravity: "Antigravity",
};

function remembered(): AssistantKey | null {
  try {
    return (localStorage.getItem(STUDY_IN_STORE) as AssistantKey | null) ?? null;
  } catch {
    return null;
  }
}

/** With a course: study it (or review it). Without one: go through today's plan across all courses (Home). */
export function StudyIn({
  course,
  review,
  ask,
}: {
  course?: { id: string; title: string };
  review?: ReviewOf;
  /** any other start message for the course, e.g. "Similar, new questions" for a simulation (2026-11-26) */
  ask?: { label: string; message: string };
}) {
  const navigate = useNavigate();
  const status = useAssistants();
  const chosen = useSession().data?.user?.assistant;
  const offered = offeredAssistants(status.data, chosen);
  const [last, setLast] = useState<AssistantKey | null>(() => remembered());
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const label = ask ? ask.label : !review ? "Study" : review.due === false ? "Practise" : "Review";

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  async function study(key: AssistantKey | "copy") {
    setOpen(false);
    const text = ask ? ask.message : course ? (review ? reviewMessage(course, review) : startMessage(course)) : PLAN_MESSAGE;
    const folder = course ? "the course's study folder" : "the Planning study folder";
    if (key !== "copy") {
      setLast(key);
      try {
        localStorage.setItem(STUDY_IN_STORE, key);
      } catch {
        /* the choice is only a convenience */
      }
    }
    if (key === "chatgpt") {
      // a course chat starts with that course picked; the plan starts a planning chat with the message in the box
      const withCourse = course ? `course=${encodeURIComponent(course.id)}` : "";
      const withMessage = !course || review || ask ? `message=${encodeURIComponent(text)}` : "";
      navigate(`/chat/new?${[withCourse, withMessage].filter(Boolean).join("&")}`);
      return;
    }
    const copied = await copy(text);
    const also = copied ? " It is also copied, to paste into a conversation you already have." : "";
    if (key === "claude") {
      launcher.open(`claude://claude.ai/new?q=${encodeURIComponent(text)}`);
      setNote(`Claude Desktop opens a new chat with the start message ready to send.${also}`);
    } else if (key === "codex") {
      launcher.open(`codex://new?prompt=${encodeURIComponent(text)}`);
      setNote(`Codex opens a new chat with the start message ready; choose ${folder} as its workspace.${also}`);
    } else if (key === "antigravity") {
      setNote(
        copied
          ? `Start message copied. Open ${folder} in Antigravity and paste it.`
          : `Copy this into Antigravity, in ${folder}: ${text}`,
      );
    } else {
      setNote(copied ? "Start message copied." : `Copy this: ${text}`);
    }
  }

  return (
    <div className="study-in" ref={box}>
      {/* Always a choice, never a default launch (owner 2026-11-23); the last one used is only marked. */}
      <button
        type="button"
        className={course && !ask && review?.due !== false ? "btn small primary" : "btn small"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={ask ? `${label} in` : review && course ? `${label} ${review.concept?.term ?? course.title} in` : undefined}
        onClick={() => setOpen(!open)}
      >
        {course ? `${label} in…` : "Go through today's plan in…"}
      </button>
      {open && (
        <div
          className="study-in-menu"
          role="menu"
          aria-label={ask ? `${label} in` : course ? `${label} ${review?.concept?.term ?? course.title} in` : "Go through today's plan in"}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        >
          {offered.map((k) => (
            <button key={k} type="button" role="menuitem" autoFocus={k === (last && offered.includes(last) ? last : offered[0])} onClick={() => void study(k)}>
              {LABEL[k]}
              {k === last && <span className="muted tiny"> · last used</span>}
            </button>
          ))}
          <button type="button" role="menuitem" onClick={() => void study("copy")}>
            Copy the start message only
          </button>
        </div>
      )}
      {note && (
        <p className="small muted study-in-note" role="status">
          {note}
        </p>
      )}
    </div>
  );
}
