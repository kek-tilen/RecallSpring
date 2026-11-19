# 03 — Data Model and Persistence Contract

## Data protection invariants

- App persists notes, imports, prompts, user answers, AI feedback and scheduler events; no reliance on provider-hosted chat history (in Mode A the chat transcript stays in the learner's Claude account; the learning record is in RecallSpring).
- Source documents are never overwritten by AI text. Keep SHA-256 content hash and explicit extraction status.
- Every acknowledged user action is committed transactionally before return. AI output is a derived, fallible record.
- Learning evidence is append-only; destructive user-visible operations use versioned soft-delete and audit trail.
- Prefer stable UUID primary keys, `created_at`/`updated_at` UTC timestamps, row-level `user_id`, and foreign-key constraints.
- Test backups by restoring an isolated copy. Encrypt secrets and backup artifacts; do not export OAuth tokens with learning data.

## Core relational tables

| Table | Required attributes and constraints |
|---|---|
| `users` | `id`, local account identity, password hash (Argon2id), login settings, timestamps |
| `ai_connections` | `id`, owner, provider (`anthropic_api`, `siwc`, `openai_compatible`, `mock`), connection state, **reference to protected server-side secret only**, limits (USD monthly / daily request %), background-AI consent; no raw keys or tokens in DB or logs |
| `ai_routing` | owner, task (`tutor/question_generation/evaluation/concept_extraction`), provider, model, optional course/session override |
| `ai_usage_ledger` | owner, provider, model, task, request id, input/output/cache tokens, estimated cost (USD, pricing-table version), status, timestamp |
| `connector_tokens` | owner, label, token hash, scopes (`connector`), created/last_used/revoked timestamps |
| `courses` | `id`, owner, title, description, `long_term_retention` bool, status |
| `syllabus_items` | `id`, course, title, parent, position, expected coverage, optional exam weighting |
| `exams` | `id`, course, date/timezone, title, status, goal priority |
| `sources` | `id`, course, filename, kind, mime, bytes, SHA256, private content-addressed storage key, origin (`upload/paste`), `duplicate_of`, parse state/error/notes, parser version, version, uploaded/parsed time |
| `source_sections` | `id`, source, source version, order, page/heading, extracted text, text offsets, citation label, parser version, `tsvector` (language-neutral `simple` config) |
| `concepts` | `id`, course, canonical term, definition draft, syllabus item link, state (`new/learning/learned/...`), `source_confidence` |
| `concept_sources` | concept-to-source_section link with evidence excerpt span, inference flag |
| `concept_relations` | from, to, relation enum (`prerequisite/part_of/related_to/contrasts_with`), origin and confidence |
| `notes` | `id`, author, course, topic, `client_note_id` (offline idempotency), raw Markdown/plaintext, revision, deleted_at, saved_at |
| `note_revisions` | note, kind (`autosave` snapshot coalesced per editing burst, or `conflict` = a rejected stale draft kept until resolved), revision, base revision, body, saved_at |
| `study_sessions` | `id`, owner, course/topic, mode (`new_learning/review`), timestamps, checkpoint |
| `messages` | `id`, session, role, content, source refs, visual block IDs, status; separately from attempts |
| `questions` | `id`, topic/concepts, Bloom level 1–6, prompt, answer rubric, source refs, difficulty, provenance, generated_at |
| `attempts` | `id`, question, user, session, **exact raw answer**, kind (`answer/dont_know/skip`), answer mode (`closed_notes/open_notes`), `captured_via` (`app_ui/answer_form/assistant_transcription`), submitted_at, idempotency key unique, status |
| `assessments` | `id`, attempt, evaluator/model/version, grade 0–4 or NULL, rubric subscores, feedback, evidence, uncertainty, status (`final/provisional/ungraded`), created_at |
| `mastery_state` | user/concept key, evidence_count, last_success_at, estimated level band, confidence low/medium/high, last recomputed_at |
| `review_state` | user/concept key, interval_days, last_review_at, due_at, consecutive_successes, lapse_count, scheduling policy version |
| `learning_events` | id, owner, entity, event type, immutable payload, timestamp, correlation id |
| `sync_operations` | owner/device/idempotency key unique, object, base revision, patch checksum, state, server timestamp |
| `jobs` | id, owner, type, payload ref, state, retries, locked_until, attempt count, last_error (sanitized), created/updated |
| `visual_blocks` | id, message, version, JSON spec, validated renderer type, explanation/fallback |
| `deletion_requests` | id, owner, scope, impact summary, requested/confirmed timestamps, reversible_until, state |
| `audit_events` | actor, action, target, before/after hashes or redacted references, timestamp, request id |

This is a logical model; agents may normalize fields and add indexes, but cannot drop essential audit/evidence/retry properties.

## Query and index guidance

- Index `(user_id, due_at)` for due reviews, `(course_id, parent_id)` for syllabus, `(session_id, created_at)` for messages, `(user_id, created_at)` for attempts, `source_sections.source_id` and full-text document content where useful.
- Partial unique indexes on idempotency keys and active review records.
- Restrict each entity by user ownership at service layer and in automated access-control tests. Prevent cross-course accidental leakage.

## Event examples

```json
{
  "type": "attempt.submitted",
  "event_id": "uuid",
  "actor_id": "uuid",
  "entity_id": "attempt-uuid",
  "occurred_at": "2026-11-19T16:00:00Z",
  "payload": {
    "question_id": "uuid",
    "answer_mode": "closed_notes",
    "client_request_id": "uuid"
  }
}
```

Persist the raw answer in `attempts` with tight owner authorization, not redundantly in server logs.

## Assessment and mastery provenance

`assessment` should include: `grade`, `rubric_version`, `evidence_refs`, `factuality_flags`, `confidence`, `feedback`, `suggested_remediation`, `teacher_review_status`. Weak concepts are *hypotheses* from attempts, not permanent labels. Record the exact evidence used by the scheduler and expose correction actions. Avoid a fake `97% mastery` display without calibration; display labels `Emerging`, `Developing`, `Reliable`, `Review due`, along with evidence count and last assessment.

## Retention, deletion and export

- Source/notes/attempts are private; authenticated user can export CSV/JSON/Markdown plus original files in ZIP. Exclude secrets and OAuth credentials from export.
- Default `deleted_at` soft-delete period **30 days** as a proposed owner-configurable policy; app must explain that backups may retain copies according to documented backup schedule.
- A destructive action must show: entity count, affected questions/notes/source links, scheduled reviews impacted and recoverability duration; require explicit confirm with human-readable text.
- `DELETE` finalization via explicit maintenance task, never model-triggered. Preserve minimal tombstone events to prevent sync resurrection.
- Implement exact match file upload de-duplication by hash within same user; only with user-visible indication. Two imports of same file must not silently merge course associations.
