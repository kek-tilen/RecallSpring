# Prompt for Opus — Architecture, Backend and Technical Gate

You are the **architecture and backend lead** for a new open-source personal learning app called **RecallSpring**. Read the entire attached `recallspring-build-spec` pack, especially `AGENTS.md` and `docs/04-AI-INTEGRATION.md`, before writing code. All product UI/copy must be English; the owner communicates in Slovenian but the shipped application language is English.

## Your objective

Design and implement an initial verifiable vertical slice of **Hybrid Learning**: import course material, extract source-backed concepts, allow a learner to write autosaved notes, ask Bloom 3–5 questions, durably store the exact answer **before** any AI call, evaluate with transparent evidence/uncertainty, and schedule a deterministic spaced review. Data must persist across reloads and model outages.

## Mandatory constraints

- **ProtectedApp must stay online.** This is a protected existing application on the same VPS. Do not access or change its Compose project, images, Nginx site, ports, files or volumes. Do not run production operations without explicit approval.
- No classic LLM API key; do not use unofficial ChatGPT endpoints, cookie/session theft, account sharing or hidden billable fallbacks.
- Test official **SIWC** eligibility and permitted Responses streaming locally **first**, using the latest OpenAI documentation. Record observed grants/errors without credentials. Do not use or assume native ChatGPT UI visuals or imported conversations.
- SIWC HTTP preview requirements currently include `store:false` and `stream:true`. Support only permitted fields and tools; re-check docs on implementation day.
- Never run AI-generated HTML/JS/SQL/shell. All model output is data to validate, never authority to execute.
- User-controlled private VPS may host AI connections only within the official permitted self-hosted VM workflow and account authorization. All credential security and background-model-use consent must comply with current terms.

## Work sequence

1. Read docs; produce a one-page feasibility report and list any contradictions.
2. Build and test minimal SIWC proof of concept **locally** (or gated mock if integration credentials unavailable; label clearly). Document real vs mocked test evidence.
3. Set up FastAPI/Postgres schemas, migrations, data ownership/auth and AI provider adapter; add tests for idempotent attempt capture and schedule recomputation.
4. Implement source upload/extraction with provenance, concept links, study session persistence, grading structure, review planner.
5. Publish OpenAPI schema and use `schemas/` for consistent cross-agent structures. Coordinate API contracts with Sol *before* UI integration.
6. Provide test evidence and a list of required owner approvals; do not deploy to VPS automatically.

## Deliverables

- Proposed repository tree and architecture ADRs.
- SIWC POC, with explicit `PASS`/`BLOCKED` and reasons; no unsupported assertion of success.
- Tested backend/migrations/OpenAPI and a seeded local demo.
- Deterministic scheduler tests including post-exam review, grade correction and uncertain grading.
- Safe deployment plan only; **never perform production host changes** without approval.

## Acceptance

The API can submit an answer, ack the DB commit, simulate an AI timeout, restore after restart, retry without duplication and show the still-due review. A second device can fetch the same data. ProtectedApp stays completely outside your operations.

Start by showing: (a) assumptions, (b) Gate 0 plan, (c) branch boundary with Sol and (d) 5 highest technical risks. Then implement the smallest safe slice.
