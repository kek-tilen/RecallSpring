# ADR-002 — AI provider architecture: Claude connector + pluggable in-app providers

- **Status:** Accepted by owner, 2026-11-19
- **Supersedes:** the SIWC-only design and the "no classic LLM API keys" rule of the original build pack

## Context

The owner is moving from ChatGPT to Claude and prefers Claude's explanation style. They want to use their existing Claude subscription rather than pay for API usage, and they want the system to support other models (including custom LLMs) later.

Anthropic's published terms allow consumer-plan OAuth only for Claude Code and Anthropic's native apps. Developers building their own products must use API keys and may not offer Claude.ai login, route requests through consumer-plan credentials, or store or intermediate Claude.ai credentials. A Claude plan does not include API usage.

## Decision

1. **Mode A — Claude connector (primary).** RecallSpring exposes an MCP server. The owner studies in the official Claude app (Claude Desktop, local stdio connector first) on their own plan. Claude reads plans/sources and appends questions and assessments through typed tools; answers are captured by a first-party MCP App form that writes the learner's exact text before grading.
2. **Mode B — in-app providers** behind an `LLMProvider` interface with capability flags and per-task routing: `anthropic_api` (official SDK, owner key, monthly USD limit), `siwc` (official OpenAI flow), `openai_compatible` (future custom/self-hosted LLMs), `mock` (tests, always labelled Simulated).
3. The non-AI core never depends on any provider.
4. Default tutor model is Sonnet, switchable per course/session (Opus for demanding material).

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Call Claude from RecallSpring using the owner's Pro/Max login | Prohibited by Anthropic's terms (consumer OAuth outside native apps). |
| Drive the Claude Code / Agent SDK binary headlessly from the backend on the subscription | Terms direct developers building products to API keys; usage limits assume ordinary individual use; fragile and enforceable without notice. |
| Anthropic API key only | Legitimate but always paid; kept as optional Mode B adapter with a hard USD limit. |
| SIWC only (original design) | Kept as an optional adapter for other self-hosters. |

## Consequences

- No credentials for Claude ever reach RecallSpring in Mode A. Plan usage limits are invisible to RecallSpring; it can only throttle its own tool calls (daily limit 1–100 %).
- The chat transcript of Mode A lives in the owner's Claude account; RecallSpring stores the learning record and optional session summaries.
- A remote connector for Claude web/mobile needs public HTTPS and OAuth on the MCP endpoint; deferred (desktop-only).
- New tables: `ai_routing`, `ai_usage_ledger`, `connector_tokens`; `attempts.captured_via` and `attempts.kind`.
- Gate 0 is split per mode; each mode is enabled only after its own proof passes.
