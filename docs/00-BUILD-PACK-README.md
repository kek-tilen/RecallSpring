# RecallSpring — Agent Build Pack

**Status:** implementation-ready specification, **not** a completed application.  
**Date:** 2026-11-19  
**Language:** English in the product, developer artifacts, UI, and system messages.  
**Project:** RecallSpring (working public name accepted by owner; domain/trademark not verified).

> **Prime directive:** Build an intuitive AI learning companion that takes care of learning administration so the learner can concentrate on understanding. **Never interrupt, restart, rebuild, reconfigure, or delete anything belonging to ProtectedApp.**

## What to read, in order

1. `AGENTS.md` — non-negotiable rules for every coding agent.
2. `docs/01-PRODUCT-REQUIREMENTS.md` — scope, user journeys, acceptance criteria.
3. `docs/02-ARCHITECTURE.md` — technologies, boundaries, process design.
4. `docs/03-DATA-CONTRACT.md` — model, evidence, storage, sync.
5. `docs/04-AI-INTEGRATION.md` — Sign in with ChatGPT eligibility and technical gate.
6. `docs/05-LEARNING-ENGINE.md` — Hybrid Learning, Bloom, memory and assessment logic.
7. `docs/06-UX-DESIGN.md` — Sage Study light UI, visual learning components.
8. `docs/07-API-AND-VISUAL-CONTRACT.md` — endpoint and rendering schemas.
9. `docs/08-SECURITY-OPERATIONS.md` — safe deployment and data protection.
10. `docs/09-DELIVERY-AND-TESTS.md` — ordered work packages and test gates.
11. `docs/10-DECISIONS-AND-RISKS.md` — approved decisions vs explicit unknowns.
12. `prompts/OPUS-LEAD.md` and `prompts/SOL-IMPLEMENTATION.md` — ready-to-paste agent briefs.

## Goal and scope

A **self-hosted, single-user-first**, open-source, English-language web app with a mobile-friendly Progressive Web App frontend. A conversational AI tutor supports reading, explanations and **interactive visuals only when pedagogically valuable**. The learner retains control over acquiring and writing new material. A deterministic learning engine tracks concepts, evaluates learner attempts with AI assistance, and automatically prepares spaced reviews, weak-area checks and a next-session plan. Notes, original answers, source links, evaluations, and scheduling events must persist **during the session**, not only at the end.

Avoid copying ChatGPT's internal UI or claiming its visual components are portable. We build our own safe React visual renderer. Avoid an Anki-style manually maintained card workflow.

## Known environment — keep private

The owner has a resource-constrained Linux VPS that also hosts the protected **ProtectedApp** behind a reverse proxy. **Do not copy server identity, internal filenames or actual topology into the public source repository.** Detailed owner-provided observations are in `private/INFRASTRUCTURE-OWNER-ONLY.md`, intentionally excluded by `.gitignore`. Recheck all capacity and services before any authorized deployment.

## Implementation approach

- React + TypeScript + Vite, accessible component library and CSS design tokens.
- FastAPI (Python) + PostgreSQL; same Python image for lightweight async jobs with a separate worker process; no Redis, Kubernetes, vector DB, or local LLM for v1.
- Docker Compose project `recallspring` with **new project-owned** services, volumes, private Docker network.
- Host Nginx reverse-proxies a **loopback-only** new service endpoint once owner approves a new domain and HTTPS setup. Never use ports 3000 or 8000.
- AI provider adapter: official **Sign in with ChatGPT (SIWC)** plus authorized Responses API requests where permitted. **No LLM API keys**. Gate this with a real proof-of-concept before building dependent AI functionality.
- All learning records belong to RecallSpring's database. Conversation history is stored by the app, **not imported from ChatGPT**.

## Public/private split

This build pack is delivered privately to the implementing agents. The open-source code repository may include the safe product/technical specifications, but **must exclude `private/`, credentials, host identity, real personal study data and operational logs**. Review all files before publishing.

## Delivery order

**Gate 0:** Technical feasibility and safety (disk, firewall, OAuth/model availability).  
**Gate 1:** Local vertical slice (upload -> concept -> tutoring prompt -> attempt -> stored evaluation -> due review).  
**Gate 2:** UX, visual renderer and offline-capable draft sync.  
**Gate 3:** Security tests, backup/restore drill, supervised staging rollout.  
**Gate 4:** Explicit owner authorization before any production-facing Nginx / DNS changes.

## Sources and changing constraints

This pack encodes current official SIWC limitations as of **2026-11-19**. Revalidate on implementation day:
- https://developers.openai.com/siwc/quickstart
- https://developers.openai.com/siwc/token-sharing-open-source
- https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://openai.com/policies/sign-in-with-chatgpt-terms/
- https://docs.docker.com/engine/network/packet-filtering-firewalls/
- https://docs.docker.com/engine/manage-resources/pruning/

If these terms no longer permit the intended architecture, **stop at Gate 0, report the mismatch, and request an owner-approved new design**. Do not silently substitute unofficial interfaces, browser session scraping, shared subscription credentials, or pay-as-you-go API keys.
