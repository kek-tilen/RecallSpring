# ADR-005 — Study targets, plan v1 and kolokvij simulations

- **Status:** Accepted by owner, 2026-11-19
- **Code:** `services/api/src/recallspring_api/services/{targets,planner,mastery,quizzes}.py`, connector routes in `api/connector.py`, MCP tools and `quiz_form.html` in `services/mcp`

## Context

The owner studies several courses, each with kolokviji and an exam. They asked that:
- a study session first establishes **what they prepare for** (1st kolokvij, 2nd kolokvij, exam: whole course or only a part), **from which material to which**, whether there is an **old kolokvij**, and any **specifics**;
- questions follow the **style of old kolokviji**, which also hint at priorities;
- once a kolokvij is passed, its material is **maintained, not prioritised**, and in the exam period new material comes first;
- one overview coordinates priorities across courses by time left, knowledge and difficulty;
- simulations look like a real kolokvij (multiple choice + open questions) and are **stored in RecallSpring**, not only in the chat.

## Decision

**Study targets.** `study_targets` per course: kind (`kolokvij`/`izpit`/`other`), name, date, status (`upcoming`/`passed`/`failed`/`cancelled`), result, `goal`, the learner's **scope description verbatim**, specifics (`notes`), and resolved scope rows (whole sources, page ranges, topics or concepts; none = whole course). `GET /connector/courses/{id}/context` returns the active target (nearest upcoming), passed targets, recent simulations and, when nothing is set or a date passed, `needs_setup` with the exact questions Claude must ask. Updates are audited; scope rows are a derived index and may be replaced.

**Exam profile.** Claude analyses an old paper (imported source, or a scan attached to the chat) and records `target_profiles`: item types and shares, Bloom mix, topic weights 0.5–2.0 (linked to concepts where possible) and short paraphrased examples. Labelled as AI-derived.

**Owner defaults (approved):** 60 min Monday–Friday, 90 min weekend (per-day overrides); maintenance share 15 % of the day (at least one due review); question mix 75 % past-paper style / 25 % deeper Bloom 4–5.

**Knowledge and difficulty.** Bands `not_started` / `emerging` / `developing` / `reliable` derived from the replayed review state (estimate, not a guarantee). Difficulty 1–5: observed from results once there are ≥ 3 pieces of evidence; before that a learner rating, then Claude's estimate (never overriding the learner), then 3.

**Plan `plan-v1`** (deterministic, no model calls):
- passed-target concepts → `Maintain` (due reviews only, within the maintenance share);
- concepts outside the active target → only due reviews, at half priority;
- in scope: `Review due` (need 1.0 + overdue bonus up to 0.5), `Explore next` (0.9), `Strengthen` (0.8, +0.2 after a lapse);
- `score = urgency(days left: ≤3 → 3, ≤7 → 2, ≤14 → 1.5, else 1) × need × profile weight × (1 + 0.1 × (difficulty − 3))`;
- filled into today's minutes (base 4/6/8 min + difficulty above 3), at most six items, at least one;
- per active target a **capacity check**: remaining work (14/10/6/0 min per band + due reviews) vs. available minutes until the date × (1 − maintenance share) ÷ number of courses with targets → `ok` / `tight` / `at_risk` with "about N more min/day".

**Simulations.** `quizzes` + `quiz_items` reference ordinary questions (`question_type` `mcq` with options and a hidden key, or `open` with a hidden rubric). The first-party MCP App form (`ui://recallspring/quiz`) autosaves drafts (app-only `save_quiz_draft`), supports a time limit (auto-submit at zero), and submits all answers in **one transaction** (app-only `submit_quiz`, idempotent by `client_request_id`). Unanswered items count as "I don't know". Multiple choice is graded deterministically (`mcq-key-v1`: correct → grade 3, confidence medium; wrong → 0); open answers wait for Claude (`record_assessments`, all-or-nothing batch). Points: MCQ full or zero; open = points × grade ÷ 4.

## Consequences

- Claude's own chat widgets remain fine for explanations but never count as evidence; only RecallSpring forms do.
- Topic weights and difficulty are priors; observed results dominate as evidence accumulates.
- The capacity check splits time evenly across courses with targets; a smarter allocation can come later behind a new policy version.
- New tables are additive (migration `0004`).
