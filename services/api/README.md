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
.venv/Scripts/recallspring backup                  # database + uploaded files now, checked by a test restore
.venv/Scripts/recallspring backup-status           # last backup, kept backups, folder
.venv/Scripts/recallspring backup-restore --database <new name> --storage <empty folder>   # never overwrites
```

The worker also makes a backup when the last good one is older than 24 hours (docs/08 → Backups).

## Sources and notes

- `POST /sources` (multipart `course_id`, `file`, optional `category`) accepts PDF, Word (.docx), PowerPoint (.pptx/.ppsx), Excel (.xlsx), OpenDocument (.odt/.odp/.ods), Markdown, UTF-8 text, CSV/TSV, subtitles (.srt/.vtt), Jupyter notebooks (.ipynb), LaTeX (.tex), source code (.py, .java, .c, .js, .sql and more, see `ingest/formats.py`) and photos (PNG/JPG/WebP). Limits: 100 MiB per document, 10 MiB per text file, 20 MiB per photo, 2 GiB per library, and uploads pause (`507 storage_low`) when the disk would drop below 2 GiB free; `GET /sources/limits` reports them with the library use and the accepted extensions. The extension must match the content; originals are stored unchanged under `RS_STORAGE_DIR`, keyed by owner and SHA-256, never by filename. Identical files are flagged with `duplicate_of_id` and never merged across courses. `POST /sources/text` turns pasted text into a source.
- The worker extracts each source in a separate `python -I` process with a timeout (`RS_EXTRACTION_TIMEOUT_SECONDS`) into citable sections: PDF pages (`p. 3`), slides (`slide 5`, with speaker notes, SmartArt and tables), Markdown or Word headings (`§ Glycolysis`; Word heading styles are recognised in any Office language), spreadsheet rows (`Grades, rows 1–80`, dates formatted, hidden sheets skipped) or plain-text parts; OpenDocument like Office (`ingest/odf.py`); CSV rows (`rows 1–80`, Windows-1250 is accepted and reported as `decoded_as`), subtitles by time (`05:00–10:00`, speakers kept, styling and rolling duplicates dropped), notebooks by Markdown heading (code fenced with its language, outputs as text, HTML skipped, output pictures as `[picture N]`), LaTeX by `\section` (comments dropped, macros kept, unresolved `\input` reported), code by lines (`lines 1–80`, language as heading). Office files are read with the standard library only (`ingest/office.py`): the ZIP index is checked first, part sizes are capped, XML with DTD/entity declarations is refused, and macros, embedded objects and pictures are never opened. Old `.doc/.ppt/.xls`, macro-enabled and template files are refused with a "save as .docx/.pptx/.xlsx" hint; password-protected files with `office_protected`.
- `GET /connector/sources/{id}/visual?page=&picture=` lets Claude look at what text can't carry: a PDF page rendered with PDFium (`pypdfium2`) to PNG (longest side 1568 px, ≤ 3.5 MB; grayscale and smaller sizes are tried first), a whole slide or page of an Office/OpenDocument file when LibreOffice is installed (`whole_page: true`; `RS_OFFICE_RENDERER=auto|off`, `RS_OFFICE_RENDERER_PATH`), the pictures on a slide, or picture N of a document or notebook (`[picture N]` marks it in the text). Pictures are passed on unchanged when they are PNG/JPEG/GIF/WebP within 4.5 MB and 8000 px; TIFF, BMP and oversized ones are converted by Pillow (`converted: true`); vector drawings (EMF/WMF/SVG) are reported and appear on the whole-slide render. `GET /connector/sources/{id}/image` sends large photos as a smaller JPEG. Rendering runs in a separate `python -I` process with the extraction timeout (`ingest/visuals.py`). Scanned PDFs fail with `no_extractable_text`; partly scanned ones are `needs_attention` with the page list. Nothing is invented: questions, concepts and assessments may cite only real section IDs of the same course.
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
| `RS_DEFAULT_TIMEZONE` | `UTC` | Time zone for `create-owner` without `--timezone` (the first-run page uses the browser's) |
| `RS_FIRST_RUN_ENABLED` | `true` | The first-run page may create the first account (only from this computer, only while none exists; always off in production) |
| `RS_BACKUP_DIR` | `local-data/backups` | Same disk as the uploads by default: point it at another disk or a synced folder. A folder chosen in Settings replaces it |
| `RS_BACKUP_SETTINGS_FILE`, `RS_BACKUP_SETTINGS_FROM_WEB` | `local-data/backup-settings.json`, `true` | Where the folder chosen in Settings is kept; `false` keeps the folder to the server settings |
| `RS_BACKUP_ENABLED` | `true` | Automatic backups by the worker |
| `RS_BACKUP_EVERY_DAYS`, `RS_BACKUP_TIME` | `1`, `03:00` | Schedule in the first account's time zone (Settings → How often replaces it) |
| `RS_BACKUP_KEEP_DAILY`, `RS_BACKUP_KEEP_WEEKLY` | `7`, `4` | Daily backups: newest per day / per week kept |
| `RS_BACKUP_KEEP_LAST` | `7` | Less frequent backups: how many are kept |
| `RS_BACKUP_PG_BIN` | unset | Folder with `pg_dump`/`pg_restore` (else `PATH`, else the dev container in development) |

## Rollback notes

Migrations are applied with `alembic upgrade head`; `alembic downgrade -1` reverts the latest. Revision `0001` is the initial schema: downgrading it drops all tables and data, so back up first (`recallspring backup`). Later migrations must preserve data and be released separately from application changes.
