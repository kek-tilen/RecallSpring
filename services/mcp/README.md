# RecallSpring connector (MCP server)

Thin MCP server that Claude Desktop starts over stdio. Every tool calls RecallSpring's connector API (`/api/v1/connector`) with a connector token; the API enforces ownership, validation and the read/append-only contract. Setup: `docs/connector-setup.md`.

- **Read:** `get_study_plan`, `list_courses`, `get_course_outline`, `search_sources`, `get_source_section`, `get_notes`, `get_due_reviews`, `get_attempt`
- **Append:** `start_study_session`, `create_questions`, `submit_chat_answer` (fallback), `record_assessment`, `record_session_summary`
- **MCP Apps:** `open_answer_form` renders `ui://recallspring/answer-form`, a self-contained first-party HTML form (no external scripts, `textContent` only). It saves the learner's exact text through the app-only tool `submit_answer_from_form` (`_meta.ui.visibility: ["app"]`), then posts a chat message so Claude grades it.
- Learner material is wrapped in `<learner_material>` blocks and described to Claude as data, never instructions.

Configuration: `RS_API_URL` (default `http://127.0.0.1:4318`), `RS_CONNECTOR_TOKEN_FILE` (default `%LOCALAPPDATA%\RecallSpring\connector-token`).

```bash
.venv/Scripts/python -m pip install --require-hashes -r requirements-dev.lock && .venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
```

```bash
.venv/Scripts/python -m pytest
```
