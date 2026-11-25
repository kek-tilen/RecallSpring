# ADR-013 — Why this plan: a confirmed exam profile, coverage and an honest rationale

Status: accepted 2026-11-25 (owner in chat; owner feedback after real use: "the learner must be able to trust that the
agent knows what it is doing"). Rolled out in steps, see Rollout (steps 1-2 done 2026-11-25). Extends ADR-005 (study targets,
plan v1, simulations) and the exam readiness in `docs/05`.

## Context

The assistant says "according to your exam profile…", but the learner cannot see what is in the profile or how the
plan follows from it. Looking at what exists:

- `record_exam_profile` stores item types with shares, a Bloom mix, topic weights (0.5–2, `concept_id` optional),
  a few paraphrased example items, notes and the old paper (`source_id`). Only the latest profile of a target counts.
- The plan and readiness use a topic weight only when it is linked to a concept, and only to order work and to add
  "Frequent topic on past papers". **A topic without a linked concept silently has no effect.** A profile can look
  thorough while half of it changes nothing.
- The profile has no points per topic, no place on the paper (question number, page), nothing about several years,
  nothing about what the model could not read, and no sign that the learner agreed with the analysis.
- The Course page shows the profile; nothing shows how the plan covers it or what it leaves out.

Trust needs the reasoning to be visible, checkable against the paper, and computed by RecallSpring rather than
asserted by the model.

## Decision

### 1. Exam profile v2 (stored, learner-confirmed)

- **Topics** get: `points` (when the paper shows them) or `share` (otherwise), `concept_ids` (several concepts per
  topic), `where` (question numbers and pages on the paper, e.g. "Q2, p. 1"), and `papers` (which papers the topic
  appeared on).
- **Several papers per target.** A profile lists its papers (`source_id`, year or label, total points, duration when
  shown). A topic on more papers counts more: weight from its share of points, raised for recurrence (on 2 papers
  ×1.25, on 3 or more ×1.5, capped at 2.0). The exact formula is fixed in the build and recorded in `docs/05`.
- **Unread parts:** `unreadable` lists what the model could not make out (e.g. "points of Q4", "page 2 is a scan
  without text").
- **Mapping checked by the server.** Every topic must name concepts of this course or be marked
  `not_in_material: true`. RecallSpring refuses a topic that does neither, so nothing is silently ignored.
- **Confirmation.** A profile is saved at once as `unconfirmed`. The assistant shows the learner a short summary
  (topics with points and where they are on the paper, item types, Bloom mix, what it could not read) and asks
  whether it matches what they know about the kolokvij. Corrections make a new version; "yes" sets
  `confirmed_at` (who: the learner, through the assistant or the web app). The plan uses an unconfirmed profile but
  always says it is unconfirmed. Older profiles stay readable as v1 (shares only, no confirmation) and are shown as
  "analysed before profiles were confirmed".

### 2. The rationale is computed, not written by the model

A new deterministic service (`rationale-v1`, no model calls) builds "Why this plan" for one target from the
profile, readiness and today's plan:

- **What the paper shows:** topics in order of points, item types, Bloom mix, the papers it comes from, confirmed or
  not.
- **Coverage, weighted by points:** for each topic its concepts and their states (not studied, weak, not practised,
  developing, solid); in total "studied N % of the points, solid M %", plus the same for the Bloom mix against what
  has been practised.
- **Why this order:** the priority rules the planner actually applies (`PRIORITY_RULES` in `planner.py`, kept next
  to the scoring), with each of today's items tied to its topic and points. Built 2026-11-25, the rules are: a
  score of exam closeness × need × topic weight × difficulty; new material keeps the order of the material whatever
  its weight (earlier parts come before what builds on them) and a heavier topic gets more study time instead; with
  average weights due reviews come first, then new material, then practice and weak concepts. Learning new material
  by points was considered and not done: it would break the order of the material.
- **Does it fit:** work left against the time available until the date (the existing capacity check).
- **Limits, stated by the server:** no old paper; only one paper (pattern uncertain); unconfirmed profile; topics
  marked `not_in_material`; scope concepts that never appeared on a paper (they keep an average weight, so heavier
  topics can come before them, and that is said); topics on the paper outside the exam's scope; no points on the
  paper; papers RecallSpring has no copy of; unreadable parts; Bloom levels on the paper above the learner's
  practice limit.

Estimates from practice, never a predicted grade or a validated score.

### 3. In the assistant

- New read tool `get_plan_rationale(target_id)` (connector, MCP and ChatGPT in Chat).
- The assistant shows it **at the first session for a target, after the profile changes, and whenever the learner
  asks why**, not at the start of every session. A few lines: what the paper shows, how today covers it, what is
  left out and why. It may explain and rephrase, but must not add claims the rationale does not contain; anything
  else it says about the paper cites the paper (question or page).
- After `record_exam_profile` the assistant always asks for the confirmation in §1.
- The same rules in the server instructions, ChatGPT in Chat and the Codex / Antigravity course folders.

### 4. In the web app

- **Readiness page:** a "Why this plan" section with the same data: the profile (with a link to each old paper and
  its confirmation), a coverage table by topic (points, concepts, states), the order of today's work and the
  limits. There the learner can confirm the profile; corrections go through the assistant, which re-reads the
  paper.
- **Home:** a quiet `Why?` link next to today's plan for a course with an active target, opening that section.

### 5. On the paper but not in the material: the web, labelled and only with the learner's yes

Added 2026-11-25 (owner in chat). Example: the material shows `nmap` but never explains the `-A` flag, while
reliable sources show it matters for the kind of questions on the paper.

- When a topic on a paper, or a detail of what the material covers (a command's flag, an option, a standard), is
  not in the material, the assistant may look it up on the web, only in an app that gives it web search. It
  prefers primary sources (official documentation, the standard, the tool's manual) and says plainly that this is
  **not from the course material**, with the links it used.
- It explains why it seems important for this exam (where such questions appear on the paper, what the sources
  say), then **asks** whether to add it. Nothing is added on its own.
- On yes: the content is saved as a separate source, origin `web`, titled "From the web: …", with each URL and the
  date it was read. The concepts created for it link only to that source, so every later citation, question and
  grade shows it comes from the web and not from the professor's material. The paper's topic then names those
  concepts and keeps a `from_web` mark.
- On no: the topic stays `not_in_material`.
- The rationale (§2) lists these topics separately: "added from the web at your request" and "not in the material,
  not added". Web content is never mixed into the material's citations, and a claim from the web never counts as
  evidence from the uploaded material.
- An app without web search says that it cannot look it up and offers to note the topic as not in the material.

## Rollout

Each step with tests and docs:

1. Profile v2: migration (new columns and a papers list; v1 rows kept as they are), API validation (mapping
   required, recurrence weight), confirmation endpoint. **Done 2026-11-25** (migration 0028; the MCP and ChatGPT
   tools `record_exam_profile` v2 and `confirm_exam_profile`; the Course page shows v2 topics and whether the
   analysis is confirmed).
2. `rationale-v1` service and `GET /targets/{id}/rationale` (owner and connector), with source-aware tests.
   **Done 2026-11-25** (`services/rationale.py`).
3. MCP tool and instructions; ChatGPT in Chat tool; Codex / Antigravity folder text; web sources for
   topics not in the material (§5: source origin `web` with URLs, `from_web` topics, consent first).
4. Web: Readiness section, Home `Why?` link, profile confirmation.

## Consequences

- The learner can check the plan against the paper and correct the analysis, instead of taking the model's word.
- Assistants must map every topic to course concepts or say it is not in the material: a little more work per
  analysis, and no silent gaps.
- A weak basis (no paper, one paper, unconfirmed) is shown as such rather than hidden behind confident text.
- Points-weighted coverage is an estimate from practice evidence; it is not a grade prediction and is labelled so.
