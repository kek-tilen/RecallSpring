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
| No classic LLM API keys | Required |
| Hosting: user-controlled existing Linux VPS | Preferred |
| Sync with local devices | Required; PWA drafts + cloud sync initial interpretation |
| Existing ProtectedApp must **not** be interrupted | Absolute deployment constraint |
| Use Opus and Sol as development agents | Owner's intended workflow |

## Working assumptions (do not mistake for owner approval)

- Single-user app first; app login uses local credentials independent of SIWC, no public self-signup.
- Deployment subdomain not chosen. Do not buy/register a domain or issue certificates automatically.
- English interface; tutor replies can use learner's requested language if desired, but default English not enforced on user content.
- Initial support for PDF with extractable text and Markdown/plain text; OCR and audio are later features.
- Local device sync means browser/PWA offline draft cache plus sync to owner VPS (not automatic full filesystem mirroring).
- Backend FastAPI/Python, React/TypeScript, PostgreSQL and Docker Compose based on resource and developer productivity; can change only with documented rationale.
- Default spaced intervals and mastery bands are an explainable heuristic, not a scientific certification.
- Default goal daily plan 20 minutes, editable.
- Source deletion soft-delete window 30 days proposed; subject to owner's final preference and legal/privacy policy.

## Owner choices needed before production, not blockers for local development

1. FQDN and DNS access (e.g. `study.example.com`) + certificate method.
2. Preferred off-VPS encrypted backup location and retention policy.
3. Final open-source license (recommend consider Apache-2.0 or AGPL-3.0 after tradeoff discussion).
4. Whether additional devices need full offline content or only offline note drafts for v1.
5. Confirm SIWC OAuth/plan eligibility and remote VM terms with real proof.
6. User's preferred authentication (local password + optional TOTP is starting assumption).
7. Initial upload/storage quota and anticipated annual source volume.
8. Access restrictions: internet login from anywhere versus VPN-only, especially while HTTPS is unconfigured.

## Risk register

| ID | Severity | Risk | Mitigation / gate |
|---|---|---|---|
| R1 | Critical | SIWC unavailable, model not eligible, current preview changes | Mandatory local POC; no unofficial or paid fallback |
| R2 | Critical | RecallSpring deploy harms ProtectedApp | Isolation, hard no-touch rule, separate project, staged owner approval, health baseline |
| R3 | High | Low free disk on the VPS creates outages | Owner-approved build cache cleanup, >=10 GiB free launch gate, offsite backup, quotas |
| R4 | High | Docker-published ports can bypass the host firewall | External exposure audit; no new 0.0.0.0 binds; existing app fixes separately approved |
| R5 | High | SIWC OAuth tokens mishandled | Official self-hosted flow, owner-controlled storage, least privilege, audit, no token logging |
| R6 | High | AI hallucination or misleading grading | Source citation links, calibrated provisional marks, human correction and tests |
| R7 | High | Lost learner input | Persist-first attempts, idempotency, local draft outbox, restore drills |
| R8 | Medium | Review algorithm optimizes score not durable recall | Transparent schedule, revisit post-exam, future empirical tuning, manual override |
| R9 | Medium | Visuals become distracting/inaccurate | Intent-based visual choice, allowlist, caption provenance, plain fallback |
| R10 | Medium | Expanding multi-user features violates SIWC terms | Single-user-first, user-owned runtime only, explicit new terms review before any SaaS |
| R11 | High | No HTTPS currently shown on port 443 | No public credentials/OAuth until DNS, cert and TLS validated |
| R12 | Medium | Increased CPU/RAM causes collateral performance degradation | Container limits, no local model, low concurrency, metrics and rollback |

## Decision process for changes

Agents may make reversible local implementation choices. They must create a lightweight ADR (`docs/adr/NNN-...md`) for substantive departures from this pack and obtain owner consent for breaking changes, provider policy violations, paid service, production configuration updates, destructive data operation or possible ProtectedApp disruption.
