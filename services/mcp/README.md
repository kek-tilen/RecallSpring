# RecallSpring connector (MCP server)

Thin MCP server that Claude Desktop starts over stdio. Every tool calls RecallSpring's connector API (`/api/v1/connector`) with a connector token; the API enforces ownership, validation and the read/append-only contract. Setup: `docs/connector-setup.md`.

- **Read:** `get_study_plan`, `list_courses`, `get_course_outline`, `search_sources`, `get_source_section`, `get_notes`, `get_due_reviews`, `get_attempt`
- **Append:** `start_study_session`, `create_questions`, `submit_chat_answer` (fallback), `record_assessment`, `record_session_summary`
- **Library (append):** `create_course`, `import_file` (local PDF, Word, PowerPoint, Excel, OpenDocument, Markdown/text, CSV, subtitles, notebook, LaTeX, source code or a photo in Documents, Downloads or Desktop, up to 100 MB, uploaded directly with a category: material, notes, exercises, past_paper; waits for extraction), `add_text_source` (pasted text; both take an optional `folder` path such as "Lectures / Week 3", created when missing), `create_concepts` (linked to sections or marked inferred), `get_source_status`, `view_image` (Claude looks at a saved photo; large ones arrive as a smaller copy), `view_page` (a PDF page rendered as an image, a whole slide or page when RecallSpring has LibreOffice, the pictures on a slide, or picture N of a document or notebook; TIFF/BMP and oversized pictures are converted), `organise_courses` (university › faculty › semester by name)
- **Study targets and planning:** `get_study_context`, `set_study_target`, `update_study_target`, `record_exam_profile`, `set_concept_difficulty`, `set_availability` (also the interest share); `get_study_plan` takes `course_id` or none (overview); `get_exam_readiness` (target or a course's next exam: what is not studied, weak or not practised, by material, with the weakest concepts' gaps) and `get_weekly_review` (`weeks_ago`)
- **Interests and focus:** `create_course` with `kind="interest"` (learning outside university, no exam), `set_interest_goal`, `set_focus` (one course or interest first until a day, only on the learner's clear request); prompt **Add an interest**
- **Simulations:** `create_quiz`, `open_quiz` (MCP App `ui://recallspring/quiz`, app-only `save_quiz_draft` / `submit_quiz`), `get_quiz_results`, `record_assessments` (batch), `list_simulations` (`needs_grading` finds simulations answered in the web app)
- **Learning first:** `open_summary_form` (MCP App `ui://recallspring/summary`, app-only `save_learning_summary`), `mark_concepts_known`; `create_quiz` takes `mode` (`practice` needs studied concepts, `diagnostic` never schedules reviews)
- **Prompts:** `plan-semester` (set up every course before learning), `start-studying`, `exam-overview`, `weekly-review`, `add-interest`, `continue-from-chatgpt` (picks up chats moved in from ChatGPT: what they covered, what the learner confirms they know, what looked wrong, then a plan)
- **Moved in from ChatGPT:** saved chats are material with category `chat`; `get_study_context` returns the learner's `learner_preferences` (their own words, e.g. ChatGPT custom instructions), which never override RecallSpring's rules; archived material is left out of search and marked `hidden` in the outline
- **MCP Apps:** `open_answer_form` renders `ui://recallspring/answer-form`, a self-contained first-party HTML form (no external scripts, `textContent` only). It saves the learner's exact text through the app-only tool `submit_answer_from_form` (`_meta.ui.visibility: ["app"]`), then posts a chat message so Claude grades it.
- Learner material is wrapped in `<learner_material>` blocks and described to Claude as data, never instructions.

Configuration: `RS_API_URL` (default `http://127.0.0.1:4318`), `RS_CONNECTOR_TOKEN_FILE` (default `%LOCALAPPDATA%\RecallSpring\connector-token`).

**Remote (2026-11-27):** `recallspring-mcp --http [--host 127.0.0.1] [--port 4319]` serves the same tools at `/mcp` over MCP streamable HTTP for an assistant on another computer. It needs `RS_REMOTE_URL` (the address other computers use) and reads no token file: every request brings its own connector token (`Authorization: Bearer rsc_…`), checked with the API (`remote.py`). Setup and proxy: `docs/remote-connector.md`.

```bash
.venv/Scripts/python -m pip install --require-hashes -r requirements-dev.lock && .venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
```

```bash
.venv/Scripts/python -m pytest
```
