# 04 — AI Provider Contract and Technical Feasibility Gate

## Hard user constraints

- **No traditional OpenAI/Anthropic API keys, no API billing requirement.**
- The app should offer a first-class ChatGPT tutoring experience through an official, permitted integration. It must **not** pretend this is the full ChatGPT first-party interface.
- The VPS is user-controlled; whether a remote deployment meets all current terms must be checked against official documentation at runtime.
- Use an AI adapter interface so the deterministic learning engine and user data remain usable even when disconnected or quota limited.

## Official route to test first

OpenAI's **Sign in with ChatGPT (SIWC)** allows eligible Plus/Pro users, with consent and relevant scopes, to invoke an eligible Responses API subset via OAuth in supported open-source apps. The official self-hosted VM guide describes completing OAuth locally and transferring protected credentials to the user's VM. These are changing preview capabilities, not a blanket promise that every feature of ChatGPT is accessible.

Sources (revalidate before coding):
- https://developers.openai.com/siwc/quickstart
- https://developers.openai.com/siwc/token-sharing-open-source
- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://openai.com/policies/sign-in-with-chatgpt-terms/

### Legal/security invariants

- Authentication tokens must be obtained only from officially supported flows, kept under user's local control, never logged or stored in user browser code or remote-managed storage; the user's self-hosted, controlled VM needs explicit security review. Never repurpose tokens for unrelated apps.
- Requests from remote runtime must be controlled by the authenticated user; user requests or user-authorized automations only. **Explicit opt-in before any background LLM calls**; off by default. Deterministic scheduling needs no LLM request.
- No account pooling, credential sharing, resale, subscription usage bypass, or service offered to other users on one subscription.
- Treat revoked/expired scope as a normal state. Show explicit disconnect and delete local credentials controls.

### As-of-2026-11-19 SIWC preview contract

- Discover available models with the connected user's OAuth bearer token; do not hardcode an entitlement or assume `GPT-6` is available.
- Responses HTTP requests: `store: false`, `stream: true`; use `instructions` or developer role instructions. Supply entire required conversation context inside `input` each request; do not use `previous_response_id` over HTTP.
- Preview rejects certain normal Responses fields, including `background`, `conversation`, `max_output_tokens`, `max_tool_calls`, `metadata`, `moderation`, `multi_agent`, `prompt`, `prompt_cache_retention`, `safety_identifier`, `temperature`, `top_logprobs`, `top_p`, `truncation`, `user` (verify current list).
- Unsupported hosted tools currently include image generation, file search, Code Interpreter, native computer use, hosted MCP/connectors and `tool_search`. Do not rely on any of these for v1.
- Supported inputs may include text, image and file content for eligible models, but the Files upload API, audio/video input and transcription are not supported through this flow at present.
- Streaming can end with success or fail *after* data has been received. Persist full evaluated result only on valid completion; partial textual tutoring stream may be shown as interrupted.
- App **owns its entire conversation history and source retrieval**. Do not import first-party ChatGPT conversations; sign-in does not provide access to them.

## Gate 0: Mandatory minimal proof of concept

Without touching VPS production state:

1. Make a minimal open-source repo and exercise supported local SIWC OAuth consent with an eligible account.
2. Confirm actual granted scopes and model discovery. Show them in UI, excluding tokens.
3. Make one *official* streamed Responses request satisfying preview field restrictions; receive `response.completed`.
4. Confirm one subsequent turn with app-owned history; confirm `store:false` behavior.
5. Exercise user-visible quota, revoked-auth, network interruption and token-refresh paths (mock where necessary).
6. Validate a self-hosted VM flow on an isolated test machine/container with protected credential transfer **only after user authorization** and following official guide.
7. Verify that intended request patterns (interactive study, sources, function-style output) are supported. Confirm appropriate terms for user-controlled remote automation.
8. Record the final decision in `docs/10-DECISIONS-AND-RISKS.md` and only then unlock production AI features.

**Failure behavior:** If SIWC is unavailable or incompatible, ship a usable non-AI core and a clear AI connection blocker; do not sneak in another paid or unofficial provider. User approval is required to change no-key constraint.

## Provider interface (proposed)

```typescript
interface TutorProvider {
  getConnectionStatus(): Promise<ConnectionStatus>;
  listModels(): Promise<ModelInfo[]>;
  streamTutorTurn(args: {
    courseId: string;
    sessionId: string;
    history: ValidatedTutorMessage[];
    sourceContext: SourceExcerpt[];
    intent: "explain" | "generate_question" | "evaluate" | "visualize";
    idempotencyKey: string;
  }): AsyncIterable<ProviderEvent>;
}
```

Server-side policy validator constrains inputs, checks consent, model availability and owner session; output parser validates structured objects before commit. PII/redaction policy and prompt budget per course/session configurable.

## AI tutor behavior

- Teach via concise explanation, ask follow-up questions, clarify misconceptions and calibrate difficulty.
- Base course-specific claims on selected source sections; show references. If evidence absent, distinguish general knowledge from provided material.
- Never disclose answer rubric before learner submission unless user explicitly asks for a hint/answer.
- Separate **generation** from **grading**. On objective items use deterministic checks where possible; on open-ended Bloom 4/5 use rubrics, counterexamples, evidence and `provisional` grade when multiple defensible answers exist.
- Teacher cannot directly edit DB or execute arbitrary visual JS; all actions pass typed backend functions and authorization.
- Visual suggestions use the allowlisted schemas in `schemas/` only; if invalid, fall back to plain text plus an error event.

## Asynchronous AI policy

Default: schedule dates/questions from stored content deterministically, generate or evaluate using a model only when the user actively starts or continues a session. If later allowing server-initiated LLM calls (e.g. nightly question pre-generation), obtain a dedicated `Allow background AI requests` opt-in with scope, frequency and revoke control; include quota and usage disclosure. A background model call must not be inferred from a generic review reminder.

## Model testing

Run prompts against a curated source-based test set with adversarial instruction text embedded in PDFs. Verify source citations, rubric grading, 'I don't know' behavior, JSON output validation and refusal to obey prompt injection in imported documents. Never pass a user's source document as a higher-priority instruction.
