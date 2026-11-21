# Plan: RecallSpring without Claude (Codex first, then a ChatGPT tutor in the app)

Status, 2026-11-21: **Phase 0 and Phase 1 built** (owner in chat); the owner's Codex smoke test is open. Setup: `docs/codex-setup.md`.
Phases 2 and 3 start after the owner's go-ahead.

## Owner decisions (2026-11-21)

- **Who:** other people too, **each on their own computer** (local install, their own ChatGPT account). Not several
  people on one shared server.
- **Order:** both paths, **Codex first**, then the ChatGPT tutor inside RecallSpring.
- **Grades:** a grade from ChatGPT or Codex counts **the same as Claude's**, under the same rules. Each grade records
  which assistant and model gave it.
- The ChatGPT web connector (`docs/chatgpt-connector-plan.md`) stays a later option. It needs a public HTTPS endpoint
  or OpenAI's Secure MCP Tunnel, OAuth 2.1 with an authorization server reachable from the internet, and plan
  eligibility that sources describe differently.

## What exists today

- The MCP server (`services/mcp`) runs locally over stdio. Its connector token is read from a file in `LOCALAPPDATA`,
  not from the client's config. Its tools are read and append only (docs/07).
- Answer and quiz forms are MCP Apps. A client that cannot show them falls back to `submit_chat_answer`, where the
  assistant copies the learner's words into RecallSpring.
- Sign in with ChatGPT (SIWC) works in the Chat page: conversations, chosen material, citations and visuals. It has no
  tool calls yet. OpenAI's docs say function tools are supported on this path (docs/04 → Adapter `siwc`).
- Connector grades are stored with `provider = "claude_app"`, fixed in the code (`api/connector.py`).

## Phase 0 — shared groundwork

1. **Which assistant is it.**
   - Each connector token gets a `client`: `claude_desktop`, `codex` or `chatgpt` (migration). Existing tokens become
     `claude_desktop`.
   - Settings → Connector creates a token for a chosen client and shows the matching setup steps.
   - Grades, answers and History show "Claude", "Codex" or "ChatGPT" plus the model the assistant reports. The model
     is labelled as reported by the assistant and unverified.
2. **Answer forms without MCP Apps.**
   - The MCP server reads the client's capabilities when it connects.
   - If the client cannot show MCP Apps, `open_answer_form` and `open_quiz` return a RecallSpring link instead, for
     example `http://127.0.0.1:4318/answer/<question>`.
   - The learner answers there, so the exact words are saved as typed (`captured_via = app_ui`), not copied by the
     assistant. The assistant then reads the attempt with `get_attempt` or `get_quiz_results`.
   - `submit_chat_answer` stays as the last fallback.
3. **Images.**
   - Check whether `view_page` and `view_image` reach the model in each client. Codex is reported to drop image blocks
     when structured content is also returned.
   - If they do not arrive, return the image alone or say clearly that the page could not be shown. Never pretend the
     page was seen.

## Phase 1 — Codex (CLI, IDE extension, Codex app)

1. **Revalidate** OpenAI's Codex MCP docs on the day of building and record them in docs/10 → research log. Codex
   reads local stdio MCP servers from `~/.codex/config.toml`; that file is shared by the CLI, the IDE extension and
   the desktop app.
2. **Installer** `scripts/install-codex-connector.ps1`, the Codex counterpart of the Claude Desktop installer:
   - creates a `codex` connector token in its own file;
   - backs up `config.toml`, then adds or replaces only a clearly marked `[mcp_servers.recallspring]` block. The block
     holds the command, `RS_API_URL`, `RS_CONNECTOR_TOKEN_FILE` and the startup and tool timeouts;
   - leaves every other setting untouched. The token itself never goes into `config.toml`.
3. **Study folders:** one empty folder per course (e.g. `Documents\RecallSpring Study\<course>`) with an `AGENTS.md`
   that holds the same study instructions as the Claude projects (docs/claude-projects.md). These are generated from
   the course list.
4. **Safety, because Codex can also run commands and edit files:**
   - Codex is started inside the study folder, in a read-only sandbox, with approval required for its own commands and
     file edits.
   - RecallSpring's own tools can run without asking each time. They only read or append, and the server checks every
     write; the learner can tighten this.
5. **Owner smoke test**, the same as Gate 0 for Claude:
   - the learner signs in to Codex themselves;
   - Codex lists the tools, reads the plan and a section;
   - an answer typed in the RecallSpring form is saved before grading;
   - a fabricated evidence reference is downgraded;
   - the grade shows "Codex · model";
   - no delete tool is reachable.

## Phase 2 — ChatGPT tutor inside RecallSpring (SIWC)

1. **Revalidate** the SIWC docs: function tools, preview limits, terms (local open-source apps; no background use
   without separate consent).
2. **Tools on the server.** The Chat page's ChatGPT calls the same tools as the connector:
   - plan, context, sections, notes, creating questions, opening forms, recording grades and summaries;
   - each is run by RecallSpring for the signed-in learner, through the same validated service functions;
   - learner material is wrapped as untrusted; there are no delete or settings tools;
   - a cap applies to tool calls per turn;
   - every call is logged with the message for audit.
3. **Study mode in Chat:**
   - choosing a course starts a study session with its context;
   - answer forms, quizzes and visuals appear inline in RecallSpring (first-party components; nothing the model writes
     is run);
   - the learner's answer is saved before the model sees it.
4. **Length of a session.** SIWC requires the whole conversation in every request, so cost and limits grow with
   length. One conversation is one study session. Near a set size, the tutor proposes a summary
   (`record_session_summary`) and a new session.
5. **Failures:**
   - quota, revoked access or being signed out shows a clear status;
   - drafts and answers stay saved;
   - deterministic work (review dates) continues;
   - never a fallback to paid API keys.
6. **Tests** with the fake OpenAI: tool-call loops, the tool-call cap, a forged evidence reference, an answer saved
   before inference, quota mid-turn.

## Phase 3 — installing for other people

- An install guide and a first-run page: create your account, time zone (today's default is Europe/Ljubljana), and
  choose your assistant (Claude, Codex or ChatGPT in the app).
- No owner-specific defaults or data in the repository; demo data only on request.
- **Open question before Phase 3:** which systems to support at first (Windows only, or also macOS/Linux), and whether
  PostgreSQL keeps running in Docker or gets a simpler setup.

## Risks

| Risk | Mitigation |
| --- | --- |
| SIWC is a preview; limits, models or terms can change | Clear status in the UI, drafts kept, no paid fallback; docs revalidated before building |
| Whole-history requests make long sessions expensive and slow | One conversation per study session, summary and restart near a size limit |
| Codex is a coding agent with shell and file access | Run in an empty study folder, read-only sandbox, approvals for its own commands; RecallSpring tools stay read/append only |
| Codex may not show MCP Apps forms or pass images to the model | Answer link to RecallSpring's own form; images checked per client, honest fallback |
| The model reported by Codex/ChatGPT cannot be verified | Stored as "reported by the assistant" |
| Other people's installs: setup support, updates, their data | Local only, nothing shared with the owner; install guide; backups stay on their computer |
| `config.toml` edits could break a user's Codex setup | Backup first, only a marked block changed, an uninstall option |

## What stays true

- RecallSpring never sees ChatGPT or Codex passwords. The SIWC tokens stay on the learner's computer. Codex signs in
  by itself.
- Assistants only read and append. Deleting, settings and exports stay in the web app with confirmation.
- AI grades are not validated psychometric scores, from any assistant.
