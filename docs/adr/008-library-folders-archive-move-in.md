# ADR-008 — Library folders, one Archived page, moving in from ChatGPT, Sign in with ChatGPT

- **Status:** Accepted by owner, 2026-11-21. Owner answers in chat, including all three move-in parts (chats, project files, instructions and memory).
- **Builds on:** ADR-002 (AI providers), ADR-004 (Claude connector), docs/04 → Adapter `siwc`.

## Context

The library had become one long list per course. Material, notes and photos were hard to find. Archived items were
spread over several pages and hard to restore. Before RecallSpring, the owner prepared for exams in ChatGPT and wants
to bring that work over. We had agreed to support OpenAI
sign-in. The product rule "never force users to manage folders" still applies.

## Decision

### Library: automatic grouping plus the learner's own folders

- The library groups everything **automatically** (university › semester › course › kind). This needs no filing.
- The learner **may** add folders (`source_folders`, migration 0010):
  - each folder belongs to one course and can be nested up to 5 levels;
  - at most 300 per course;
  - names are unique per parent (case-insensitive), with slashes turned into dashes.
- `sources.folder_id` null means the course's top level. Existing material stays there, so nothing changes until the
  learner files something.
- A folder or a ZIP that is uploaded keeps its structure. Levels beyond the fifth are joined into one name
  ("a - b - c") rather than refused. Claude's `import_file` / `add_text_source` take an optional `folder` path, and
  the outline lists the folders, so Claude uses the learner's own names.
- A folder can be removed only when empty (soft delete, audited). Moving material between courses is not possible,
  because citations, concepts and attempts belong to a course.

### Archive: one place, everything restorable

- `sources.archived_at` and `source_folders.archived_at` join the existing course and group archive.
- Archiving hides material from the library and from search. It is still kept, citable by section ID, and listed with
  `hidden: true` in Claude's outline.
- `/library/archived` lists four kinds of archived items: semesters/groups, courses, folders and files. Each has a
  Restore button.
- Archive and restore are audited learning events. Nothing is deleted.

### Moving in from ChatGPT

- **Source of truth:** only the **official data export** (ZIP with `conversations.json`). No scraping, no cookies, no
  internal endpoints.
- **Staging:** the ZIP is staged for 7 days and parsed as JSON only, under size, entry and chat caps. The learner
  picks the chats; nothing becomes material without that choice.
- **Saved chats:**
  - each is saved **word for word** as Markdown (the branch ChatGPT showed, dates in the learner's time zone);
  - category `chat`, origin `import`;
  - put into the course and folder the learner chooses (default "Chats from ChatGPT");
  - deduplicated by content, so saving twice does nothing.
- **Project files:** files attached in the export are saved with the chats through the normal upload checks. Other
  project files arrive as folders or ZIPs.
- **Custom instructions and memories** are offered as a suggestion for **Study preferences** (`users.study_preferences`,
  migration 0011, at most 4000 characters, audited). They are saved only when the learner presses Save. Claude
  reads them in `get_study_context` as preferences that never override RecallSpring's rules.
- **New prompt `continue-from-chatgpt`:**
  - Claude reads the chats and says what they covered;
  - it marks as known only what the learner confirms;
  - it flags what looked wrong, checked against the course material;
  - then it plans the next steps.
  - Old ChatGPT answers are never treated as grades or as evidence of mastery.
- Chats are not translated. UI copy stays English.

### Sign in with ChatGPT: in the local app first, a connector later

- **First, a proof of concept in the local app.** It follows the official open-source token-sharing contract
  (docs/04):
  - sign-in, model list, saved conversations (each reply with model and version, time, duration and tokens; kept after signing out) and sign-out, all user-initiated;
  - only on loopback, with the redirect at `127.0.0.1`;
  - tokens are kept locally under the user's control (DPAPI / 0600), outside Git, the database and backups;
  - `store: false`, `stream: true`, allowlisted fields only;
  - every error is shown; it never falls back to paid usage.
- **Not used for tutoring or grading yet.** The owner's live test comes first (Gate 0 step 3). Claude stays the tutor.
- **Later, a ChatGPT connector,** so ChatGPT can use RecallSpring like Claude does. It needs public HTTPS and OAuth on
  the MCP endpoint, so it is planned only for now (`docs/chatgpt-connector-plan.md`).

## Consequences

- Two additive migrations. Each downgrade refuses while data that would be lost exists (folders, archive marks,
  imported chats, preferences). Migrations run separately from the app rollout.
- More API surface, all owner-session + CSRF. Writes are idempotent where the web app retries.
- The import parser depends on an undocumented export format. Unknown content is left out and counted, never guessed
  (R17). Imported text and preferences are untrusted content (R18). SIWC is a preview that can change (R19).
- Tests: `test_library_folders.py`, `test_imports.py`, `test_chatgpt_signin.py` (fake OpenAI), and the MCP prompt
  test.

## Rollback

- Turn off the app features by reverting the web/API commits.
- `RS_CHATGPT_SIGNIN_ENABLED=false` switches sign-in off without a deploy. Signing out deletes the local tokens.
- Downgrading migration 0011 and then 0010 is possible once imported chats and preferences, then folders and archive
  marks, are cleared. This is only for an owner-approved rollback, after a backup.
