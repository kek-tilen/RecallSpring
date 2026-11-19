# ADR-004 — Claude connector (Mode A) design

- **Status:** Accepted, 2026-11-19 (implements ADR-002 Mode A)
- **Code:** `services/api/src/recallspring_api/api/connector.py`, `connector_auth.py`, `services/planner.py`; `services/mcp/`

## Decision

- **Separate package** `services/mcp` (official `mcp` Python SDK, `MCPServer` + `Apps`), started by Claude Desktop over **stdio**. It is a thin HTTP client: no database access, no business rules, so the API remains the single writer and validator.
- **Path-scoped credential.** Connector tokens (`rsc_…`, stored as SHA-256) are accepted only on `/api/v1/connector/*`; owner routes keep requiring the session cookie + CSRF. The read/append-only contract and "no destructive tools" therefore hold even if the MCP server were modified. A test asserts the connector OpenAPI surface has only GET/POST and no delete/export/settings paths.
- **Token on disk, not in Claude's config.** `recallspring connector-token` writes the token to a private per-user file (`%LOCALAPPDATA%\RecallSpring\connector-token`); `claude_desktop_config.json` contains only the command and API URL.
- **Daily limit** per learner-local day: default 600 requests × owner percentage (1–100 %), counted in its own transaction before the request runs.
- **Answer capture** via an MCP App (`ui://recallspring/answer-form`, `text/html;profile=mcp-app`): a self-contained first-party HTML form with an inline script implementing the documented postMessage JSON-RPC protocol (`ui/initialize`, `ui/notifications/tool-result`, `tools/call`, `ui/message`). It shows "saved" only after the API confirms the commit, uses `client_request_id` as the idempotency key, renders model text with `textContent` only, and calls an **app-only** tool (`visibility: ["app"]`). Fallback: `submit_chat_answer` marks `captured_via = assistant_transcription`.
- **Grading through the connector** reuses the server-side assessment validation (shared schema, evidence must be real sections of the question's course, one AI assessment per attempt, learner corrections still win). The response returns the recomputed review date and reason so Claude can explain it.
- **Planner `plan-v0`** (deterministic; Review due → Strengthen → Explore next, within the available minutes, at most five items, each with `why_selected`) is shared by the web app and the connector.

## Consequences

- Claude-reported model names are stored as `model_reported_by = assistant` (unverified).
- The chat transcript stays in Claude; RecallSpring records sessions, questions, attempts, assessments and summaries.
- A remote connector for Claude web/mobile would need Streamable HTTP + OAuth on a public HTTPS endpoint; deferred.
- Whether a given Claude Desktop build renders MCP Apps for local servers must be confirmed by the owner's manual test; the text fallback keeps the flow working regardless.
