# ADR-001 — Repository layout, backend stack and tooling

- **Status:** Accepted (implementation choice within the build pack), 2026-11-19

## Decision

- **Separate repository** `recallspring/`; the private build pack (with `private/`) stays outside it. Initial spec import commit, then work on branches (`opus/*` for the backend lead, `sol/*` for the frontend lead).
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x (synchronous ORM over psycopg 3), Alembic. Sync endpoints run in FastAPI's threadpool; endpoints that wait on an AI provider are `async` and run their database phases in the threadpool so no transaction stays open during a model call.
- **Dependencies:** `requirements.in` → `requirements.lock` with hashes (`pip-compile --generate-hashes`); dev tools in `requirements-dev.lock`, constrained to the runtime lock. Install with `pip install --require-hashes`.
- **Database:** PostgreSQL 16 only (partial indexes, `SKIP LOCKED` jobs and JSONB are used; no SQLite fallback). Local development uses `infra/compose.dev.yml`, bound to `127.0.0.1:55432`. Connections use `timezone=UTC`.
- **Tests:** pytest against a real PostgreSQL database `recallspring_test`, recreated and migrated with Alembic per run and truncated between tests; a separate test checks upgrade/downgrade and that the ORM model has no drift from the migrations. Time is injected through `recallspring_api.clock.now` so scheduling tests are deterministic.
- **Lint/format:** ruff (`ruff check`, `ruff format`), line length 120.
- **Ports (local):** API `127.0.0.1:4318`, web `127.0.0.1:4317`, dev DB `127.0.0.1:55432`. Never 3000/8000.

- **Ingestion:** `pypdf` (BSD) rather than PyMuPDF (AGPL) for PDF text. Extraction runs in a separate `python -I` process with a wall-clock timeout so a malicious or broken file cannot hang or crash the worker; jobs live in PostgreSQL (`SKIP LOCKED`, leases, bounded retries with backoff) — no Redis.

## Consequences

- Windows offers no per-process memory cap for the extractor; in container deployments the worker's memory limit bounds it. OCR remains out of scope.
- An uploaded blob is written before the database commit; if the commit fails an unreferenced blob may remain (content-addressed, harmless; a later cleanup job can remove orphans).

- Login rate limiting is in-process; it assumes a single API worker (true for the single-user deployment). Revisit if more workers are ever run.
- `starlette.testclient` warns that `httpx` support is deprecated in favour of `httpx2`; switch when FastAPI's test client does.
- The first migration's downgrade drops every table. Later migrations must be data-preserving and shipped separately from app rollouts (AGENTS.md).
