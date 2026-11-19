# 05 — Learning Engine and Pedagogy

## Method: Hybrid Learning (owner-approved)

**Learner controls new material.** The app supports reading and own-note writing; it should not force AI-generated summaries or linear lessons. The AI orchestrates assessments, weak-spot identification and later reviews, but the learner may request mentor-led help at any moment.

### Bloom taxonomy use

| Level | Label | Core task | Default use |
|---|---|---|---|
| 1 | Remember | Retrieve facts, definitions, components | Quick recall probes as necessary |
| 2 | Understand | Explain in own words, compare examples | Notes, self-explanation and short checks |
| 3 | Apply | Solve a new but grounded problem | Primary first practice |
| 4 | Analyze | Relate causes, compare mechanisms, find parts | Primary in-depth practice |
| 5 | Evaluate | Argue a choice with explicit criteria | Primary critical reasoning practice |
| 6 | Create | Synthesize new case, model, solution | Optional for appropriate content |

Default on new topics: gently ramp levels 3->4->5 **when evidence of foundation exists**. Default on revisions: mix levels 1–5 and topics, progressively increasing transfer. Make level selector flexible; not every topic admits a meaningful level-5 prompt.

## Learning lifecycle

`Unseen -> Reading -> Practicing -> Review queued -> Due -> Reviewed -> Maintained` is a UX model, not a strict mastery ladder. Concepts can return to `Needs attention` after an error. Self-ratings are distinct from evidenced results.

### On source import

1. Extract sections with page/heading provenance; classify parser confidence.
2. Draft concepts and prerequisite links with evidence refs; proposed rather than assumed facts.
3. Attach concepts to syllabus objectives. If weak source support, mark `needs verification` and avoid invented answers.
4. Offer quick 'What would you like to study first?' but do not generate a giant card deck.

### On note-taking

- Auto-save every meaningful change after a short debounce plus on blur/close as best effort, with transactional server acknowledgment; recover offline drafts.
- Encourage read -> hide -> rewrite from memory -> compare, with source readily available but not forcing one rigid habit.
- Note text is learner-owned, editable, versioned; tutor can comment, not silently rewrite.

### On questioning

- Use model to generate open-ended 3/4/5 prompts linked to source and concepts; alternatives can include short responses, scenario problems, compare/contrast, critique.
- Avoid clues embedded in stems. At start user can choose `Mixed` or `Progressive` and `Closed notes` or `Open notes` (closed default).
- Questions must vary across sessions; avoid near-duplicate stems, maintain generation history and last practiced concept pairs.
- User answer saved immediately before AI feedback. 'Reveal hint', 'Skip', and 'I don't know' are all explicit attempt actions.

### Grading rubric (not the same as true knowledge)

| Grade | Label | General rule |
|---|---|---|
| 0 | No evidence | Incorrect/blank or meaningful misunderstanding |
| 1 | Fragile | Some relevant recall but core reasoning incorrect/incomplete |
| 2 | Partial | Main idea present, gaps or weak justification |
| 3 | Solid | Correct and justified within task requirements |
| 4 | Transfer | Correct, well supported, handles novel implication or counterexample |

Grade NULL with `ungraded` is mandatory when question cannot be judged on available evidence. Include `why`, specific missing steps, citations, uncertainty and suggested next step. Expose `Challenge evaluation` and teacher correction. A well-grounded critical response may have multiple acceptable positions; the rubric must reward reasoning rather than conformity to model opinion.

## Scheduling: deterministic v1 algorithm

Avoid claiming FSRS accuracy without calibration/training data. Use an inspectable, adjustable interval heuristic with a policy version and automated tests. Proposed initial schedule:

- After a meaningful first completed session: next review **1 day** later.
- For repeated `solid`/`transfer` reviews, intervals approx `[1,3,7,14,30,60,120]` days with bounded multiplier; use stable algorithmic index per concept.
- `partial` repeats current short interval (e.g. 1–3 days) and adjusts practice difficulty; `fragile`/`no evidence` schedules earlier review (e.g. next day) and remediation.
- Never schedule a review in the past solely due to timezone handling; store UTC and calculate in learner's configured timezone (default Europe/Ljubljana, user-editable).
- Skipped reviews remain due; a defer must be explicit and produce an audit event.
- Support long-term retention goals and periodic maintenance beyond exam dates; prioritization can lower after an exam but concepts are not discarded automatically.

Algorithm detail for implementation: start `step=0`, due next local day. On grade>=3 and confidence not low: `step=min(step+1, 6)` and `due=now + [1,3,7,14,30,60,120][step]` days; on grade 2: `step=max(step-1,0)`, due `now + min(3,[1,3,7,14,30,60,120][step])` days; on grade<=1: step=0, due next day. Agent may refine **only with deterministic tested rules**; record policy version and explain user-facing due reason. Evaluator uncertainty: if `ungraded` or `provisional`, do not promote mastery or lengthen interval on that uncertain evidence; schedule a short follow-up or request human grading.

## Daily planner

Inputs: available study minutes (default 20, adjustable), due reviews, weak concepts, prerequisites, incomplete syllabus topics, exam dates, user overrides and interaction recency. Output: **small explainable ranked list** with categories `Review due`, `Strengthen`, `Explore next` and approximate duration. Never auto-run LLM requests merely because planner refreshed.

Suggested baseline weighted priority: overdue duration capped, low recent evidence, course exam proximity, prerequisite importance, last practiced timestamp and learner goals. Store version, input timestamps and a `why_selected` explanation. Avoid manipulative streaks and overloaded plans. Provide graceful `Not enough evidence` states.

### Implemented: study targets and `plan-v1` (ADR-005)

- Each course can have study targets (kolokvij / izpit) with the learner's verbatim scope description, resolved scope (sources, page ranges, topics, concepts), specifics and an exam profile from past papers. A session starts with the study context; if nothing is set, Claude asks what the learner prepares for, from which material to which, whether an old paper exists, and any specifics.
- The nearest upcoming target is active. Passed targets' material is in maintenance (due reviews only, 15 % of the day by default, at least one item). Material outside the active target keeps only its due reviews at lower priority.
- Ranking: urgency (days left) × need (due / unstarted / weak) × exam-profile weight × difficulty; filled into the day's available minutes (60 min weekdays, 90 min weekends by default, per-day overrides). Each item explains why it was chosen; each active target gets a capacity check (`ok` / `tight` / `at_risk`).
- Knowledge bands (`not_started`, `emerging`, `developing`, `reliable`) and difficulty (observed after 3+ answers, else learner rating, else Claude's estimate) are explainable estimates.
- Kolokvij simulations (multiple choice + open questions) are answered in a RecallSpring form: drafts autosave, submission stores every answer exactly in one transaction, multiple choice is graded from the key, open answers by Claude. About 75 % of practice questions follow the past-paper style, 25 % are deeper Bloom 4–5 questions.

## Long-term learning

Review should persist after exams to address owner's reported forgetting. Long-term targets prioritize fundamentals and inter-topic transfer. Default schedule and concept importance can be adjusted by user with natural-language commands, but modifications always pass through typed server actions and audit.

## Study insights

Show: due today/this week, topics with repeated misconceptions, covered vs uncovered syllabus, most recent evidence by concept and upcoming exams. Do **not** display unwarranted precision about memory or ranking. A confidence descriptor must explicitly say 'Estimated from practice, not a guarantee of recall'.

## Example behavior

User uploads material on cell respiration, writes own explanation, asks for Bloom 4 practice. Tutor asks for similarities/differences between glycolysis and the citric acid cycle, grounded in uploaded sections. Answer saved. AI identifies a missing relationship, shows source excerpt and an optional flow visual. System records a partial grade, schedules a short follow-up and links the weak concept. A week later, the daily review mixes this with a distinct related concept instead of repeating identical flashcards.
