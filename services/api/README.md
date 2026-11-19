# RecallSpring API

FastAPI backend: owner authentication, courses/topics/concepts, questions, persist-first attempts, append-only assessments, deterministic review scheduling and pluggable in-app AI (Mode B). OpenAPI: `GET /api/v1/openapi.json` (interactive docs at `/api/v1/docs` outside production).

## Setup (Windows paths; use `.venv/bin/` on macOS/Linux)

```bash
# from the repository root: start the local database (127.0.0.1:55432 only)
docker compose -p recallspring-dev -f infra/compose.dev.yml --env-file infra/.env up -d

cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r requirements-dev.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env          # then put the password from infra/.env into RS_DATABASE_URL
.venv/Scripts/alembic upgrade head
```

## Everyday commands

```bash
.venv/Scripts/python -m pytest                     # full suite against recallspring_test
.venv/Scripts/ruff check src tests migrations && .venv/Scripts/ruff format src tests
.venv/Scripts/recallspring create-owner --username <name>   # password is prompted; no public sign-up
.venv/Scripts/recallspring seed-demo --username <name>      # labelled demo course
.venv/Scripts/uvicorn recallspring_api.main:app --host 127.0.0.1 --port 4318
.venv/Scripts/recallspring worker                  # second terminal: extracts uploaded sources (no model calls)
.venv/Scripts/recallspring worker --once           # process queued jobs and exit
```

## Sources and notes

- `POST /sources` (multipart `course_id`, `file`) accepts PDF, Markdown and UTF-8 text up to 30 MiB (library 250 MiB). The extension must match the content; originals are stored unchanged under `RS_STORAGE_DIR`, keyed by owner and SHA-256, never by filename. Identical files are flagged with `duplicate_of_id` and never merged across courses. `POST /sources/text` turns pasted text into a source.
- The worker extracts each source in a separate `python -I` process with a timeout (`RS_EXTRACTION_TIMEOUT_SECONDS`) into citable sections: PDF pages (`p. 3`), Markdown headings (`§ Glycolysis`) or plain-text parts. Scanned PDFs fail with `no_extractable_text`; partly scanned ones are `needs_attention` with the page list. Nothing is invented: questions, concepts and assessments may cite only real section IDs of the same course.
- Notes autosave with `PATCH /notes/{id}` and `base_revision`. A stale save returns `409 revision_conflict` with the current version, and the rejected draft is kept as a `conflict` revision, so both versions survive until you resolve them.

## Write requests

Every mutating request needs the session cookie, an `X-CSRF-Token` header equal to the `rs_csrf` cookie, and an `Idempotency-Key` UUID. Replaying a key returns the stored response (`Idempotent-Replay: true`); reusing it for a different body returns `422 idempotency_key_reused`. `POST /attempts` is additionally deduplicated by `client_request_id`. Errors use `{code, message, request_id, details?}` and never echo submitted text.

## Persist-first evaluation

1. `POST /attempts` commits the exact answer and returns `201 {attempt_id, status: "saved_awaiting_evaluation", saved_at}`.
2. `POST /attempts/{id}/evaluate` claims the attempt, calls the configured provider outside any transaction, validates the output against `packages/contracts/schemas/assessment.schema.json` and the evidence that was served, and appends an assessment. On timeout, outage or invalid output it returns `503 evaluation_unavailable` and the attempt stays `saved_awaiting_evaluation` for a later retry.
3. `POST /assessments/{id}/challenge` records disagreement; with `corrected_grade` it appends a human assessment and recomputes the schedule.

## Configuration (`RS_*` environment variables or `.env`)

| Variable | Default | Notes |
|---|---|---|
| `RS_DATABASE_URL` | local dev URL without password | Required; secrets only in `.env` (gitignored) |
| `RS_COOKIE_SECURE` | `true` | `false` only for plain-HTTP loopback development |
| `RS_AI_EVALUATION_PROVIDER`, `RS_AI_QUESTION_PROVIDER` | `none` | `mock` for development; real adapters follow ADR-002 |
| `RS_AI_TIMEOUT_SECONDS` | `90` | Provider call timeout |
| `RS_DEFAULT_TIMEZONE` | `Europe/Ljubljana` | New users' timezone |

## Rollback notes

Migrations are applied with `alembic upgrade head`; `alembic downgrade -1` reverts the latest. Revision `0001` is the initial schema: downgrading it drops all tables and data, so back up first. Later migrations must preserve data and be released separately from application changes.
