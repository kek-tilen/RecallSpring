# ADR-006 — Learning first: study before practice and simulations

- **Status:** Accepted by owner, 2026-11-19
- **Supersedes:** the "prefer a simulation" guidance of ADR-005 for material that has not been studied

## Context

In the owner's first real session, Claude set up the 1st kolokvij correctly and then immediately ran a mixed simulation on material the owner had not studied yet. Nothing in RecallSpring distinguished *not studied* from *studied but not practised*, and the connector instructions told Claude to prefer simulations. Practising unseen material measures nothing and would have polluted the review schedule with lapses.

## Decision

- **Study status per concept:** `not_studied` (default), `studied` (learning session, or any practice evidence), `known` (learner self-report, or shown in a diagnostic pre-test). Changes are learning events; self-reports are audited with the learner's own reason.
- **Learning session (default style):** Claude teaches in chunks of a few pages, in the order of the material, from the learner's own sources with page citations; the learner writes a summary in their own words in a first-party MCP App form (`ui://recallspring/summary`), stored **exactly** as a note (`POST /connector/learning`, idempotent by `client_request_id`) — this marks the concepts studied; then 2–3 short check questions (Bloom 1–2). Writing can be skipped; the concepts are still marked studied.
- **Server-side guard:** Claude's practice questions and practice simulations (`mode = practice`) are refused with `409 concepts_not_studied` (listing the concepts and the three ways forward) while any concept is not studied. Learner-written questions in the web app are not guarded.
- **Diagnostic pre-tests** (`mode = diagnostic`, only when the learner asks): attempts are stored, but never enter the review replay. A concept whose items are all graded final, not low confidence, grade ≥ 3 becomes `known`; others stay to be learned.
- **Plan `plan-v1` categories:** `Learn next` (not studied: in material order — source upload order, then page/position — with the linked pages, 12 min, +4 min for topics frequent on past papers), `Practice` (studied or known, no evidence yet), then the existing `Review due`, `Strengthen`, `Maintain`. Capacity counts 18 min for a not-studied concept (learning + first practice).
- **Owner data:** the owner's unsubmitted simulation "Diagnostika 1" was switched to `diagnostic` (audited, no answers existed).

## Consequences

- Claude can no longer jump straight to a kolokvij simulation on new material; the plan and the API both enforce the order.
- A learner who attended lectures can skip the teaching step honestly ("known"), or prove it with a diagnostic.
- Migration `0005` is additive.
