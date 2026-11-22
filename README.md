# RecallSpring

**Your personal AI learning companion.** A self-hosted, single-user-first study app using *Hybrid Learning*: you drive new learning (sources, notes, questions you ask for); RecallSpring administers spaced review, tracks evidence of mastery and plans your next session — no flashcard or calendar busywork.

> Status: **early development (Gate 0 / M1)**. Not ready for production use.

## Repository layout

```text
AGENTS.md                 Non-negotiable rules for every coding agent
apps/web/                 Web app: overview of everything RecallSpring stores — see apps/web/README.md
docs/                     Product, architecture and safety specification (01–10)
docs/adr/                 Architecture decision records
docs/agent-briefs/        Briefs for the implementing agents
packages/contracts/       Shared JSON schemas (assessment, visual blocks)
services/api/             FastAPI backend, migrations, tests, AI provider adapters
services/mcp/             Claude connector (MCP server) for Claude Desktop — see docs/connector-setup.md
scripts/install.ps1       Install or update RecallSpring on Windows — see docs/install-windows.md
scripts/start-local.ps1   Start the local database, API (serves the web app) and worker in the background;
                          -Status / -Restart / -Stop
scripts/logs.ps1          Show the API log (-Worker: the worker log) from local-data/logs
infra/compose.dev.yml     Local development database (loopback only)
```

## Install (Windows)

For your own computer: install Python 3.12+, Node 22+ and Docker Desktop, then run
`powershell -ExecutionPolicy Bypass -File scripts\install.ps1` and open `http://127.0.0.1:4318/`. The first visit
creates your account and asks which assistant you study with (Claude, Codex, Google Antigravity or ChatGPT in RecallSpring). Full guide:
[docs/install-windows.md](docs/install-windows.md).

## Local development (Windows / macOS / Linux)

Requirements: Python 3.12+, Docker (for PostgreSQL), Node 22+ (web app).

```bash
# 1. Start the local dev database (binds to 127.0.0.1 only)
docker compose -p recallspring-dev -f infra/compose.dev.yml --env-file infra/.env up -d

# 2. Backend (Windows paths; use .venv/bin/ on macOS/Linux)
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r requirements-dev.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env    # set the password from infra/.env
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m pytest
```

Copy `infra/.env.example` to `infra/.env` with a random password first.

```bash
# 3. Web app (served by the API at http://127.0.0.1:4318/)
cd apps/web
npm ci
npm run build
```

On Windows `scripts/start-local.ps1` starts the database, API and worker; the API and worker run in the background
without a window and log to `local-data/logs` (`scripts/logs.ps1`, `-Status`). Run it with `-Restart` after updating
the code. Then open `http://127.0.0.1:4318/`: on a new install the first visit creates the account (this computer only),
afterwards it is the sign-in.

While the worker runs it backs up the database and your uploaded files once a day into `local-data/backups` (checked
by a test restore; Settings → Backups). That folder is on the same disk: set `RS_BACKUP_DIR` to another disk or a
synced folder for real protection. Restore steps: docs/08 → Backups.

See `services/api/README.md` for configuration, the owner-account CLI and the demo seed.

## AI integration

AI is pluggable and optional:

- **Mode A — Claude connector:** study in the official Claude app (Claude Desktop) on your own Claude plan; RecallSpring is an MCP connector that Claude uses to read your plan and sources and to record questions, answers and assessments.
- **Mode B — in-app providers:** OpenAI *Sign in with ChatGPT*, the Anthropic API with your own key and a hard monthly USD limit, and later OpenAI-compatible/custom models.

Only official integration routes are used; no consumer credentials are ever stored. Without any AI connection every non-AI feature (sources, notes, scheduling, planning) keeps working. See `docs/04-AI-INTEGRATION.md` and `docs/adr/002-ai-provider-architecture.md`.

## License

Copyright (C) 2026 Kek Tilen. Questions: kektilen@proton.me

RecallSpring is free software under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only).
You may use, study, change and share it; if you change it and let others use it over a network (for example as a
hosted study service), you must offer them the source code of your version under the same license. The license is
the first commit of the repository, so it applies to every commit.
