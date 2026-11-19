# 04 — AI Provider Architecture and Integration Contract

> **Revised 2026-11-19 by owner decision** (replaces the SIWC-only design). Rationale and alternatives: `docs/adr/002-ai-provider-architecture.md`. Research facts: `docs/10-DECISIONS-AND-RISKS.md` → Gate 0 research log.

## Hard constraints

- AI is **optional and pluggable**. The deterministic learning engine, sources, notes, review queue and planner work with every provider disconnected.
- **No mandatory paid usage.** The owner's primary path uses their own Claude plan inside the official Claude app (Mode A). Paid API usage (Mode B with an API key) is opt-in and capped in USD.
- Only official, documented integration routes. Never collect, store or intermediate Claude.ai or ChatGPT consumer credentials or session tokens outside the vendor's own official flow; never call internal endpoints; never route a request through another person's plan.
- Provider-neutral data model: learning records belong to RecallSpring regardless of which model produced or graded them. Every AI-derived record stores provider, model and prompt/rubric version.

## Modes at a glance

| Mode | Where the conversation happens | Who pays | Status |
|---|---|---|---|
| **A — Claude connector** | Official Claude app (Claude Desktop first) calling RecallSpring's MCP tools | Learner's own Claude plan (usage counts against its limits) | **Primary; build first** |
| **B — In-app provider** | RecallSpring's own tutor pane, via `LLMProvider` adapters | Depends on adapter: ChatGPT plan (SIWC), Anthropic API credits (key), self-hosted model | After Mode A; adapters are independent |
| **Core (no AI)** | RecallSpring UI | — | Always available |

Anthropic's terms state that developers building their own products should use API-key authentication and may not offer Claude.ai login or route requests through Free/Pro/Max credentials. Mode A complies because the learner uses the **unmodified official Claude app** with their own plan, and RecallSpring is only a tool server that the app calls. RecallSpring never sees Claude credentials.

## Mode A — Claude connector (MCP)

### Transport and authentication

- **Local (now, desktop-first):** Claude Desktop launches the RecallSpring connector as a local **stdio** MCP server. The connector is a thin client of the RecallSpring API (`services/mcp`), authenticated with a **scoped connector token** created in RecallSpring Settings (shown once, stored hashed server-side, revocable, `last_used_at` tracked). Scope `connector` cannot reach deletion, export, budget, consent or account routes.
- **Remote (deferred):** Claude web/mobile connect to custom connectors **from Anthropic's cloud**, so a remote connector needs a public HTTPS endpoint (Streamable HTTP) protected by OAuth. Deferred until the owner approves a domain and HTTPS (Gate 4); the owner studies on one computer.

### Tool catalogue (read + append only)

The authoritative list lives in `docs/07-API-AND-VISUAL-CONTRACT.md` → Claude connector tool contract. Principles:

- Read tools return learner content and source text **wrapped and labeled as untrusted document content** with section IDs and citation labels; source text can never act as instructions.
- Append tools create records (questions, attempts, assessments, session summaries) through the same validated service functions as the HTTP API.
- **No destructive tools.** Deleting, restoring, exporting, changing budgets/consent/routing and editing source documents happen only in RecallSpring's UI with explicit confirmation.
- Tool descriptions instruct the model: do not reveal rubrics before submission; prefer Bloom 3–5; separate question generation from grading; cite section IDs; say when evidence is missing.

### Answer capture (persist-first invariant)

1. Claude calls `open_answer_form(question_id)`. Hosts that support **MCP Apps** render RecallSpring's first-party answer form inside the chat.
2. The learner types the answer in the form; the form calls `submit_attempt` with the **exact typed text** and a client request ID. The server commits the attempt before replying (`captured_via = "answer_form"`).
3. Only then does Claude read the attempt (`get_attempt`) and grade it.
4. Fallback where the form cannot render: Claude passes the learner's chat answer to `submit_attempt` with `captured_via = "assistant_transcription"`; the UI marks such attempts so the learner can check the stored text.

### Assessment recording and validation

`record_assessment` accepts the `packages/contracts/schemas/assessment.schema.json` shape plus provider/model metadata. The server:

- validates the schema, grade/status consistency and size bounds;
- accepts `evidence_refs` only if they are source-section IDs that RecallSpring returned in this study session; unknown refs are dropped and the assessment is downgraded to `provisional` with a factuality flag;
- never lets an uncertain (`provisional`, `ungraded`, low-confidence) assessment promote mastery or lengthen an interval (see `docs/05-LEARNING-ENGINE.md`);
- appends; never overwrites earlier assessments. Learner corrections (`Challenge evaluation`) are separate appended records.

### Model choice and limits

The learner picks the model in the Claude app (owner default: **Sonnet**, switching to **Opus** for demanding material). RecallSpring records the model name Claude reports, labelled `reported_by_assistant` (unverified). Plan usage limits are managed by the Claude app; RecallSpring cannot see them. RecallSpring's own **daily connector-request limit** (1–100 % of the default) can throttle tool calls.

### Limitations to keep honest in the UI

- The chat transcript lives in the learner's Claude account; RecallSpring holds the learning record (questions, attempts, assessments, notes, schedule) and optional session summaries.
- Visual explanations in Mode A are drawn by the Claude app itself; RecallSpring's safe visual renderer applies to its own UI (Mode B and stored visual blocks).
- Connector features depend on the Claude app (custom connectors, MCP Apps). If a feature disappears, fall back to transcription capture and keep the core working.

## Mode B — in-app providers

### Provider interface

```python
class LLMProvider(Protocol):
    id: str  # "anthropic_api", "siwc", "openai_compatible", "mock"
    def capabilities(self, model: str) -> ProviderCapabilities: ...
    async def connection_status(self) -> ConnectionStatus: ...
    async def list_models(self) -> list[ModelInfo]: ...  # discovered, never hardcoded entitlements
    def stream_turn(self, request: TurnRequest) -> AsyncIterator[ProviderEvent]: ...
    async def generate_structured(self, request: StructuredRequest) -> StructuredResult: ...
```

`ProviderCapabilities` flags: `streaming`, `structured_output`, `tool_use`, `citations`, `pdf_input`, `image_input`, `prompt_caching`, `usage_reporting`, `cost_reporting`. Feature code checks capabilities instead of provider names. A per-task **routing table** (`tutor`, `question_generation`, `evaluation`, `concept_extraction`) maps each task to a provider and model, with per-course and per-session overrides. Owner default for every task: `claude-sonnet-5-5` when the Anthropic adapter is configured; Opus (`claude-opus-5-5`) selectable for demanding courses.

A server-side policy layer runs before every call: owner session, consent (background opt-in), budget/limit check, input-size bounds, provider capability check. Output parsers validate structured objects before commit; invalid output becomes a sanitized error event, never a partial record.

### Adapter: Anthropic Claude API (`anthropic_api`)

- Official `anthropic` Python SDK only. Owner-provided API key from platform.claude.com, stored server-side as a protected secret file; never echoed back after saving.
- **Hard monthly USD limit** set by the owner. Each call is pre-checked against the remaining budget and post-recorded in an `ai_usage_ledger` from `response.usage` and a versioned pricing table. At the limit: stop new calls and show the limit state; never switch model or provider silently. Recommend the owner also sets a spend limit in the Anthropic Console.
- Streaming for tutor turns; `stop_reason` checked before reading content (handle `refusal`, `max_tokens`).
- **Citations** on source `document` blocks for tutor explanations (verifiable quotes with page/char locations). **Structured outputs** (`output_config.format`) for assessments and generated questions. The two cannot be combined in one request, so grading and cited explanation are separate calls.
- **Prompt caching** for stable source context (frozen system prompt and source blocks first, volatile content last); verify with `usage.cache_read_input_tokens`.
- Adaptive thinking with an explicit `effort` per task; no sampling parameters.

### Adapter: OpenAI Sign in with ChatGPT (`siwc`)

Kept as a feature for other self-hosters and for the owner. Implemented after Mode A. Contract as researched on 2026-11-19 (revalidate before coding):

- Dynamic client registration (`client_id=dynamic_agent_client` + `agent_name_hint` on first sign-in; the issued `oaiapp_…` client ID is reused afterwards), PKCE S256, fresh `state`/`nonce`, stable per-host `ext_agent_host_id`, scopes `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`, `resource=https://api.openai.com/v1`.
- Redirect URI **only** `http://127.0.0.1:<port>/…` (never `localhost`): sign-in completes on the computer running the browser. Remote instances receive credentials through the official self-hosted VM procedure (secure transfer; the VM owns refreshes).
- Access token 1 h; refresh tokens rotate (30-day lifetime each); serialize refreshes; revoke via the discovery document's `revocation_endpoint` on sign-out.
- Inference `POST https://api.openai.com/v1/responses` with `store: false`, `stream: true`, full history in `input`, system text via `instructions`. Omit `previous_response_id`, `background`, `conversation`, `max_output_tokens`, `max_tool_calls`, `metadata`, `moderation`, `multi_agent`, `prompt`, `prompt_cache_retention`, `safety_identifier`, `temperature`, `top_logprobs`, `top_p`, `truncation`, `user` — enforced by an **allowlist request builder**. Function/custom tools are supported (use them for structured grading); hosted image generation, file search, code interpreter, computer use, hosted MCP and `tool_search` are not.
- Errors: `subscription_sharing_usage_limit_exceeded` (429) pauses plan-using requests with OpenAI's `Usage limit reached` / `Manage usage` UI; `…_usage_unavailable` and `…_user_unavailable` (503) use bounded backoff; `…_user_not_eligible` is explained without looping OAuth; `…_unsupported_capability` (400) removes the offending field and never retries the same body.
- Scope caveat: OpenAI's docs describe this path for open-source and *locally hosted* apps; clear a remotely hosted instance with OpenAI (interest form) before enabling SIWC there.

### Adapter: OpenAI-compatible / custom LLMs (`openai_compatible`, future)

For self-hosted or third-party models exposing an OpenAI-compatible API (e.g. Ollama, LM Studio, vLLM). Capabilities are declared per configured model by the owner; missing structured-output support falls back to strict JSON validation with `ungraded` on failure.

### Adapter: mock (`mock`)

Deterministic, for tests and offline development only. Every mock output is labelled **Simulated** in API responses and UI, is always `provisional` with low confidence, and therefore never changes intervals or mastery.

## Consent, limits and background calls

- User-initiated calls are the default. Server-initiated LLM calls (e.g. nightly question pre-generation) require a dedicated `Allow background AI requests` opt-in per provider, OFF by default, with scope, frequency and revoke control. A review reminder never implies a model call.
- Limits: monthly **USD** limit for API-key providers; daily AI-request limit **1–100 %** of the default for plan-based providers and the connector. Limit state is visible in Settings and wherever an AI action is offered.

## AI tutor behavior (all modes)

- Teach via concise explanation, ask follow-up questions, clarify misconceptions and calibrate difficulty.
- Base course-specific claims on selected source sections and show references. Without evidence, distinguish general knowledge from the provided material.
- Never disclose the answer rubric before submission unless the learner asks for a hint or the answer.
- Separate **generation** from **grading**. Use deterministic checks for objective items; for open-ended Bloom 4/5 use rubrics, counterexamples and evidence, and `provisional` when several defensible answers exist.
- Reply in the language of the learner's question or material unless the learner chooses otherwise; never translate original notes without consent. UI copy stays English.
- The model never mutates records directly: every action passes typed backend functions with authorization and validation.
- Visual suggestions in RecallSpring's UI use only the allowlisted schemas in `packages/contracts/schemas/`; invalid specs fall back to plain text plus an error event.

## Gate 0 (revised)

1. ✅ Re-validate official terms and docs (Anthropic consumer vs API use, Claude custom connectors, MCP Apps, SIWC) — 2026-11-19, see research log.
2. **Mode A smoke test (local):** Claude Desktop lists RecallSpring tools; reads plan and source sections; an answer submitted through the form is stored verbatim before grading; an assessment with a fabricated evidence ref is downgraded; no destructive tool is reachable.
3. **Mode B (later, per adapter):** SIWC OAuth + model discovery + streamed `response.completed` + second turn with app-owned history + quota/revoke/refresh paths; Anthropic API key smoke test only if the owner adds a key and a USD limit.
4. Record PASS/BLOCKED per mode in `docs/10-DECISIONS-AND-RISKS.md`; a mode is enabled only after it passes.

## Model testing

Run prompts against a curated, human-reviewed source-based test set (including adversarial instruction text embedded in PDFs) for every provider/model pair in use. Verify citations, rubric grading, "I don't know" behavior, structured-output validation and refusal to obey prompt injection in imported documents. Never pass a learner's source document as a higher-priority instruction.

## Sources (revalidate on implementation day)

- Anthropic: https://code.claude.com/docs/en/legal-and-compliance (authentication and credential use), https://support.claude.com/en/articles/11175166 (custom connectors via remote MCP), https://modelcontextprotocol.io/docs/extensions/apps (MCP Apps), https://privacy.claude.com/en/articles/7996866 (API data retention)
- OpenAI SIWC: https://developers.openai.com/siwc/token-sharing-open-source and its `sign-in`, `self-hosted-vms`, `models-and-inference`, `preview-limitations`, `errors-and-recovery`, `token-reference`, `profiles-and-sessions` pages; https://developers.openai.com/siwc/ui-ux-guidelines; https://openai.com/policies/sign-in-with-chatgpt-terms/ (returned HTTP 403 to automated fetch on 2026-11-19 — read manually before enabling SIWC)
