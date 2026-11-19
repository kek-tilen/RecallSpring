# 09 — Agent Delivery Roadmap and Acceptance Test Matrix

## Team roles and handoff

- **Opus — architecture and backend lead:** validate SIWC gate, data model and migration constraints, FastAPI/auth/learning scheduler, source retrieval and AI assessment rules, test review.
- **Sol — frontend and integration lead:** Sage Study accessible React interface, offline outbox, source/notes workspace, validated visualization components, E2E and UX quality.
- Both review each other's pull requests. Either may challenge architecture with evidence; owner retains deployment and destructive-operation approval.
- Do not run both agents against the same uncommitted branch. Use separate branches, documented interface contracts and clear PR boundaries.

## Milestones

### M0 — Feasibility and safe foundation (blocking)

- `M0.1` Re-validate SIWC access/terms and self-hosted VM token handling using up-to-date docs.
- `M0.2` Build small OAuth + model catalog + streamed `response.completed` proof, locally; log only non-sensitive results.
- `M0.3` Test revoked tokens, plan quota/error handling, and refresh behavior; document account consent.
- `M0.4` Assess VPS capacity, image footprint and ProtectedApp separation; **do not deploy**.
- `M0.5` Create git repository, license proposal, CI, lint/test, dependency pins, threat model.

**Gate:** POC works legally/technically or project AI feature is explicitly blocked pending owner decision. Do not imply first-party ChatGPT features port over.

### M1 — Durable core

- `M1.1` FastAPI project scaffold, PostgreSQL migrations, auth, `user_id` scoping and audit.
- `M1.2` Course/syllabus/exam endpoints.
- `M1.3` Upload/extract/source anchor pipeline; parse failures surfaced.
- `M1.4` Note autosave and revision history.
- `M1.5` Study sessions + append-only attempts with idempotent submission before AI.
- `M1.6` Deterministic review scheduler and daily planner with unit tests.
- `M1.7` Export + soft-delete preview/confirmation + offsite backup strategy.

**Gate:** Crash test demonstrates raw answer saved before failed inference and due review remains reproducible.

### M2 — Tutor and evaluator

- `M2.1` SIWC provider adapter behind feature flag and model picker.
- `M2.2` Source-grounded concept map (verified sections, uncertainty flags).
- `M2.3` Bloom 3/4/5 question generation with rubric; mixed/progressive modes.
- `M2.4` Transparent grading with source refs, grade 0–4/NULL and challenge flow.
- `M2.5` Tutor conversation history and SSE streaming, failed-stream recovery.
- `M2.6` Input sanitization, prompt-injection tests, source provenance benchmarks.

**Gate:** 20+ human-curated factual and analytical fixtures pass agreed acceptance threshold; no fabricated quote in gold set, uncertain items marked provisional/ungraded.

### M3 — Sage Study frontend and visuals

- `M3.1` Responsive navigation and three-action home dashboard.
- `M3.2` Source viewer + notes + tutor desktop split and mobile tabs.
- `M3.3` Review UI with due explanation and keyboard/touch support.
- `M3.4` Render safe `process_flow`, `comparison`, `timeline`, `concept_map`, `data_chart`, `interactive_parameter` from JSON schema.
- `M3.5` Loading/error/empty states, model connection state, accessibility review.
- `M3.6` PWA offline draft outbox, idempotent push and 409 conflict UI.

**Gate:** UI keyboard navigable, 2 representative phone viewports pass, visual specs invalid -> plain fallback, no arbitrary JS execution.

### M4 — Infrastructure and release

- `M4.1` Production Compose isolated and resource-limited, project name explicit.
- `M4.2` Approved external encrypted backups; restoration proof.
- `M4.3` Private loopback-only staging deploy after owner approval, ProtectedApp health baseline.
- `M4.4` Approval checkpoint for domain + HTTPS, add separate host Nginx vhost only.
- `M4.5` Simulate OAuth outage, network outage, full disk, worker crash, invalid source and quota exhaustion.
- `M4.6` Documentation, release notes, monitoring, rollback and owner signoff.

**Gate:** Production release requires security baseline, consent, disk/memory headroom and no ProtectedApp regression. No auto-deployment on commit.

## Minimal smoke tests (automate where possible)

| ID | Case | Must pass |
|---|---|---|
| T-01 | Submit answer, kill AI stream | Raw attempt survives and shows `Saved; feedback pending` |
| T-02 | Retry same idempotency key | One attempt, no duplicated reviews or grade |
| T-03 | Model returns invalid chart with script | Renderer rejects, text fallback; no JS execution |
| T-04 | Source contains 'ignore instructions' | Tutor treats it as untrusted document content |
| T-05 | Unsupported scanned PDF | Explicit parse failure/needs OCR; no invented source refs |
| T-06 | Grade 0/1 after previous success | Next review interval becomes shorter per policy |
| T-07 | Grade 4 with good evidence | Longer interval, explainable; not false 100% memory guarantee |
| T-08 | Uncertain/subjective response | Provisional/ungraded; scheduler does not over-promote |
| T-09 | Browser offline during notes | Draft in local outbox, later merges or flags conflict |
| T-10 | Two devices same note revision | 409 and both versions retained until user resolves |
| T-11 | Delete a course | Preview impacts; nothing removed before confirmation |
| T-12 | SIWC disconnect/quota exceeded | App usable for notes/scheduling, no paid fallback |
| T-13 | App restart | DB data, sources, notes, attempts and review dates persist |
| T-14 | Export and restore | Full dataset plus original source files recovered; no secrets in export |
| T-15 | Backend authorization | Cross-user access fails in test fixture even if single user in prod |
| T-16 | ProtectedApp health on private deploy | Container IDs and response baseline unchanged |
| T-17 | Compose inspection | New services have no public DB/API binds, no shared existing volumes |
| T-18 | 443 not configured | No public login goes live over HTTP |
| T-19 | Autosave crash just after acknowledged save | Latest acknowledged content recovered |
| T-20 | Background AI consent off | No model calls triggered by scheduler timer |
| T-21 | Question generation | Source-grounded, no leading hints, Bloom level appropriate |
| T-22 | Accessible visuals | Screen reader description and keyboard controls work |
| T-23 | One-step plan after exam | Long-term foundational concepts remain eligible for review |
| T-24 | DB unavailable when submitting | No false 'saved' acknowledgment; local draft retained |

## Handoffs and proof required for every milestone

- Code, migrations, tests, docs, screenshot(s) or short screen recording (UI only), reproducible local commands.
- Checklist of changed files and why each change respects ProtectedApp boundary.
- Before/after resource measurement for a VPS-targeted change, plus revert steps.
- New dependencies and service costs stated explicitly (no hidden billable LLM calls).
- Owner approval recorded before infra changes and destructive operations.

## Build order and scope control

No polishing of visual themes before the AI gate and persistence are proven. Do not implement all six visualization variants before one end-to-end validated flow works. First 'thin slice' should allow: upload example -> extract section -> select concept -> write note -> ask question -> save raw answer -> evaluate (real SIWC if gate passed, otherwise mock) -> schedule due review -> reopen and see state.
