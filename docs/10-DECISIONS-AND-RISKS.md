# 10 — Decision Log, Open Questions and Risk Register

## Approved owner decisions

| Decision | Status |
|---|---|
| Project name **RecallSpring** | Accepted |
| UI and system messages in English | Required |
| **Sage Study**, white/light-first theme | Required |
| Open-source code acceptable | Accepted; license TBD |
| **Hybrid Learning** | Required: new-learning user-led, follow-up/reviews AI-administered |
| Full process: sources -> notes -> tutor -> Bloom 3–5 -> reviews -> insights | Required |
| Meaningful visual explanations | Required, own safe renderer acceptable |
| Automatic background record-keeping | Required |
| Destructive actions need explanation and confirmation | Required |
| Existing ProtectedApp must **not** be interrupted | Absolute deployment constraint |
| Use Opus and Sol as development agents | Owner's intended workflow; Opus builds backend first and publishes the OpenAPI contract, Sol joins later on a separate branch |
| **AI architecture (2026-11-19):** Mode A = Claude connector (MCP) used from the official Claude app on the owner's own Claude plan; Mode B = optional in-app providers (SIWC, Anthropic API key, later custom LLMs) | Approved; **replaces "no classic LLM API keys"** — see ADR-002 |
| Tutor model: Sonnet by default, switchable to Opus (or another model) per course/session for demanding material | Approved |
| Limits: Anthropic API key → monthly **USD** limit only; plan-based providers and connector → daily AI-request limit 1–100 % of default | Approved |
| SIWC: keep SIWC as an in-app provider for the owner and for other self-hosters | Approved; built after Mode A |
| Sending notes, answers and source excerpts to the chosen AI provider (incl. Anthropic) | Accepted by owner |
| Delivery order: non-AI core + local Claude connector first, then SIWC | Approved |
| Desktop-first: one computer; phone use dropped for now | Approved |
| Hosting: local on the owner's computer first; user-controlled existing Linux VPS later | Preferred |
| Code repository: separate `recallspring/` repo; private build pack stays outside it | Approved |
| Tutor replies in the language of the learner's question/material by default (UI stays English) | Approved |
| Test material: synthetic fixtures (biology, programming); real material optional and never committed | Approved |
| Study targets: a session first asks what the learner prepares for (1st/2nd kolokvij or exam, whole or part), from which material to which, old kolokvij, specifics | Approved 2026-11-19 (ADR-005) |
| Passed kolokvij material → maintenance (reviews kept, lower priority); new material first, especially in the exam period | Approved 2026-11-19 |
| Old kolokvij papers (text or scans) shape question style and topic priority; 75 % past-paper style / 25 % deeper | Approved 2026-11-19 |
| Default study time 60 min weekdays / 90 min weekends; maintenance share 15 % | Approved 2026-11-19 |
| Kolokvij simulations in a RecallSpring form (MCQ + open), stored in RecallSpring; Claude's own chat widgets do not count as evidence | Approved 2026-11-19 |
| Claude Projects: one per course + one Overview project (templates in `docs/claude-projects.md`) | Approved 2026-11-19 |
| Organisation: university › faculty › semester groups; archiving a semester archives its courses (reversible), archived courses keep due reviews as maintenance when long-term retention is on | Approved 2026-11-20 |
| Web app edits exams/kolokviji (drag on a timeline or type a date, result, scope) and course colours from a fixed validated palette; simulations can be answered in the web app, open answers wait for Claude (ID to copy) | Approved 2026-11-20 |
| Photos of notes, notebooks and exercises are kept as material (PNG/JPG/WebP, no OCR); Claude looks at them on request via the connector (≤ 4.5 MB; the web app shrinks larger photos before upload) | Approved 2026-11-20 |
| Calendar: exams export as an .ics download (no public subscription URL while local-only) | Approved 2026-11-20 |
| Sharing with others | Deferred (owner in chat) |
| Web app = overview of everything stored (plan, courses, exams, concepts, reviews, simulations, material, notes, history, settings) in the Sage Study palette; studying stays in Claude. Served same-origin by the API from `apps/web/dist` with a strict CSP | Approved 2026-11-19 |
| Learning first: teach new material (explain, own-words summary, short checks) before practice or simulations; server refuses practice on unstudied concepts; diagnostics only on request and never affect reviews | Approved 2026-11-19 (ADR-006) |

## Working assumptions (do not mistake for owner approval)

- Single-user app first; app login uses local credentials (Argon2id + optional TOTP) independent of any AI provider, no public self-signup.
- Deployment subdomain not chosen. Do not buy/register a domain or issue certificates automatically. Remote Claude connector (web/mobile) waits for domain + HTTPS.
- Initial support for PDF with extractable text and Markdown/plain text; OCR and audio are later features.
- Device sync = the browser's offline draft outbox plus sync to the RecallSpring server; no automatic filesystem mirroring.
- Backend FastAPI/Python, React/TypeScript, PostgreSQL and Docker Compose based on resource and developer productivity; can change only with documented rationale (ADR-001).
- Default spaced intervals and mastery bands are an explainable heuristic, not a scientific certification (ADR-003).
- Default daily plan 20 minutes, editable. Default timezone Europe/Ljubljana, editable.
- Source deletion soft-delete window 30 days proposed; subject to owner's final preference and legal/privacy policy.
- "Topic" in API/notes means a `syllabus_item`; "teacher correction" means the owner's own manual grade correction.

## Owner choices needed before production, not blockers for local development

1. FQDN and DNS access (e.g. `study.example.com`) + certificate method (also unlocks the remote Claude connector).
2. Preferred off-VPS encrypted backup location and retention policy.
3. Final open-source license (Apache-2.0 vs AGPL-3.0).
4. Before enabling SIWC on a remotely hosted instance: clearance from OpenAI (its docs scope the open-source path to open-source and locally hosted apps; remote/paid apps → interest form).
5. Whether to add an Anthropic API key (Mode B with Claude) and its monthly USD limit.
6. Initial upload/storage quota and anticipated annual source volume.
7. Access restrictions for a VPS instance: internet login from anywhere versus VPN-only.

## Risk register

| ID | Severity | Risk | Mitigation / gate |
|---|---|---|---|
| R1 | High | Claude app changes connector/MCP Apps support or plan limits; SIWC preview changes | Core works without AI; transcription fallback for answer capture; adapters isolated; revalidate docs per release |
| R2 | Critical | RecallSpring deploy harms ProtectedApp | Local-first; isolation, hard no-touch rule, separate project, staged owner approval, health baseline |
| R3 | High | Low free disk on the VPS creates outages | Owner-approved build cache cleanup, >=10 GiB free launch gate, offsite backup, quotas |
| R4 | High | Docker-published ports can bypass the host firewall | External exposure audit; no new 0.0.0.0 binds; existing app fixes separately approved |
| R5 | High | Provider secrets (API key, SIWC tokens) or connector tokens mishandled | Server-side protected files, hashed connector tokens with scopes, no logging, audit, revoke controls |
| R6 | High | AI hallucination or misleading grading | Evidence refs validated against served sections, provisional marks, human correction, gold-set tests |
| R7 | High | Lost learner input | Persist-first attempts, idempotency, local draft outbox, restore drills |
| R8 | Medium | Review algorithm optimizes score not durable recall | Transparent schedule, revisit post-exam, future empirical tuning, manual override |
| R9 | Medium | Visuals become distracting/inaccurate | Intent-based visual choice, allowlist, caption provenance, plain fallback |
| R10 | Medium | Multi-user expansion violates provider terms | Single-user-first; each self-hoster uses their own plan/key; terms review before any SaaS |
| R11 | High | No HTTPS currently on the VPS | No public credentials/OAuth/connector until DNS, cert and TLS validated |
| R12 | Medium | Increased CPU/RAM causes collateral performance degradation | Container limits, no local model, low concurrency, metrics and rollback |
| R13 | High | Unexpected API cost (Mode B with a key) | Hard monthly USD limit enforced before each call, usage ledger, Console spend limit, no silent model switch |
| R14 | High | Prompt injection in sources steers connector tools | Read/append-only tool surface, untrusted-content wrapping, server-side validation, audit |
| R15 | Medium | Answer stored non-verbatim when Claude transcribes it | MCP App answer form as default; `captured_via` flag; learner can check stored text |

## Gate 0 research log (2026-11-19)

**Anthropic (Claude):**
- Claude Code legal & compliance page: OAuth (Free/Pro/Max) is for Claude Code and Anthropic's native apps; developers building products (incl. with the Agent SDK) should use API keys; third parties may not offer Claude.ai login or route requests through consumer-plan credentials, nor store or intermediate Claude.ai credentials. → RecallSpring cannot call Claude on the owner's plan itself; Mode A keeps the official app as the client.
- Claude plans do not include API usage; the API is billed per token to a separate Console organization.
- Custom connectors (remote MCP) are available on Pro and Max; Claude connects to remote connectors from Anthropic's cloud (needs a public endpoint). Claude Desktop also runs local MCP servers.
- MCP Apps (interactive UI in chat) supported in Claude and Claude Desktop since 2026-01-26.
- API data retention: inputs/outputs deleted within 30 days by default, with exceptions (longer-retention services such as the Files API, separate agreements, Usage Policy enforcement — up to 2 years for flagged content — and legal requirements). Training-use policy for API data to be confirmed from the commercial terms before Mode B with Claude is enabled.

**OpenAI SIWC (open-source token sharing):** facts summarized in `docs/04` → Adapter `siwc`. Additional notes: open-source path available to all open-source partners with dynamic registration (no client secret); the docs scope it to open-source and locally hosted apps; Plus 5-hour usage limit is shared across all apps; the terms page returned HTTP 403 to automated fetch and must be read manually.

**Gate status:**
- Mode A: automated end-to-end run **PASS** on 2026-11-19. The real API and the real MCP server over stdio completed the full loop: plan → question → form submission (exact text saved) → assessment → next review; a second grade was rejected. The run used an in-process MCP client, not Claude Desktop. **Pending: the owner's test in Claude Desktop**, which must show that the answer form renders.
- SIWC: research done, proof pending (after Mode A).
- Anthropic API: not planned until the owner adds a key.

## Decision process for changes

Agents may make reversible local implementation choices. They must create a lightweight ADR (`docs/adr/NNN-...md`) for substantive departures from this pack and obtain owner consent for breaking changes, provider policy violations, paid service, production configuration updates, destructive data operation or possible ProtectedApp disruption.
