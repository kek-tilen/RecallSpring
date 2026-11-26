// Entry of the answer clock inlined into the MCP forms (npm run build:mcp-clock; ADR-014 §3).
import { AnswerClock, watchActivity } from "./answerClock";

(globalThis as unknown as { RecallSpringClock: unknown }).RecallSpringClock = { AnswerClock, watchActivity };
