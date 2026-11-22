import { useAssistants, useSession } from "./queries";
import type { AssistantChoice, AssistantKey } from "./types";

/**
 * How the app names the assistant the learner studies with. It follows what is really connected (Settings →
 * Assistants): the only connected assistant by name, "your assistant" when several are, and the welcome page's
 * choice (migration 0018) while none is connected yet. Only wording depends on it.
 */
export interface AssistantWords {
  key: AssistantKey | null;
  /** "Claude", "Codex", "Antigravity", "ChatGPT" or "your assistant" (mid-sentence). */
  name: string;
  /** The same at the start of a sentence: "Your assistant". */
  Name: string;
  /** Where the learner studies: "in Claude", "in Codex", "in Chat" or "with your assistant". */
  where: string;
  /** The app a study conversation happens in: "Claude Desktop", "Codex", "RecallSpring's Chat", "your assistant". */
  app: string;
}

export const ASSISTANTS: { key: AssistantKey; label: string; app: string }[] = [
  { key: "claude", label: "Claude", app: "Claude Desktop" },
  { key: "codex", label: "Codex", app: "Codex" },
  { key: "antigravity", label: "Antigravity", app: "Antigravity" },
  { key: "chatgpt", label: "ChatGPT", app: "RecallSpring's Chat" },
];

/** A mix (or nothing chosen) is named neutrally: "your assistant". */
export function assistantWords(key: AssistantChoice | null | undefined): AssistantWords {
  switch (key) {
    case "claude":
      return { key, name: "Claude", Name: "Claude", where: "in Claude", app: "Claude Desktop" };
    case "codex":
      return { key, name: "Codex", Name: "Codex", where: "in Codex", app: "Codex" };
    case "antigravity":
      return { key, name: "Antigravity", Name: "Antigravity", where: "in Antigravity", app: "Antigravity" };
    case "chatgpt":
      return { key, name: "ChatGPT", Name: "ChatGPT", where: "in Chat", app: "RecallSpring's Chat" };
    default:
      return { key: null, name: "your assistant", Name: "Your assistant", where: "with your assistant", app: "your assistant" };
  }
}

export function useAssistant(): AssistantWords {
  const status = useAssistants();
  const chosen = useSession().data?.user.assistant;
  return assistantWords(status.data ? status.data.in_use : chosen);
}
