# AGENTS.md — RecallSpring Non-Negotiable Agent Instructions

Applies to **Claude Opus, Sol, Codex and every delegated coding agent**. These constraints override convenience, speed, and speculative optimizations.

## Mission

Implement RecallSpring per `README.md` and the `docs/` specifications. It is a self-hosted, open-source, **English UI** study companion using **Hybrid Learning**: the learner drives new learning; the app autonomously administers spaced repetition, tracks mastery, evaluates attempts and suggests weak-area exercises. Preserve the **Sage Study** light-first visual identity.

## Safety critical: ProtectedApp uptime

*ProtectedApp* is the codename for an existing production application that runs on the same server RecallSpring may later be deployed to. Its real name, containers and locations are only in the private operator snapshot, never in this repository.

1. **ZERO PLANNED PROTECTEDAPP DOWNTIME**. Never stop, restart, rebuild, pause, rename, remove, prune volumes for, or recreate ProtectedApp's containers.
2. Never edit the existing ProtectedApp application files, Compose config, database, volumes, environment, Docker networks or enabled Nginx site; see the private operator snapshot for precise locations.
3. No `docker compose down` from an ambiguous directory; no `docker system prune -a`, `docker volume prune`, `docker network prune`, broad Docker cleanups, or blanket host firewall changes.
4. Development **first on a local machine / isolated branch**, never live production by default. No SSH/deployment action to the VPS without explicit owner approval for that exact step.
5. Separate app directory `/opt/recallspring`, Compose project name `recallspring`, separate names/volumes/ports/networks; no host-network mode, privileged containers, or mounting the Docker socket.
6. Before any authorized deployment: capture baseline ProtectedApp health, system resource metrics, compose projects, existing Nginx config; compare after; stop rollout on any regression. Host proxy change must be additive, syntactically validated and gracefully reloaded only after owner approval.
7. Use resource bounds and refuse installation below agreed disk/memory gates. Building large images on the VPS is discouraged: prefer prebuilt pinned artifacts after isolated testing.

## Product critical

- Never force users to manage review cards, folders, or intervals manually.
- Persist raw learner input **before** model inference. Keep source/evidence links for generated content, and record assessment explanations and confidence.
- The AI must never fabricate evidence from uploaded material. If unsupported, say so and mark the grade provisional or ungraded.
- Do not interpret AI-graded mastery as a validated psychometric score.
- Deleted data requires explicit confirmation; use reversible soft-delete and audit for a retention period. Never ask the LLM to mutate records directly without server-side permission checks.
- All UI copy English; all sources and learner content may be in any language. Never automatically translate original notes without consent.
- Strict allowlisted visual JSON components. **Do not execute model-generated HTML, JS, CSS, SQL, shell code, or templates.** RecallSpring's own static MCP App UI (e.g. the connector answer form) is first-party code reviewed like any frontend code and never embeds model-generated markup or scripts.
- Accessible, keyboard-friendly, responsive, light mode default. User can decide if visual aids are useful; avoid decoration over learning value.

## AI integration critical (revised 2026-11-19 by owner decision — see `docs/adr/002-ai-provider-architecture.md`)

AI is pluggable and optional. The non-AI core (sources, notes, scheduling, planning, review queue) must always work.

- **Mode A — Claude connector (the owner's primary path).** The learner studies in the official Claude app (Claude Desktop first) on their own Claude plan; RecallSpring is an MCP server exposing typed, authorized tools. RecallSpring never obtains, stores, proxies or requests Claude.ai credentials or session tokens, and never sends model requests on the learner's Claude plan itself.
- **Mode B — in-app AI providers** behind the `LLMProvider` interface: official OpenAI *Sign in with ChatGPT* (SIWC), the Anthropic Claude API with an owner-provided API key (official `anthropic` SDK only), and later OpenAI-compatible/custom LLMs. Provider and model are chosen per task and can be overridden per course or session.
- Never scrape cookies or session tokens, never call reverse-engineered internal endpoints, never route requests through another person's account or plan.
- API keys and OAuth credentials are owner-controlled secrets in protected server-side storage only; never in Git, client JS, logs, error traces, images, CI artifacts, exports or plaintext database columns.
- Paid usage needs an owner-set hard limit: a monthly USD limit for API-key providers; a daily AI-request limit (1–100 % of the default) for plan-based providers. Never silently switch provider or model, and never fall back from plan-based to billable usage.
- SIWC: HTTP requests use `store: false`, `stream: true`, complete history in `input` and officially supported fields only. Do **not** assume a ChatGPT plan grants unrestricted models, volume, native ChatGPT visuals or hosted tools. Revalidate the official docs on implementation day.
- Background LLM requests (no user action) require separate affirmative opt-in, OFF by default, for every provider. Deterministic scheduling without model calls may run automatically. User-initiated calls are the default.
- Connector tools may read learning data and append records. They must never delete, finalize deletions, modify source documents, change budgets or consent, or bypass server-side validation (schema, evidence references, ownership).
- Quota exceeded / revoked authorization / disconnection => clear UI status, save drafts and queue deterministic work.

## Engineering discipline

- Work in small PRs/commits; explain changes; add tests and documentation; separate data migrations from app rollout.
- Never commit secrets, private documents, actual learner data, OAuth tokens, or VPS identity/private keys.
- All API access authorized. Use CSRF protection where relevant, rate limits, audit logs, least privilege, dependency lockfiles and input-size bounds.
- No destructive or infrastructure-affecting change without an explicit owner checkpoint. Never claim zero downtime is guaranteed; demonstrate that ProtectedApp was not touched and create rollback procedures.
- Stop and request a focused decision ONLY when a material requirement truly blocks safe progress; otherwise use documented assumptions in `docs/10-DECISIONS-AND-RISKS.md` and implement to a testable baseline.

## Definition of done for each feature

Source-aware tests + UI behavior + API error handling + auditability + migration/rollback + operational notes + no regressions to owner uptime constraints.
