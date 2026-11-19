# RecallSpring

**Your personal AI learning companion.** A self-hosted, single-user-first study app using *Hybrid Learning*: you drive new learning (sources, notes, questions you ask for); RecallSpring administers spaced review, tracks evidence of mastery and plans your next session — no flashcard or calendar busywork.

> Status: **early development (Gate 0 / M1)**. Not ready for production use.

## Repository layout

```text
AGENTS.md                 Non-negotiable rules for every coding agent
docs/                     Product, architecture and safety specification (01–10)
docs/adr/                 Architecture decision records
docs/agent-briefs/        Briefs for the implementing agents
packages/contracts/       Shared JSON schemas (assessment, visual blocks)
services/api/             FastAPI backend, migrations, tests, SIWC client
infra/compose.dev.yml     Local development database (loopback only)
```

## Local development (Windows / macOS / Linux)

Requirements: Python 3.12+, Docker (for PostgreSQL), Node 22+ (frontend, later).

```bash
# 1. Start the local dev database (binds to 127.0.0.1 only)
docker compose -p recallspring-dev -f infra/compose.dev.yml --env-file infra/.env up -d

# 2. Backend
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.lock   # Windows
.venv/Scripts/python -m pip install --no-deps -e .
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m pytest
```

See `services/api/README.md` for configuration, the owner-account CLI and the demo seed.

## AI integration

RecallSpring uses **official Sign in with ChatGPT (SIWC)** plan sharing for open-source apps — never classic API keys, never unofficial endpoints. Without a connection, every non-AI feature (notes, sources, scheduling, planning) keeps working. See `docs/04-AI-INTEGRATION.md` and `docs/adr/002-siwc-integration.md`.

## License

To be decided by the owner (Apache-2.0 or AGPL-3.0 under consideration). Until then, all rights reserved.
