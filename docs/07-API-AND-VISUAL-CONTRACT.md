# 07 — API Surface and Safe Visual Contracts

## API conventions

Prefix `/api/v1`. JSON UTF-8; bearer app session via secure HttpOnly cookie, CSRF protection on mutating requests, authenticated owner access. All write requests require `Idempotency-Key` UUID and optional `If-Match` revision. UTC timestamps ISO 8601. Standard errors `{code,message,request_id,details?}` with no model tokens or document text leaked. File downloads require authorization and safe MIME handling. Generated TypeScript client from OpenAPI definition.

## Proposed routes

| Method | Route | Purpose |
|---|---|---|
| POST | `/auth/login` | Private app session (Argon2id credentials; rate-limited) |
| GET | `/auth/setup` | `{needs_setup, refusal}`: whether the install still has no account, and why this browser may not create it (`not_local`, `disabled`) |
| POST | `/auth/setup` | First run: `{username, password (≥ 12), timezone}` creates the first account and signs it in (201). Refused once any account exists (409 `already_set_up`), from another computer (403 `first_run_not_local`), from another site, and in production or with `RS_FIRST_RUN_ENABLED=false` (403 `first_run_disabled`); 422 `invalid_timezone` |
| PUT | `/settings/profile` | `{timezone?, assistant?, assistant_mix?}` (assistant null = not chosen; set on the welcome page; `"mix"` needs `assistant_mix` with at least two different of claude/codex/chatgpt/antigravity, else `422 mix_too_small`; stored in that order, cleared when another choice is saved); audited `profile.changed` with from/to; returns the user |
| GET | `/settings/assistants` | `{items: [{key: claude/codex/antigravity/chatgpt, connected, tokens, last_used_at, in_mix}], in_use, chosen, mix}` (with a mix its assistants come first; a mix is "your assistant" until exactly one is connected): connected from an active connector token (Claude, Codex, Antigravity) or the ChatGPT sign-in; last use from the tokens or the newest Chat conversation. `in_use` is the only connected assistant, the welcome choice while none is, null when several are (the web then says "your assistant") |
| POST | `/auth/logout` | Revoke session |
| GET | `/ai/providers` | Providers, connection state, capabilities, limits and current usage |
| PUT | `/ai/providers/{provider}` | Configure a provider (store API key server-side, set limits); never echoes secrets |
| POST | `/ai/providers/{provider}/connect` | Start the provider's official auth flow (SIWC) or verify a key |
| POST | `/ai/providers/{provider}/disconnect` | Revoke/forget credentials as supported |
| GET | `/ai/models` | Models actually available per provider (discovered, not hardcoded) |
| GET/PUT | `/ai/routing` | Per-task model routing and course/session overrides |
| GET/PUT | `/settings/connector` | Connector daily limit (1–100 % of default), usage today, tokens |
| POST | `/settings/connector/tokens` | Create a connector token (shown once; stored as a hash) for `client` `claude` (default label "Claude Desktop") `codex` ("Codex") or `antigravity` ("Antigravity", migration 0021); tokens list their `client` |
| POST | `/settings/connector/tokens/{id}/revoke` | Revoke a connector token |
| GET | `/connector/*` | Connector surface: **bearer connector token only**, read + append, see tool contract below |
| GET/POST | `/courses` | List/create courses |
| GET/PATCH | `/courses/{id}` | Course detail and goals |
| GET | `/courses/{id}/contents` | `{title, counts, restorable_days: 30}`: what deleting the course hides (materials, folders, concepts, notes, exams, simulations, questions, answers, conversations, focus_blocks) |
| DELETE | `/courses/{id}` | Body `{confirm_title}` must equal the title exactly, else 422 `confirm_title_mismatch`. Soft delete of the course and everything in it (its rows get the course's `deleted_at`; questions, quizzes, attempts and reviews follow the course); idempotent; audit and learning event `course.deleted` with the counts; returns `{deleted, restorable_days: 30}`. Everything in a deleted course is 404 and leaves every list and the connector |
| GET | `/courses/deleted` | Courses deleted in the last 30 days, newest first, with `deleted_at` |
| POST | `/courses/{id}/restore` | Within 30 days: clears exactly the course's stamp (things deleted on their own before stay deleted); 409 `course_exists` when another course took the name; audit `course.restored` |
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
| GET | `/notes`, `/notes/{id}`, `/notes/{id}/revisions` | Notes and history (autosave snapshots, preserved conflicts). Each note has `references`: the Library files its text links (`[name](source:<id>)`), in order, as `{id, filename, kind, course_id, missing}`; `missing` (no name) for a deleted file or an ID that is not the learner's |
| DELETE | `/notes/{id}` | Soft delete after the learner confirmed it (idempotent; audit `note.deleted`, learning event); returns `{deleted, restorable_days: 30}`. A deleted note is 404 for get, patch and revisions and leaves `get_notes` |
| GET | `/notes/deleted` | Notes deleted in the last 30 days (optional `course_id`), newest first |
| POST | `/notes/{id}/restore` | Restore within 30 days (audit `note.restored`); 404 afterwards |
| POST | `/study-sessions` | Start study/review session |
| GET | `/study-sessions/{id}` | Retrieve session with messages and state |
| POST | `/study-sessions/{id}/turns` | User message saved; optional streamed tutor response |
| POST | `/questions/generate` | User-initiated grounded questions |
| POST | `/attempts` | **Durably save answer**; return attempt ID before evaluation. `photo_ids` (≤ 4): the learner's own image sources in the question's course, saved first (`POST /sources`, category notes, folder "Answer photos"); a photo alone is an answer; `422 photo_invalid` / `photo_other_course` / `too_many_photos` |
| POST | `/attempts/{id}/evaluate` | Start model-backed assessment; safe retry |
| GET | `/attempts/{id}` | Raw answer, assessments, state, `photos` `[{id, filename, available}]` (also in the connector's view; the MCP server returns them as images with `get_attempt` / `get_answer`) |
| POST | `/assessments/{id}/challenge` | Record disagreement/correction request |
| GET | `/reviews/due` | Due queue and reasons |
| POST | `/reviews/{id}/defer` | Record explicit defer |
| GET | `/planner/today` | Deterministic ranked daily plan (`plan-v2`: `interests` and `focus` explained), optional `course_id` and `minutes` |
| GET | `/targets/{id}/readiness` | Exam readiness (`readiness-v1`): every concept in scope with its state, grouped by material; weakest concepts with the gaps from their last feedback; next steps; time check; simulations (404 for someone else's target) |
| GET | `/overview/week?weeks_ago=0..52` | Weekly review (`week-v1`), Monday to Sunday in the learner's time zone: planned vs. recorded study time, activity, grade average and trend, per course, overdue reviews and exams in the next 21 days (current week only), plain summary sentences |
| GET/PUT | `/settings/study` | Weekly minutes, maintenance share (0–50 %), past-paper style share (0–100 %), interest share (0–50 %, 0 = university first); GET also returns the current `focus` |
| GET/POST | `/settings/backup` | Backup status (last good backup, what it holds, check, next, folder, size, failure; no secrets) / back up now (synchronous; `409 backup_busy`, `503 backup_failed` with the reason; audited) |
| PUT | `/settings/focus` | `{course_id, until}`: one course or interest first until a day (≤ 60 days), `course_id` null ends it; audited |
| POST | `/sync/push` | Idempotent offline outbox replay |
| GET | `/sync/changes?cursor=` | Incremental account-scoped updates |
| POST | `/exports` | Export job, user initiated |
| POST | `/deletion-requests` | Preview impact, then separate confirm |
| GET/POST | `/folders` | The learner's library folders with path, file count and archived state (`?course_id=`) / create one `{course_id, parent_id, name}` (Idempotency-Key; `422 folder_too_deep` beyond 5 levels, `422 too_many_folders` beyond 300 per course; `409 folder_exists` for the same name in the same place) |
| PATCH | `/folders/{id}` | Rename or move `{name?, parent_id?}` within its course (no cycles); audited |
| POST | `/folders/{id}/archive` | `{archived: bool}` archive or restore a folder; its files are hidden with it, not changed |
| DELETE | `/folders/{id}` | Remove an **empty** folder (soft delete, audited); `409 folder_not_empty` |
| GET | `/library/archived` | Everything archived: groups (semesters…), courses, folders, files, each with what restoring needs |
| GET | `/sources?course_id=&archived=` | Material with `folder` and `folder_path`; archived (or inside an archived folder) only with `archived=true` |
| POST | `/sources/move` | `{source_ids ≤ 200, folder_id \| null}` file material into a folder of the same course or back to its top level |
| POST | `/sources/archive` | `{source_ids ≤ 200, archived}` archive or restore material; audited |
| POST | `/sources` | (addition) optional `folder_id` and `folder_path` ("Week 3/Lab", created below `folder_id`, part of the idempotency fingerprint) |
| POST | `/sources/zip` | A ZIP of the learner's own files, unpacked into folders (≤ 2000 entries, nothing executed, unsupported files listed as skipped with a reason, duplicates in the same folder skipped); audited `source.zip_imported` |
| POST | `/imports/chatgpt` | Stage a ChatGPT data export ZIP (≤ 1 GiB, `conversations.json` ≤ 300 MB, ≤ 20 000 chats); `422 not_a_chatgpt_export`; nothing is saved as material yet |
| GET | `/imports/chatgpt`, `/imports/chatgpt/{id}` | Staged uploads; one upload's chats (title, project, dates, turns, attached files) and the instructions/memories found |
| GET | `/imports/chatgpt/{id}/chats/{key}` | Word-for-word preview of one chat (Markdown, ≤ 200 000 characters) |
| POST | `/imports/chatgpt/{id}/save` | `{course_id, folder_id?, folder?, keys ≤ 200, include_files}` save chosen chats (category `chat`, origin `import`) and their files; already saved ones are skipped; audited `import.chatgpt_saved` |
| DELETE | `/imports/chatgpt/{id}` | Delete the staged upload now (it expires after 7 days anyway); audited |
| GET/PUT | `/settings/preferences` | The learner's own study preferences `{text ≤ 4000}` (e.g. ChatGPT custom instructions and memories); audited; read by Claude in `get_study_context` |
| GET | `/ai/chatgpt` | Sign in with ChatGPT status (account, scopes, plan usage, `unavailable_reason`: `disabled`/`not_local`); never tokens |
| POST | `/ai/chatgpt/connect` | Start sign-in (CSRF): returns the OpenAI authorize URL; `409 chatgpt_not_local` / `chatgpt_disabled` |
| GET | `/ai/chatgpt/callback` | OAuth redirect target (one-time `state`, no session cookie needed); 303 to `/settings?chatgpt=<outcome>` |
| GET | `/ai/chatgpt/models` | Models listed for the account (`visibility == "list"`) |
| GET | `/ai/chatgpt/conversations` | Saved conversations (newest first), recently deleted ones (30 days) and usage over the last 24 hours and 30 days; readable while signed out |
| GET | `/ai/chatgpt/conversations/{id}` | One conversation: messages with, per reply, model chosen, model and version that answered, response ID, time, duration, account and token usage; failed messages with their error code; totals |
| POST | `/ai/chatgpt/messages` | `{conversation_id?, model, message ≤ 4000, visuals = true, source_ids? ≤ 20 (new conversation only), recallspring = false, course_id? (new conversation only; study mode, own course or 404), photo_ids? ≤ 4 (images pasted or dropped into the message, saved first in the Library; sent once as `input_image` with this message, later turns only say they were there)}` (Idempotency-Key: a retry never asks twice): saves the message, then waits for `response.completed` and saves the reply. With `recallspring: true` ChatGPT may use RecallSpring's tools (docs/04; up to 6 responses and 12 calls); the learner's message then lists `tool_calls` `[{call_id, name, arguments, status, error_code, summary, writes, ms, form?}]`, where `form` is `{kind: "answer", question_id}`, `{kind: "summary", course_id, concept_ids, title, covered}` or `{kind: "quiz", quiz_id, title}`. A conversation view has `course` `{id, title}` or null; a learner's message has `photo_ids`. When `get_answer` returns an answer with photos, they follow the tool output as a user message with `input_image` parts, so ChatGPT grades the work on paper. `422 chatgpt_unsupported` carries `details.param` when OpenAI named the unsupported part; errors `chatgpt_*` (429 usage limit, never a paid fallback) carry `details.conversation_id`; `409 conversation_deleted` |
| PUT | `/ai/chatgpt/conversations/{id}/material` | `{source_ids ≤ 20}` (owner session + CSRF): the files whose matching excerpts are sent with the next messages; `[]` sends none; returns the conversation with `material`. Each message in a conversation view has `context` (on the learner's message: excerpts sent, `{ref, section_id, source_id, filename, label, chars}`) and `citations` (on a reply: the refs it cites that were really sent) |
| PATCH | `/ai/chatgpt/conversations/{id}` | Rename `{title ≤ 200}` (whitespace collapsed; `422 title_required`) |
| DELETE | `/ai/chatgpt/conversations/{id}` | Soft delete after the learner's confirmation; audited |
| POST | `/ai/chatgpt/conversations/{id}/restore` | Restore within 30 days; audited |
| POST | `/ai/chatgpt/disconnect` | Revoke at OpenAI (best effort) and delete the tokens here; audited |
| POST | `/focus-sessions` | One finished or stopped Pomodoro focus block `{client_session_id, course_id?, started_at, ended_at, planned_minutes 1–240, focused_seconds 60–14 400, completed}` (owner session + CSRF). Same `client_session_id` again returns the saved block (200, `Idempotent-Replay`). `422` for `ended_before_start`, `focus_time_out_of_range` (in the future or over 7 days old), `focus_longer_than_block`; `404` for a course that is not the learner's. Records `focus.completed` / `focus.stopped` |
| GET | `/focus/summary` | Focus time today, the last 7 days by day (learner's time zone) and by course, the latest 8 blocks, `removed` (blocks removed in the last `restore_days` = 30 days) |
| DELETE | `/focus-sessions/{id}` | Remove a wrongly timed block after the learner confirmed it (owner session + CSRF): soft delete, no longer counted anywhere (summary, Claude's `focus_time`); audited `focus.deleted`; returns the summary. Removing again changes nothing |
| POST | `/learning` | The learner's summary of a learning chunk written on the web `/summary` page (owner session + CSRF; same body and effect as the connector's `/learning`: saved exactly as a note, concepts marked studied) |
| PATCH | `/focus-sessions/{id}` | `{course_id: uuid or null}` (required): the course the block counts for, set afterwards; own blocks and courses only (404 otherwise); audited `focus.course_changed` with from/to; returns the summary |
| POST | `/focus-sessions/{id}/restore` | Count a removed block again within 30 days (`409 restore_period_over` after); audited `focus.restored`; returns the summary |
| GET | `/health/live` | Liveness, no secrets |
| GET | `/health/ready` | DB and storage checks, restricted if exposed |

For streaming, use SSE or chunked fetch response with typed events (`turn.started`, `text.delta`, `visual.validated`, `turn.completed`, `turn.failed`). A request failure must never erase saved user input. Streaming responses can be recovered by GET session. Keep server-side authorization checks independent of UI.

## Assistant connector (MCP) tool contract (Claude Desktop, Codex)

Views with a grade carry `graded_by` (evaluator kind) and `grader` `{name, model}`: "Claude", "Codex", "RecallSpring (answer key)" or "You", plus the model the assistant reported. History reads "3/4 (final) by Codex (model)".

**Apps without MCP Apps forms** (e.g. Codex): `open_answer_form`, `open_quiz` and `open_summary_form` check whether the client announced the MCP Apps extension (`io.modelcontextprotocol/ui` with the `text/html;profile=mcp-app` type). If not, they return a link to the learner's RecallSpring web app (`RS_WEB_URL`, default the API address): `/answer/{question_id}?session=…`, `/simulations/{quiz_id}` (the clock starts when the learner opens it) or `/summary?course=…&concepts=…&title=…&covered=…`. The learner answers there (`captured_via = app_ui`); `get_answer` reads the latest saved answer of a question (connector `GET /questions/{id}` returns `latest_attempt`).

**Forms in RecallSpring's Chat:** a form sent from Chat stays in the conversation with the question and the learner's exact text. The answer form of an earlier turn shows the learner's newest answer to that question and its grade (web `GET /questions/{id}` returns `latest_attempt_id`; then `GET /attempts/{id}`); an earlier form never answered stays a link.

Tools call `/api/v1/connector/*` with a connector token, which is accepted nowhere else (owner routes need the session cookie and CSRF token). Every request counts towards the owner's daily connector limit. All writes are append-only; there are **no** delete, restore, export, budget, consent or routing tools.

| Tool | Kind | Contract |
|---|---|---|
| `get_study_plan` | read | Today's ranked plan with `why_selected` |
| `list_courses`, `get_course_outline` | read | Courses, syllabus topics, concepts and coverage |
| `search_sources`, `get_source_section` | read | Section text wrapped as untrusted document content, with section ID and citation label; IDs are remembered for the session |
| `get_notes` | read | Learner notes for a topic (read-only; the tutor may comment in chat but never rewrites notes), each with the Library files it links (`files` / `references`: name, kind, `source_id`, or deleted) so the assistant can open them with `view_image`, `view_page` or `get_source_section` |
| `get_due_reviews` | read | Due concepts with due reason and last evidence |
| `get_attempt` | read | Exact stored answer, question with rubric (an attempt exists), cited sections |
| `get_answer` | read | The latest saved answer to a question, as `get_attempt` (after a RecallSpring link), or that none is saved yet |
| `start_study_session` | append | Connector study session (`origin = connector`) |
| `create_questions` | append | Up to 10 questions (Bloom level, prompt, hidden rubric); `source_refs` must be sections of the course |
| `open_answer_form` | UI | MCP App `ui://recallspring/answer-form` showing the question (no rubric) |
| `submit_answer_from_form` | append, app-only | Called by the form (`visibility: ["app"]`): exact typed text, `captured_via = answer_form`, idempotent by `client_request_id` |
| `submit_chat_answer` | append | Fallback when the form cannot render: `captured_via = assistant_transcription` |
| `record_assessment` | append | Once per attempt; validated against `assessment.schema.json`; evidence refs that are not real sections of the question's course are dropped and a final grade becomes `provisional`; returns the next review date and reason |
| `record_session_summary` | append | Once per session |
| `create_course` | append | New course (`POST /connector/courses`); `kind: "interest"` for personal learning without exams, description = goal |
| `set_interest_goal` | audited update | The learner's goal for an interest (`POST /connector/courses/{id}/goal`) |
| `set_focus` | audited update | Only on the learner's clear request: one course or interest first until a day; null ends it (`POST /connector/focus`) |
| `import_file` | append | Local file read by the connector process (allowed folders and types only) and uploaded with the same checks as the web upload; waits for extraction; optional `folder` path ("Lectures / Week 3"), created when missing |
| `add_text_source` | append | Pasted text as a source; optional `folder` path |
| `get_source_status` | read | Extraction state and section IDs/labels (no text) |
| `create_concepts` | append | Up to 30 concepts; existing terms reused; linked sections must belong to the course, otherwise `inferred` |
| `get_study_context` | read | Active target, scope, exam profile, passed targets, recent simulations; `needs_setup` + questions to ask |
| `set_study_target`, `update_study_target` | append / audited update | Kolokvij or exam with verbatim scope description, resolved scope, specifics; status passed/failed, moved date |
| `record_exam_profile` | append | Item types, Bloom mix, topic weights (0.5–2.0) and short examples from past papers |
| `set_concept_difficulty` | audited update | Difficulty 1–5; Claude's estimate never overrides a learner rating |
| `set_availability` | audited update | Weekly minutes, a one-day override, or the interest share (`interest_percent`, 0 = university first) |
| `create_quiz` | append | Simulation of 1–30 items: `mcq` (options A–H, hidden key) or `open` (hidden rubric), style `past_paper`/`deeper` |
| `open_quiz` | UI | MCP App `ui://recallspring/quiz` (no keys or rubrics before submission; time limit starts on first open) |
| `save_quiz_draft`, `submit_quiz` | append, app-only | Draft autosave; one-transaction submission idempotent by `client_request_id`; MCQ graded from the key |
| `get_quiz_results` | read | Answers (as learner material), keys, rubrics, pending open answers, points |
| `record_assessments` | append | Batch grading, all or nothing |
| `get_study_plan` | read | `plan-v2`, optional `course_id` (course or interest, no priority rules) or none (overview with `interests` and `focus`), capacity per active target |
| `get_exam_readiness` | read | `GET /connector/readiness?target_id=` or `?course_id=` (that course's active target; `409 no_upcoming_exam`, `422 target_or_course_required`): the readiness view with less per concept (id, term, state, last grade, due, exam weight) |
| `get_weekly_review` | read | `GET /connector/week?weeks_ago=`: the weekly review, same as the web page |
| `open_summary_form` | UI | MCP App `ui://recallspring/summary`: the learner summarises the chunk just taught |
| `save_learning_summary` | append, app-only | `POST /connector/learning`: exact summary as a note, concepts become `studied` |
| `mark_concepts_known` | audited update | `POST /connector/concepts/known`: learner self-report with reason |
| `create_quiz` / `create_questions` guard | — | `409 concepts_not_studied` for practice on unstudied concepts; `mode="diagnostic"` pre-tests never schedule reviews |
| `get_study_context` | (addition) | `learner_preferences {text, how_to_use}` or null: the learner's own words on how they like to study, as preferences, never as rules above RecallSpring's |
| prompt `continue-from-chatgpt` | prompt | Picks up from chats saved from ChatGPT (category `chat`): read them, say what was covered, confirm with the learner, then mark known only what the learner confirms |

`search_sources` skips archived material and material in archived folders; `get_course_outline` still lists it with `hidden: true` (its sections stay readable by ID, so earlier citations keep working) and lists the course's visible folders as paths, so Claude can use the learner's own names.

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

In a chat reply a model writes a visual as a fenced block tagged `recallspring-visual` with one JSON object (`services/visual_blocks.py`; at most 4 per reply, 20 000 characters each). The server parses it without NaN/Infinity, validates it against the schema, then checks what the schema cannot: unique node ids, edges to existing nodes, one value per comparison column, finite numbers, numeric x for scatter, slider minimum < initial ≤ maximum and at most 2 000 steps. `source_refs` keep only the excerpt references (`S1`, …) really sent with the question (none when no material was chosen); a chart left without any is forced to `illustrative: true`. Each saved assistant message is returned with `visuals: [{ok: true, block} | {ok: false, error}]`, in fence order, computed from the saved text on every read, so a stricter checker also applies to old replies. The web app draws only from `visuals`, never from the fence text. `interactive_parameter` drives only the built-in presets (`linear_growth` y = p·x, `exponential_decay` y = e^(−p·x), `quadratic_curve` y = p·x², `unit_circle`); no model expression is evaluated. The instructions describing the format are added only when the request has `visuals: true`; the audit event records `visuals_allowed` and which blocks passed.

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
