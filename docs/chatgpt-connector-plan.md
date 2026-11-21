# Plan: RecallSpring as a ChatGPT connector (not built)

Status: **plan only**, 2026-11-21 (ADR-008). This is the second half of the owner's answer. The first half,
Sign in with ChatGPT in the local app, is built as a proof of concept (docs/04 → Adapter `siwc`).

## Goal

The learner studies in ChatGPT the way they study in Claude Desktop today:

- ChatGPT reads the plan, material and notes;
- it asks questions and saves the learner's answers word for word;
- it records grades with evidence;
- RecallSpring keeps the records and decides review dates deterministically.

The connector reuses the existing connector API (`/api/v1/connector/*`, read + append only, no delete/settings tools,
daily limit) and the MCP server's tool contract (docs/07).

## Why it is not built yet

Claude Desktop starts RecallSpring's MCP server **locally** over stdio. ChatGPT reaches connectors **from OpenAI's
cloud**, so RecallSpring would need:

1. **A public HTTPS endpoint** for a remote MCP server (streamable HTTP). There is no HTTPS on the VPS yet (R11), and
   the deployment rules forbid touching ProtectedApp. An additive Nginx site or a tunnel needs an owner checkpoint and the
   staged rollout in docs/08.
2. **OAuth on the MCP endpoint** (the MCP authorization spec: protected-resource metadata, an authorization server,
   PKCE, short-lived tokens scoped to `connector`). Static connector tokens would not be acceptable on a public URL.
3. **A current reading of OpenAI's connector / Apps SDK docs and terms** on the day of building: what plans may add
   custom connectors, developer-mode limits, how tool results and UI widgets are shown, and whether write tools need
   confirmation. Nothing here assumes those details.

## Steps (each needs the owner's go-ahead)

1. **Revalidate** OpenAI's docs for custom connectors / Apps SDK and record the findings in
   `docs/10` → research log.
2. **Transport:** add a streamable-HTTP entry point to `services/mcp` next to stdio. The tools, wrapping of learner
   material as untrusted data, and the read/append-only surface stay the same. Test locally with an MCP inspector.
3. **OAuth:** RecallSpring becomes its own authorization server for the connector:
   - consent page behind the owner login;
   - tokens stored hashed with a scope, revocable from Settings;
   - every grant and revoke audited.

   Rate limits and the daily connector limit apply per token.
4. **Answer capture:** ChatGPT may not render RecallSpring's MCP App forms. The fallback is `submit_chat_answer`
   (`captured_via = assistant_transcription`), as with Claude when a form cannot render (R15). Check whether
   ChatGPT's widget support can show the answer and quiz forms safely (no model-generated HTML; first-party,
   textContent-only forms).
5. **Exposure:** only after HTTPS exists and the owner approves the exact Nginx/tunnel change:
   - publish only `/mcp` and the OAuth endpoints, never the owner web app's admin routes;
   - capture a baseline before and compare after;
   - keep a rollback ready.
6. **Smoke test** (as Mode A in docs/04 Gate 0): ChatGPT lists the tools, reads a plan and a section, an answer is
   saved verbatim before grading, a fabricated evidence reference is downgraded, no destructive tool is reachable.

## What stays true

- RecallSpring never asks for the learner's OpenAI password and never stores ChatGPT cookies.
- ChatGPT, like Claude, can only append and read. Deleting, settings, budgets and exports stay in the web app.
- Old grades are never rewritten. Archived material stays out of search.
