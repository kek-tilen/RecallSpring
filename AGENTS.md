# AGENTS.md — RecallSpring Non-Negotiable Agent Instructions

Applies to **Claude Opus, Sol, Codex and every delegated coding agent**. These constraints override convenience, speed, and speculative optimizations.

## Mission

Implement RecallSpring per `README.md` and the `docs/` specifications. It is a self-hosted, open-source, **English UI** study companion using **Hybrid Learning**: the learner drives new learning; the app autonomously administers spaced repetition, tracks mastery, evaluates attempts and suggests weak-area exercises. Preserve the **Sage Study** light-first visual identity.

## Safety critical: ProtectedApp uptime

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
- Strict allowlisted visual JSON components. **Do not execute model-generated HTML, JS, CSS, SQL, shell code, or templates.**
- Accessible, keyboard-friendly, responsive, light mode default. User can decide if visual aids are useful; avoid decoration over learning value.

## AI integration critical

- No classic LLM API keys; no hardcoded credentials; no scraping ChatGPT cookies or reverse-engineered internal endpoints.
- First implement isolated SIWC proof of concept per official OpenAI documentation, using this project's approved self-hosted user-controlled VM model. The OAuth credential storage must remain under the user's control and protected; never in Git, client JS, logs, error traces, images, CI artifacts, or remote managed secret storage.
- Do **not** assume a ChatGPT subscription grants unrestricted models, volume, native ChatGPT visuals, Code Interpreter, image generation, file search, or conversation sync.
- SIWC preview HTTP responses require `store: false`, `stream: true`, complete request history in input and officially supported fields only. Check current docs before implementing.
- Background **LLM** requests require separate affirmative user consent under current SIWC terms. Deterministic server-side scheduling without model calls may operate automatically. User-initiated calls are the default.
- Quota exceeded / revoked authorization / disconnection => clear UI status, save drafts and queue deterministic work; **never silently fall back to billable API-key usage**.

## Engineering discipline

- Work in small PRs/commits; explain changes; add tests and documentation; separate data migrations from app rollout.
- Never commit secrets, private documents, actual learner data, OAuth tokens, or VPS identity/private keys.
- All API access authorized. Use CSRF protection where relevant, rate limits, audit logs, least privilege, dependency lockfiles and input-size bounds.
- No destructive or infrastructure-affecting change without an explicit owner checkpoint. Never claim zero downtime is guaranteed; demonstrate that ProtectedApp was not touched and create rollback procedures.
- Stop and request a focused decision ONLY when a material requirement truly blocks safe progress; otherwise use documented assumptions in `docs/10-DECISIONS-AND-RISKS.md` and implement to a testable baseline.

## Definition of done for each feature

Source-aware tests + UI behavior + API error handling + auditability + migration/rollback + operational notes + no regressions to owner uptime constraints.
