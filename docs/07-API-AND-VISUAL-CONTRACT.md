# 07 — API Surface and Safe Visual Contracts

## API conventions

Prefix `/api/v1`. JSON UTF-8; bearer app session via secure HttpOnly cookie, CSRF protection on mutating requests, authenticated owner access. All write requests require `Idempotency-Key` UUID and optional `If-Match` revision. UTC timestamps ISO 8601. Standard errors `{code,message,request_id,details?}` with no model tokens or document text leaked. File downloads require authorization and safe MIME handling. Generated TypeScript client from OpenAPI definition.

## Proposed routes

| Method | Route | Purpose |
|---|---|---|
| POST | `/auth/login` | Private app session (Argon2id credentials; rate-limited) |
| POST | `/auth/logout` | Revoke session |
| GET | `/ai/providers` | Providers, connection state, capabilities, limits and current usage |
| PUT | `/ai/providers/{provider}` | Configure a provider (store API key server-side, set limits); never echoes secrets |
| POST | `/ai/providers/{provider}/connect` | Start the provider's official auth flow (SIWC) or verify a key |
| POST | `/ai/providers/{provider}/disconnect` | Revoke/forget credentials as supported |
| GET | `/ai/models` | Models actually available per provider (discovered, not hardcoded) |
| GET/PUT | `/ai/routing` | Per-task model routing and course/session overrides |
| GET/PUT | `/settings/connector` | Connector daily limit (1–100 % of default), usage today, tokens |
| POST | `/settings/connector/tokens` | Create a connector token (shown once; stored as a hash) |
| POST | `/settings/connector/tokens/{id}/revoke` | Revoke a connector token |
| GET | `/connector/*` | Connector surface: **bearer connector token only**, read + append, see tool contract below |
| GET/POST | `/courses` | List/create courses |
| GET/PATCH | `/courses/{id}` | Course detail and goals |
| GET/POST | `/courses/{id}/syllabus` | Syllabus objectives and coverage |
| POST | `/sources` | Multipart upload; create extraction job |
| GET | `/sources/{id}` | Status, metadata, sections |
| GET | `/sources/{id}/sections` | Read extracted source sections |
| POST | `/sources/text` | Pasted Markdown/plain text becomes a source (fallback for scanned PDFs) |
| GET | `/sources/search?q=&course_id=` | Full-text search over current sections; plain-text snippets marked « » |
| GET | `/sources/{id}/file` | Unchanged original, always as attachment with `nosniff` |
| POST | `/sources/{id}/reprocess` | Extract again as a new version; earlier sections stay citable |
| GET | `/sections/{id}` | One citable section (text, page/heading, offsets, citation label) |
| GET/PATCH | `/topics/{id}` | Topic and links |
| POST | `/notes` | Create note, autosave revisions |
| PATCH | `/notes/{id}` | Mutate note by `base_revision`; `409 revision_conflict` keeps the rejected draft as a `conflict` revision |
| GET | `/notes`, `/notes/{id}`, `/notes/{id}/revisions` | Notes and history (autosave snapshots, preserved conflicts) |
| POST | `/study-sessions` | Start study/review session |
| GET | `/study-sessions/{id}` | Retrieve session with messages and state |
| POST | `/study-sessions/{id}/turns` | User message saved; optional streamed tutor response |
| POST | `/questions/generate` | User-initiated grounded questions |
| POST | `/attempts` | **Durably save answer**; return attempt ID before evaluation |
| POST | `/attempts/{id}/evaluate` | Start model-backed assessment; safe retry |
| GET | `/attempts/{id}` | Raw answer, assessments, state |
| POST | `/assessments/{id}/challenge` | Record disagreement/correction request |
| GET | `/reviews/due` | Due queue and reasons |
| POST | `/reviews/{id}/defer` | Record explicit defer |
| GET | `/planner/today` | Small deterministic ranked daily plan |
| POST | `/sync/push` | Idempotent offline outbox replay |
| GET | `/sync/changes?cursor=` | Incremental account-scoped updates |
| POST | `/exports` | Export job, user initiated |
| POST | `/deletion-requests` | Preview impact, then separate confirm |
| GET | `/health/live` | Liveness, no secrets |
| GET | `/health/ready` | DB and storage checks, restricted if exposed |

For streaming, use SSE or chunked fetch response with typed events (`turn.started`, `text.delta`, `visual.validated`, `turn.completed`, `turn.failed`). A request failure must never erase saved user input. Streaming responses can be recovered by GET session. Keep server-side authorization checks independent of UI.

## Claude connector (MCP) tool contract

Tools call `/api/v1/connector/*` with a connector token, which is accepted nowhere else (owner routes need the session cookie and CSRF token). Every request counts towards the owner's daily connector limit. All writes are append-only; there are **no** delete, restore, export, budget, consent or routing tools.

| Tool | Kind | Contract |
|---|---|---|
| `get_study_plan` | read | Today's ranked plan with `why_selected` |
| `list_courses`, `get_course_outline` | read | Courses, syllabus topics, concepts and coverage |
| `search_sources`, `get_source_section` | read | Section text wrapped as untrusted document content, with section ID and citation label; IDs are remembered for the session |
| `get_notes` | read | Learner notes for a topic (read-only; the tutor may comment in chat but never rewrites notes) |
| `get_due_reviews` | read | Due concepts with due reason and last evidence |
| `get_attempt` | read | Exact stored answer, question with rubric (an attempt exists), cited sections |
| `start_study_session` | append | Connector study session (`origin = connector`) |
| `create_questions` | append | Up to 10 questions (Bloom level, prompt, hidden rubric); `source_refs` must be sections of the course |
| `open_answer_form` | UI | MCP App `ui://recallspring/answer-form` showing the question (no rubric) |
| `submit_answer_from_form` | append, app-only | Called by the form (`visibility: ["app"]`): exact typed text, `captured_via = answer_form`, idempotent by `client_request_id` |
| `submit_chat_answer` | append | Fallback when the form cannot render: `captured_via = assistant_transcription` |
| `record_assessment` | append | Once per attempt; validated against `assessment.schema.json`; evidence refs that are not real sections of the question's course are dropped and a final grade becomes `provisional`; returns the next review date and reason |
| `record_session_summary` | append | Once per session |

## API example: attempt creation

Request:

```json
{
  "question_id": "b75ddf3f-4255-4a3e-9d4f-dfe556813c69",
  "session_id": "3cc6a493-558f-4889-97ce-4488cdb0ea7b",
  "answer_text": "My own explanation, exactly as submitted.",
  "answer_mode": "closed_notes",
  "client_request_id": "a807ed91-91d4-4585-87c4-e85e716e73e9"
}
```

Success (must be committed before 201 response):

```json
{
  "attempt_id": "dd3832b8-faa1-43ce-86e5-14d78bb7b83c",
  "status": "saved_awaiting_evaluation",
  "saved_at": "2026-11-19T16:00:00Z"
}
```

## AI visual output

Only six renderer types enumerated above. Never accept HTML/CSS/JS generated by an LLM as executable content. JSON schema file: `schemas/visual-block.schema.json`; every block includes `type`, `title`, `alt_text`, validated bounded `data`, optional `source_refs`. Limit nodes/edges/labels, sanitize text, use verified quantitative claims only. For ungrounded numeric charts, show `illustrative example` conspicuously.

Examples:

```json
{
  "type": "process_flow",
  "title": "Example study process",
  "alt_text": "Read material, explain from memory, then check reasoning.",
  "data": {
    "nodes": [
      {"id":"read","label":"Read"},
      {"id":"recall","label":"Explain from memory"},
      {"id":"check","label":"Check reasoning"}
    ],
    "edges": [
      {"from":"read","to":"recall"},
      {"from":"recall","to":"check"}
    ]
  },
  "source_refs": []
}
```

When the model proposes an invalid block, log only a sanitized validation reason and fall back to accessible text. Avoid Mermaid raw model syntax in production; sanitize/validate even if a vetted diagram library supports it.

## Error and retry states

- Upload failure: retry with same idempotency key or create a new operation intentionally.
- 409 note conflict: preserve both versions, show diff and explicit resolution.
- Provider limit (plan quota, USD limit, daily limit) or model refusal: retain attempt, display `Saved; feedback unavailable` with the specific limit, allow manual later retry; never switch provider or model silently.
- Provider auth revoked (401) or connector token revoked: app remains usable; prompt reconnection, never redirect away mid-edit.
- Partial SSE failure: event `turn.failed` and preserve saved input; never mark complete.
- Malformed model JSON: safe fallback, do not blindly persist a grade or execute visuals.
