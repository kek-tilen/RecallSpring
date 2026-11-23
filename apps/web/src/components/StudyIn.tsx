import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ASSISTANTS } from "../assistant";
import { useAssistants, useSession } from "../queries";
import type { AssistantKey, AssistantsStatus } from "../types";

/**
 * "Study in…" on a course card (ADR-012 §3). Only links the makers document are used:
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
  const connected = status?.items.filter((i) => i.connected).map((i) => i.key) ?? [];
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

export function StudyIn({ course }: { course: { id: string; title: string } }) {
  const navigate = useNavigate();
  const status = useAssistants();
  const chosen = useSession().data?.user?.assistant;
  const offered = offeredAssistants(status.data, chosen);
  const [last, setLast] = useState<AssistantKey | null>(() => remembered());
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const box = useRef<HTMLDivElement>(null);

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
    const text = startMessage(course);
    if (key !== "copy") {
      setLast(key);
      try {
        localStorage.setItem(STUDY_IN_STORE, key);
      } catch {
        /* the choice is only a convenience */
      }
    }
    if (key === "chatgpt") {
      navigate(`/chat/new?course=${encodeURIComponent(course.id)}`);
      return;
    }
    const copied = await copy(text);
    const also = copied ? " It is also copied, to paste into a conversation you already have." : "";
    if (key === "claude") {
      launcher.open(`claude://claude.ai/new?q=${encodeURIComponent(text)}`);
      setNote(`Claude Desktop opens a new chat with the start message ready to send.${also}`);
    } else if (key === "codex") {
      launcher.open(`codex://new?prompt=${encodeURIComponent(text)}`);
      setNote(`Codex opens a new chat with the start message ready; choose the course's study folder as its workspace.${also}`);
    } else if (key === "antigravity") {
      setNote(
        copied
          ? `Start message copied. Open the course's study folder in Antigravity and paste it.`
          : `Copy this into Antigravity, in the course's study folder: ${text}`,
      );
    } else {
      setNote(copied ? "Start message copied." : `Copy this: ${text}`);
    }
  }

  return (
    <div className="study-in" ref={box}>
      {/* Always a choice, never a default launch (owner 2026-11-23); the last one used is only marked. */}
      <button type="button" className="btn small primary" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Study in…
      </button>
      {open && (
        <div
          className="study-in-menu"
          role="menu"
          aria-label={`Study ${course.title} in`}
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
