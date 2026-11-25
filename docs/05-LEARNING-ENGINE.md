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

Practice ramp (2026-11-22): reading and notes are phases 1–2; practice then follows each concept's `practice.next_level` in `get_course_outline`, worked out by RecallSpring without a model call (`services/bloom.py`). A level counts as reached with a final grade of 3 or 4 from an assistant or the learner's correction (provisional and self-assessed grades never move it up). It ramps 3 Apply → 4 Analyze → 5 Evaluate, steps back one level (never below 3) after a 0–1 answer, and once 5 is reached suggests the level among 3–5 practised least recently (mixed). An exam profile's Bloom mix takes precedence; quizzes mix concepts and levels. The learner's practice limit per course (2–5) caps all of it; RecallSpring says when the exam paper asks for higher levels until the learner keeps the limit on purpose (ADR-009).

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

**One scale for every assistant (scale-v1, 2026-11-22).** The exact wording every grader uses is `GRADING_SCALE` in `services/api/src/recallspring_api/learning/grading.py`. It is returned as `grading_scale` with every answer an assistant grades (connector `GET /attempts/{id}`, so also `get_answer` and ChatGPT in Chat, and simulation results) and is part of the in-app evaluation instructions (`eval-v2`). It adds anchors so models agree: a fully correct recall, true/false or standard-procedure answer is 3; 4 only for real transfer, and between 3 and 4 the grade is 3; a missing required step (e.g. normalisation) is 2; feedback names the expected points met and missed. Grades given before scale-v1 keep their value. **Saying a grade** (owner 2026-11-25): "3/4, grade saved" read like test points, so a recorded grade comes back with `grade_name` and `tell_the_learner`, and the instructions say the same: name the level in the learner's language with what it means for this answer, what was missing and the next review date, never a bare number. The web app keeps "Solid (3/4)" next to the scale's explanation.

**Self-assessment (2026-11-22).** When no assistant is available the learner can check a saved answer against the question's expected points (shown only after the answer is saved): met / partly / missed per point. The suggested grade is deterministic: all met → 3, at least half (partly counts half) → 2, something → 1, nothing → 0; 4 is never suggested and needs the learner's reason. The grade is stored as `evaluator_kind = self`, `status = provisional`, so the scheduler only plans a next-day follow-up and never lengthens an interval. It counts until any other grade exists: an assistant's check (`get_self_assessments_to_check`, or the `self_assessments` in the study context) replaces it; a learner correction (`human`) still wins over everything.

Grade NULL with `ungraded` is mandatory when question cannot be judged on available evidence. Include `why`, specific missing steps, citations, uncertainty and suggested next step. Expose `Challenge evaluation` and teacher correction. A well-grounded critical response may have multiple acceptable positions; the rubric must reward reasoning rather than conformity to model opinion.

## Scheduling: deterministic v1 algorithm

Avoid claiming FSRS accuracy without calibration/training data. Use an inspectable, adjustable interval heuristic with a policy version and automated tests. Proposed initial schedule:

- After a meaningful first completed session: next review **1 day** later.
- For repeated `solid`/`transfer` reviews, intervals approx `[1,3,7,14,30,60,120]` days with bounded multiplier; use stable algorithmic index per concept.
- `partial` repeats current short interval (e.g. 1–3 days) and adjusts practice difficulty; `fragile`/`no evidence` schedules earlier review (e.g. next day) and remediation.
- Never schedule a review in the past solely due to timezone handling; store UTC and calculate in learner's configured timezone (chosen at first run from the browser's zone, user-editable in Settings → Profile).
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

### Implemented: learning first (ADR-006)

- Each concept is `not_studied`, `studied` or `known`. New material is taught before it is practised: Claude explains a few pages at a time in the order of the material, the learner writes a summary in their own words (saved exactly as a note), then 2–3 short checks. Only then do practice questions and kolokvij simulations follow.
- RecallSpring refuses Claude's practice on unstudied concepts. A learner who already knows a topic says so (self-report, audited) or chooses **Check first** (ADR-009): a short diagnostic quiz per chapter or for a bit of everything, offered gently. Two correct closed answers or one Solid open answer show a concept (green: known, rare reviews from 21 days); half of that is yellow (learn only the gaps, summary optional); nothing is red (learn it first). A guess counts nothing. Check answers never enter the review evidence or the practice ramp.
- The plan shows `Learn next` items with the pages to study, then `Practice`, `Review due`, `Strengthen` and `Maintain`.

### Implemented: interests, university first and focus (ADR-007, `plan-v2`)

- An **interest** is a course of kind `interest`: personal learning without exams or a deadline (e.g. data analysis
  or computer vision in free time). Its goal (the learner's own words) replaces the exam; it is not filed under a
  semester; materials, concepts, learning sessions, practice and reviews work as for courses.
- **University first** (default, interest share 0 %): interests get only the minutes left after today's course work,
  and only while every exam of a university course is on track (`ok`). When an exam is `tight` or `at_risk` the
  whole day goes to the courses, and the plan's `interests.message` names the exam.
- **A share of each day** (1-50 %, the learner's choice): kept for interests first; exam capacity checks count only
  the rest of the day.
- **Focus** (the learner's clear request): one course or interest comes first until a day (at most 60 days, one at a
  time); other work gets the time left; capacity checks of other courses do not count the focus days, and
  `focus.message` names exams that are tight or at risk meanwhile.
- A plan for one course or interest (`course_id`) applies no priority rules. Without interests and focus `plan-v2`
  equals `plan-v1`.

### Implemented: Concept-to-Clarity (ADR-010, step 1)

- **C2C** trains understanding: the learner explains one concept in their own words. Each save is a new **version**
  (v1, v2, …) of one explanation per concept, kept exactly as written, with where it came from (written by the
  learner, after a discussion, or from an exam answer with its word limit; the last one only when the learner adds
  it, from step 2).
- The assistant reads the versions and gives **feedback per version**: correct, missing and wrong points and a short
  text, citing only sections of the concept's course (others are dropped). It is **not a grade**: it does not change
  the concept's study status, reviews, practice ramp or readiness, and the assistant never rewrites the explanation or
  writes a version for the learner.
- The concept page shows the newest version with its feedback, the changes from the previous version (added and
  removed words) and earlier versions folded. Versions are soft-deleted after confirmation and can be restored for
  30 days; numbers are never reused.

## Long-term learning

Review should persist after exams to address owner's reported forgetting. Long-term targets prioritize fundamentals and inter-topic transfer. Default schedule and concept importance can be adjusted by user with natural-language commands, but modifications always pass through typed server actions and audit.

## Study insights

Show: due today/this week, topics with repeated misconceptions, covered vs uncovered syllabus, most recent evidence by concept and upcoming exams. Do **not** display unwarranted precision about memory or ranking. A confidence descriptor must explicitly say 'Estimated from practice, not a guarantee of recall'.

### Implemented: exam readiness (`readiness-v1`)

Deterministic, no model calls; recomputed on every request from the review states and assessments already stored.

- Every concept in a target's scope gets one state, in this order of precedence:
  - `not_studied`: no learning evidence yet (learn it first);
  - `not_practised`: studied or marked known, but no graded answer yet;
  - `weak`: mastery band `emerging`, a lapse, or a last effective grade of 0-2;
  - `solid`: mastery band `reliable`;
  - `developing`: everything else ("Getting there").
- Concepts are grouped by the material they come from: syllabus topics first, then files in upload order (first
  linked section), then "Not linked to material". Each concept shows its last grade, whether a review is due, the
  past-paper weight and up to two citations.
- **Weakest**: up to 5 weak concepts, ordered by last grade, lapses and past-paper weight, each with a plain reason
  and the gaps and tip from the feedback of its last answer (a human correction wins). Diagnostic quizzes are left
  out.
- **Next steps** follow the learning-first order: learn what is not studied (in material order, with a per-day pace),
  strengthen the weakest, answer one question on studied but unpractised concepts, open due reviews, and suggest a
  timed simulation when the exam is 10 days away or less, at least half the scope is studied and no simulation was
  submitted in the last 7 days.
- The time check (`capacity`) is the planner's own (`plan-v2`) for each course's active target; later targets show a
  rough estimate of minutes left instead.
- The page and the connector say it plainly: estimated from answers so far, not a prediction of the grade.

### Implemented: weekly review (`week-v1`)

- Monday to Sunday in the learner's time zone, this week or up to 52 weeks back.
- Planned minutes are the learner's availability for the days so far; study time counts only study sessions closed
  with a summary (each capped at 4 hours), so it can be less than the real time.
- Answers, graded answers, concepts studied or marked known, simulations, notes and materials; active days; average
  effective grade with the previous week's average and the 0-4 distribution; a per-course breakdown.
- For the current week: overdue reviews, reviews due in the next 7 days, and exams in the next 21 days with their
  readiness counts.
- `summary` holds plain sentences built from these numbers only; Claude starts its weekly review from them.

## Example behavior

User uploads material on cell respiration, writes own explanation, asks for Bloom 4 practice. Tutor asks for similarities/differences between glycolysis and the citric acid cycle, grounded in uploaded sections. Answer saved. AI identifies a missing relationship, shows source excerpt and an optional flow visual. System records a partial grade, schedules a short follow-up and links the weak concept. A week later, the daily review mixes this with a distinct related concept instead of repeating identical flashcards.
