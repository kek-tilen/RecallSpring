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
services/api/             FastAPI backend, migrations, tests, AI provider adapters
services/mcp/             Claude connector (MCP server) — planned
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

AI is pluggable and optional:

- **Mode A — Claude connector:** study in the official Claude app (Claude Desktop) on your own Claude plan; RecallSpring is an MCP connector that Claude uses to read your plan and sources and to record questions, answers and assessments.
- **Mode B — in-app providers:** OpenAI *Sign in with ChatGPT*, the Anthropic API with your own key and a hard monthly USD limit, and later OpenAI-compatible/custom models.

Only official integration routes are used; no consumer credentials are ever stored. Without any AI connection every non-AI feature (sources, notes, scheduling, planning) keeps working. See `docs/04-AI-INTEGRATION.md` and `docs/adr/002-ai-provider-architecture.md`.

## License

To be decided by the owner (Apache-2.0 or AGPL-3.0 under consideration). Until then, all rights reserved.
