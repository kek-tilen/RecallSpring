# ADR-014 — Exam-aware reviews: an exam layer now, FSRS-6 in shadow, then the switch

Status: accepted 2026-11-26 (owner in chat: answered the design questions, then reviewed this ADR). Not built yet;
see Rollout. Extends ADR-003 (`rs-interval-v1`), ADR-009 (`rs-interval-v2`, Check first), the planner of ADR-005 and
ADR-007 (`plan-v2`) and the exam weights of ADR-013.

## Context

The review state of a concept is a pure replay of its evidence (ADR-003). The replay is a strength and stays.
Uncertain evidence never lengthens an interval, and corrections recompute the schedule exactly. What is missing:

- **The ladder does not know the exam date.** Take a concept first practised on day 0, Solid on days 1 and 4, with
  a kolokvij on day 10. The ladder puts the next review on day 11, the day after the exam, and the last review is
  six days before it. The planner's urgency only orders the work that is already due.
- **The target's `goal` (`exam_only` / `long_term`) is stored but unused** by scheduling.
- **The intervals do not adapt.** In Duolingo's comparison of 12.9 million sessions, a fixed ladder (Pimsleur)
  predicted recall worse than a constant guess, and Leitner boxes also lost to a constant (Settles & Meeder 2016).
  `rs-interval-v2` is a Leitner system with step-back.
- **Every review costs a fixed 4 minutes** in the plan, whatever the concept needs.

Research for this ADR (primary sources, listed at the end), in short:

- **FSRS-6** (open-spaced-repetition) models each item's stability S, difficulty D and retrievability R with a power
  forgetting curve. It handles early reviews, partial answers and lapses with one continuous state. py-fsrs 6.3.3
  (MIT, Python ≥ 3.10) is deterministic with fuzz off, an explicit card id and UTC datetimes. FSRS-7 shipped in
  fsrs-rs on 2026-11-10, its formulas were still being edited on 2026-11-16, and it is not in py-fsrs.
- **Only Again is a failure** in FSRS. Hard, Good and Easy are passes, and the optimizer learns from that binary
  label. Where the pass/fail line falls is therefore the most consequential mapping.
- **Spacing before a near test:**
  - The best gap grows with the time to the test but shrinks as a share of it: about 14–31 % for horizons of one
    to ten weeks, and 6–7 % for a year. Gaps that are too short cost more than gaps that are too long (Cepeda et al.
    2008).
  - When the test comes 1–7 days after the last session, a contracting schedule wins (Küpper-Tetzel et al. 2014).
- **Successive relearning:** retrieval with feedback until one correct answer per session, repeated in 3–4 sessions
  on separate days. It beats overlearning in one session (Rawson & Dunlosky 2011, 2014).
- **Testing with feedback:** testing beats restudy by about g = 0.5. Without feedback the benefit is near zero for
  items answered correctly half the time or less (Rowland 2014).
- **The main unknown:** no study validates FSRS, or any memory model, on concept-level open answers graded by a
  model. The FSRS benchmark measures how well binary recall of flashcards is predicted, not learning gains.

## Decision

### 1. Three phases

- **A, now:**
  - An exam layer on the existing ladder (`rs-interval-v3`) and a planner that chooses how deep each review goes
    (`plan-v3`).
  - A per-target choice for the days before the exam.
  - Answer timing.
  - FSRS-6 computed in **shadow**: stored, never shown and never used for dates.
- **B, after an owner checkpoint:** switch to FSRS-6 (`rs-fsrs6-v1`) when the shadow data support it (§6).
- **Later, each a version bump and a replay:** fitted parameters, FSRS-7 once it is in py-fsrs or a stable Anki
  release, and a different Partial mapping.

### 2. Exam layer (phase A, `rs-interval-v3` = `rs-interval-v2` + this section)

The ladder's own rules do not change. The layer is an **overlay on the final replayed state**, so history is never
rewritten. The ladder keeps its own date (`policy_due_at` in the due reason). An answer on a date the overlay pulled
forward counts as early for the ladder: a Solid answer keeps the interval and a weaker one steps back as usual. The
overlay can therefore add reviews but never lengthen an interval.

- **Which exam:** the nearest upcoming target (status `upcoming`, date today or later) whose scope contains the
  concept. E is its date, as a local day.
- **Target for the exam morning, T,** per target (§4). The default is 0.95 for `exam_only` and 0.90 for `long_term`.
- **The ladder as a stand-in for stability.** Phase A has no stability yet, so the ladder's current interval
  I = `INTERVALS[step]` stands in for S. On the FSRS-6 forgetting curve with the default w20 = 0.1542, recall falls to
  T after the fraction f(T) = (T^(−1/w20) − 1) / (0.9^(−1/w20) − 1) of S:

  | T | f(T) |
  |---|---|
  | 0.97 | 0.22 |
  | 0.95 | 0.40 |
  | 0.90 | 1.00 |

- **Exam cap:** the cap moves the review to the start of E−1 when both hold:
  - the ladder's date is after E−1;
  - more than f(T)·I days lie between the last review and E.

  A concept last reviewed on E−1 or E is never capped. For `long_term` the cap applies at most once per concept and
  exam. With T = 0.90 it almost never fires, because the ladder's own date already keeps it.
- **Relearning in the last 7 days.** A concept is weak when it is in the scope of an exam at most 7 days away and its
  last certain grade is 2 or lower. A weak concept is due again the next local day after each answer, never later
  than the ladder's date, until a Solid answer makes it no longer weak. After that the cap applies as usual.
- **A deferral made after the last answer wins** over the cap and the relearning overlay: it is the learner's
  explicit choice, and the plan says that the review now falls after the exam.
- **After the exam** the overlay stops, because the target is no longer upcoming. Post-exam behaviour changes only in
  phase B (§6).
- **New due reasons:** `exam_cap` ("Last review before 1. kolokvij on 12 Dec.") and `relearn` ("Weak a week before
  1. kolokvij: another try with feedback tomorrow."). Both carry `policy_due_at`, the exam and T.

**Worked example** (the case from the context: practised on day 0, Solid on days 1 and 4, kolokvij on day 10):

- *`exam_only`:* the ladder's date is day 11, and 10 − 4 = 6 > 0.40 × 7, so the review moves to day 9. A Solid answer
  on day 9 is early for the ladder and keeps its day-11 date. Day 9 is E−1, so nothing more is added.
- *`long_term`:* 6 is not more than 1.0 × 7, so the review stays on day 11.

**Within a session.** A final, certain grade of 2 or lower on a weak concept gets `relearn` in the grade response
(like `offer_harder`, ADR-013). The response gives the concept, today's attempt count, the criterion and what to say.
The assistant then:

1. gives feedback grounded in the material;
2. asks again after other questions, varying the question at Bloom 3 and above;
3. stops at the first Solid answer, or the second on E−1 for `exam_only`;
4. stops after at most 4 attempts that day.

For `long_term` the criterion is one Solid, also on E−1. Later attempts on the same day are evidence for the ladder,
as today. They are never presented as mastery. The rules are added to the MCP instructions, ChatGPT in Chat and the
Codex / Antigravity folder text.

### 3. How much each review gets: the planner decides (phase A, `plan-v3`)

The owner asked for the system to judge how much a review deserves against the whole situation. Phase A does this
with three deterministic depths:

| Depth | When | What the assistant does | Estimate |
|---|---|---|---|
| `quick` | A reliable concept brought forward by the cap, or a `Maintain` item | One short question, Bloom 1–2 | 3 min |
| `standard` | Any other due review | One question in the exam's style at the concept's practice level | 6 min |
| `relearn` | A weak concept in the last 7 days | Feedback and another try until the criterion (§2), at most 4 attempts | 10 min |

- Each plan item gets `depth`, and `why_selected` says why. A new category, `Relearn`, joins the plan's categories.
- The capacity check counts the exam tail.
- **When it is `tight` or `at_risk`, the planner trims in this order:**
  1. `standard` becomes `quick` for reliable concepts;
  2. capped reviews of the lowest-weight concepts are dropped (topic weights from ADR-013);
  3. `relearn` items are never dropped before the other two.

  When the day before the exam is full, the planner offers capped reviews on E−3 to E−2, in a fixed order: weight
  first, then a hash of the concept id.
- **Nothing is dropped silently.** "Why this plan" (`rationale-v1`) gets an `exam_tail_trimmed` limit naming what was
  left out and why.
- **The estimates learn the learner's pace (answer timing).** RecallSpring answer forms report how long the question
  was open and visible, excluding pauses over 5 minutes. They store it as `attempts.answer_seconds` (nullable,
  1–7200; migration). Chat answers have none.
  - After 10 timed answers of a depth, its estimate becomes the median of the last 30 plus 2 minutes for feedback.
    Until then the defaults above apply.
  - Like focus sessions, this records time spent, never learning or mastery.
- **Phase B** replaces the trimming order with value per minute (§6).
- **The learner stays in control:** availability, the maintenance and interest shares, a per-day minutes override
  and the choice in §4.

### 4. The learner's choices (owner: keep the defaults, leave the learner free to change them)

- **Per target, "Before this exam":**

  | Option | T | Default for |
  |---|---|---|
  | Regular reviews only | 0.90 | `long_term` |
  | An extra review before the exam | 0.95 | `exam_only` |
  | Intense | 0.97 | none |

  Intense warns that it needs noticeably more reviews. The choice is stored as `study_targets.exam_retention`
  (nullable numeric, 0.85–0.97; NULL means the goal's default; migration). It is set on the course's Exams tab and
  through `update_study_target`.
- **Phase B adds two global settings:**
  - Review intensity: Relaxed 0.85, Standard 0.90 (the default) or Thorough 0.93.
  - After an `exam_only` exam: Maintenance (desired retention 0.80, the default) or Pause.
- Choices are shown in words, never as a percentage chance of remembering. An assistant changes them only on the
  learner's clear request, and each change is audited.

### 5. FSRS-6 in shadow (phase A)

**Engine**

- py-fsrs 6.3.3, pinned with hashes in `requirements.lock`.
- `Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=False, desired_retention=0.90,
  maximum_interval=120)` with the default parameters.
- `card_id` comes from the concept UUID.
- Every review is passed at UTC midnight of the learner's local date. Elapsed time is then whole calendar days, and a
  late-evening answer followed by a morning one is never same-day.
- The app's own replay loop is sorted by (local date, attempt id). It records S, D and R after each step.
- A test asserts the library version and reproduces fixed fixtures: S 2.31 after a first Good, and 10.96 after a
  second Good two days later.

**Evidence:** one review per concept per local day, the day's first certain attempt.

- Excluded: provisional, low-confidence, ungraded and self-assessed grades, and diagnostic answers (as today).
- Later attempts that day stay audit only.
- The Bloom level is logged with every review. Readiness for higher levels stays with the practice ramp, not with R.

**Grade mapping (owner 2026-11-26):**

| Grade | Rating |
|---|---|
| 0 No evidence, 1 Fragile | Again |
| 2 Partial | Hard in `rs-fsrs6-v1`; Again in the second variant `rs-fsrs6-v1a`, computed side by side |
| 3 Solid | Good |
| 4 Transfer | Good. A grader cannot observe "no effort", and graders have been lenient with 4. Easy only if the shadow data later show that Transfer predicts better recall than Solid. |
| Shown in Check first | A first Easy review on the check date. ADR-009's 21-day first review stays as an overlay. |

The shadow also computes the exam cap from FSRS's own R(E) with each target's T. In phase B, that cap is what
compares workloads.

**Storage:** `review_shadow`, a derived table rebuilt by every replay and never edited (additive migration). One row
per variant and evidence row, with:

- the attempt, the local date, the grade, the rating and the Bloom level;
- the evaluator kind and confidence;
- the elapsed days;
- R, S and D before the review, and S and D after it;
- FSRS's date and the capped date;
- R(E) for the concept's exam;
- the library version and a hash of the parameter vector.

Nothing in the web app or the connector shows it.

**Report:** `recallspring shadow-report`, a command that never calls a model. It prints locally and can write a
file under `local-data/`, which is never committed. It shows:

1. **Prediction:** log loss of R against a constant baseline, the learner's running pass rate before each review.
   Both are computed only from earlier reviews. The same is shown for both variants, with a bootstrap 90 % interval.
2. **Workload:** reviews and minutes per day under the ladder and under FSRS with its cap.
3. **Exam morning:** how many concepts of each exam reached the exam morning below T under each policy.
4. **The Partial question:** pass rates of the next review after a Partial, a Fragile and a Solid answer.
5. **Graders:** the mix of graders and confidences behind the reviews.

The scheduler and the report make no model calls, so under the project rules they may run automatically.

### 6. The switch (phase B, owner checkpoint)

**Criteria:**

- at least one full exam cycle in shadow;
- at least 100 evaluable reviews (a concept's later first-of-day reviews, at least a day after the previous one);
- a variant beats the constant baseline on log loss, with an interval that excludes zero;
- its workload fits the learner's availability on the shadow days.

The owner decides with the report in hand. If the criteria are not met, the shadow simply continues and nothing
changes.

**On the switch**, the policy becomes `rs-fsrs6-v1`, or `v1a` if Again predicted Partial better. Every due reason
records the library version and the parameter hash, and all states are replayed. Then:

- **Exam cap from R(E):** if FSRS's date is after E−1 and R(E) is below T, the review moves to E−1, spread over E−3
  to E−1 as in §3.
- **Relearning** as in §2. A lapse already drops S to about 0.2–2 days.
- **Ordering by value per minute:** the planner orders work by its expected gain in predicted exam-day recall per
  estimated minute, weighted by the topic's exam weight. New material gains the most and a stable concept near T the
  least.
  - The gain uses FSRS's own pass and fail outcomes, weighted by the current R. It is used only for ordering and
    never shown.
  - At `at_risk`, T is lowered for that plan only, 0.95 → 0.90 → 0.85, and "Why this plan" says so. The learner's
    setting is not changed.
- **After the exam:**
  - `exam_only` moves to maintenance at desired retention 0.80 (intervals about 3.3 × S) or pauses, as the learner
    chose. The state is kept, so a later target resumes it by replay.
  - `long_term` continues at 0.90.
- **Unchanged:** the 120-day maximum interval, the uncertain-evidence follow-up and deferrals.
- **Rollback:** set the policy back to `rs-interval-v3` and replay. The state is derived, so no data is lost.
- **Personal parameters:**
  - not before 512 day-separated reviews; py-fsrs silently returns the defaults below that;
  - fitted by an explicit offline job, because torch stays out of the runtime image;
  - adopted only if they beat the defaults on later, held-out reviews.

### 7. What RecallSpring does not claim

- R is never shown as "a 92 % chance you'll remember this". It is a model estimate fitted on other people's
  flashcards with default parameters. It is not a validated measure of mastery (AGENTS.md).
- Schedules are never called optimal or proven. Each date gives its concrete reason ("Last review before
  1. kolokvij on 12 Dec.").
- Correct answers within one session are not presented as mastery. Exam scores are not predicted.
- FSRS is not called personalised while it runs on the default parameters. Benchmark accuracy is not cited as
  evidence that RecallSpring's scheduling improves learning.

## Rollout

Each step comes with tests, docs and a `docs/10` row. Migrations ship separately from app changes, after a backup
and with the owner's approval for the owner's instance.

1. **Exam layer and depths:** `rs-interval-v3` overlay; the `exam_cap` and `relearn` reasons; `relearn` in grade
   responses; `plan-v3` depths, the `Relearn` category and the trimming order; the `exam_tail_trimmed` limit;
   instructions in every assistant text. The defaults come from `goal`. No migration.
2. **"Before this exam" choice:** migration for `study_targets.exam_retention`; the Exams tab control and the
   connector field.
3. **Answer timing:** migration for `attempts.answer_seconds`; reported by the answer forms; estimates per depth.
4. **FSRS-6 shadow:** the pinned dependency, the `review_shadow` migration, both variants and the
   `shadow-report` command.
5. **Phase B,** after the owner's checkpoint on the report: the switch, the global settings and value per minute.

## Consequences

- No review is stranded after an exam. The days before an `exam_only` exam contract onto new and weak concepts,
  which is the shape the spacing literature supports for a near test.
- The plan's minutes come closer to the learner's real pace, and trimming is visible instead of silent.
- Phase A changes due dates only through an overlay that can add reviews but never lengthen intervals.
  `rs-interval-v2` schedules stay reproducible by replay.
- FSRS earns its place on the learner's own data rather than on a flashcard benchmark. The cost is one exam cycle
  before the switch, and a small sample from a single learner.
- Grades without their confidence and rationale could not be replayed into a new policy. They are already stored,
  and that stays a hard requirement.

## Key sources

- FSRS: [The Algorithm](https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm),
  [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) 6.3.3 (MIT),
  [srs-benchmark](https://github.com/open-spaced-repetition/srs-benchmark),
  [Anki manual: FSRS](https://docs.ankiweb.net/deck-options.html#fsrs).
- Settles & Meeder 2016, ACL, [P16-1174](https://aclanthology.org/P16-1174.pdf).
- Cepeda, Vul, Rohrer, Wixted & Pashler 2008, Psychological Science,
  [doi:10.1111/j.1467-9280.2008.02209.x](https://doi.org/10.1111/j.1467-9280.2008.02209.x).
- Küpper-Tetzel, Kapler & Wiseheart 2014, Memory & Cognition,
  [doi:10.3758/s13421-014-0394-1](https://doi.org/10.3758/s13421-014-0394-1).
- Rawson & Dunlosky 2011, JEP: General, [doi:10.1037/a0023956](https://doi.org/10.1037/a0023956).
- Roediger & Karpicke 2006, Psychological Science; Rowland 2014, Psychological Bulletin
  ([PubMed 25150680](https://pubmed.ncbi.nlm.nih.gov/25150680/)).
- Henkel et al. 2024, L@S ([arXiv:2405.02985](https://arxiv.org/abs/2405.02985)): model grading of short answers
  agrees with humans at about κ 0.70, against 0.75 between humans.
