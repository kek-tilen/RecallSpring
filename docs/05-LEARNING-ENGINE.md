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

Practice ramp (2026-11-22): reading and notes are phases 1–2; practice then follows each concept's `practice.next_level` in `get_course_outline`, worked out by RecallSpring without a model call (`services/bloom.py`). A level counts as reached with a final grade of 3 or 4 from an assistant or the learner's correction (provisional and self-assessed grades never move it up). It ramps 3 Apply → 4 Analyze → 5 Evaluate (→ 6 Create only at a practice limit of 6), steps back one level (never below 3) after a 0–1 answer, and once the top level is reached suggests the level practised least recently (mixed). An exam profile's Bloom mix takes precedence; quizzes mix concepts and levels. The practice limit per course caps all of it: the learner's own (2–6), else automatic, which is 5 Evaluate, or 6 Create while an upcoming exam paper has Create questions (2026-11-26, migration 0034; at 6 RecallSpring recommends a more capable model, because Create questions are hard to ask and to judge well); RecallSpring says when the exam paper asks for higher levels until the learner keeps the limit on purpose (ADR-009).

Harder questions while learning (owner 2026-11-25): the check questions after a summary are Bloom 1–2. When the learner's last two learning answers in a course (Bloom 1–2, not Check first) are both final Solid or Transfer (not self-assessed), the grade response carries `offer_harder` (level 3 Apply, the concepts of those two answers, what to say). It appears exactly when the streak reaches two, so a declined offer does not return with every further good answer; a weaker answer starts a new streak. Never above the practice limit. The assistant offers once, in one sentence; on yes it asks at level 3 for those concepts (allowed, since they are studied), on no it goes on as planned. Deterministic (`bloom.harder_offer`), no model call.

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
- **Unsure (2026-11-26):** an open answer the learner marks as unsure is graded exactly like any other (the grade, the review schedule, Check first and readiness ignore the mark). The assistant sees it (`unsure`, and `unsure_note` from `GET /connector/attempts/{id}`) and, when the grade is below Solid, offers once to explain that part again. Only a closed answer marked "I'm guessing" counts nothing.

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

> **Implemented: exam layer `rs-interval-v3` and `plan-v3` (ADR-014 step 1, 2026-11-26).** On top of the ladder below, applied to the final replayed state only (history is never rewritten; the ladder keeps its own date as `policy_due_at`): (1) **exam cap**: for the nearest upcoming exam after the last review whose scope holds the concept, when the ladder's date is after the day before the exam and more than f(T) × the current interval days lie between the last review and the exam, the review moves to the day before the exam. T is the target for the exam morning, 0.95 for `exam_only` and 0.90 for `long_term`; f(T) comes from the FSRS-6 forgetting curve (0.40 for 0.95, 1.0 for 0.90, so long-term targets almost never move). (2) **Relearning**: a concept whose last certain grade is 2 or lower, answered 2–7 days before an exam, is due again the next day. (3) A deferral after the last answer wins. An answer on a brought-forward date is early for the ladder, so the layer adds reviews but never lengthens an interval. Due reasons `exam_cap` and `relearn` name the exam, its date and T. Dates follow a target when it changes; once an exam has passed, its brought-forward dates are recomputed before due reviews are read. After a weak answer before an exam the grade response carries `relearn` (feedback, another try later in the session with a varied question, stop at one Solid answer or two on the day before an exam-only exam, at most 4 tries a day). The planner gives each review a depth (`quick` 3 min, `standard` 4 min, `relearn` 10 min, +1 min per difficulty step above 3), shows weak concepts in the last week as `Relearn`, keeps reviews of reliable concepts short when an exam is tight or at risk, offers brought-forward reviews a day or two earlier when the day before the exam would not fit, and lists exam-tail work that did not fit in `left_out` ("Why this plan": `exam_tail_trimmed`). **Step 2 (2026-11-26, migration 0031):** the learner chooses per target how the reviews go before the exam: "Regular reviews only" (T 0.90), "An extra review before the exam" (0.95) or "Intense" (0.97, warned: noticeably more reviews); no choice means the goal's default. It is shown in words, never as a chance of remembering, and an assistant changes it only on the learner's clear request (audited). A long-term exam brings at most one review forward per concept. **Step 3 (2026-11-26, migration 0032):** the estimates learn the learner's pace. RecallSpring's answer forms (web and MCP) report how long a question was open and visible, without pauses over 5 minutes (`attempts.answer_seconds`; chat answers have none). After 10 timed answers of a depth (quick: questions at Bloom 1-2, standard: Bloom 3 and higher), its estimate is the median of the last 30 plus 2 minutes for the feedback, rounded up (at most 60); relearn keeps 2.5 standard reviews. Only answers count, not "I don't know", skips or Check first. The plan lists the minutes per depth in `estimates` with their source (`default` or `your_pace`). Time spent, never learning or mastery. **Step 4 (2026-11-26, migration 0033):** FSRS-6 (py-fsrs 6.3.3, default parameters, no fuzz, no learning steps, desired retention 0.90, at most 120 days) runs in shadow beside the ladder: one review per concept per local day (the day's first certain answer; provisional, low-confidence, ungraded, self-assessed and Check first answers stay out), passed at UTC midnight of the local date so elapsed time is whole days; grades 0-1 Again, 2 Partial as Hard (`rs-fsrs6-v1`) and as Again (`rs-fsrs6-v1a`) side by side, 3-4 Good, a first Check first result Easy. It also computes an exam cap from its own R on the exam morning. The rows (`review_shadow`) are rebuilt by every replay, never shown and never used for dates; `recallspring shadow-report` compares prediction (log loss against the learner's running pass rate, bootstrap 90 % interval), workload, exam mornings, the next review after Fragile, Partial and Solid answers, and the graders. The switch (phase B) needs the owner's checkpoint on that report.

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

- Each course can have study targets (kolokvij / izpit) with the learner's verbatim scope description, resolved scope (sources, page ranges, topics, concepts), specifics and an exam profile from past papers. **Exam profile v2 (ADR-013 §1, 2026-11-25):** every topic of a paper names the course concepts that cover it or says `not_in_material` (RecallSpring refuses a topic with neither, so nothing in a profile is silently ignored). A topic's share is its points over the papers' total points (or the given share); its weight is that share against an average topic's share (share × number of topics), ×1.25 when it appeared on 2 papers and ×1.5 on 3 or more, kept within 0.5–2.0, and without a share 1.0. Papers used only for their style (`use: style`, e.g. a paper of another kolokvij) do not count for recurrence, and a topic that appears only on them weighs 1.0 (`style_only`). A concept takes the highest weight of the topics it covers; the plan says "Weighs more on past papers" for a weight above 1. An analysis is saved unconfirmed; the learner confirms the latest one (through the assistant or the web app); analyses from before ADR-013 keep their topic weights and cannot be confirmed, only analysed again. **Why this plan (`rationale-v1`, ADR-013 §2):** computed without a model from the profile, readiness and today's plan. Coverage is weighted by each topic's share of the points (or its given share; a topic without one counts as an average topic): a topic counts as studied for the part of its concepts that is studied, ready for the part that is developing or solid, solid for the part that is solid; topics not in the material (or v1 topics without a concept) count as not covered. The order is described by `PRIORITY_RULES` next to the planner's scoring. The assistant shows it on its own at the first study session for an exam and after its analysis changed (`explain_plan` in the study context: no finished session of the course since then), otherwise when the learner asks. **On the paper but not in the material (ADR-013 §5):** an assistant with web search may look it up (primary sources first), says it is not from the course material, explains why it seems to matter for this exam and asks; only on the learner's yes it is saved as a web source (origin `web`, the links and the day they were read) and its concepts link only to that source. The rationale names topics whose concepts all come from the web (`from_web`) apart from topics not in the material and not added. A session starts with the study context; if nothing is set, Claude asks what the learner prepares for, from which material to which, whether an old paper exists, and any specifics.
- The nearest upcoming target is active. Passed targets' material is in maintenance (due reviews only, 15 % of the day by default, at least one item). Material outside the active target keeps only its due reviews at lower priority.
- Ranking: urgency (days left) × need (due / unstarted / weak) × exam-profile weight × difficulty; filled into the day's available minutes (60 min weekdays, 90 min weekends by default, per-day overrides). Each item explains why it was chosen; each active target gets a capacity check (`ok` / `tight` / `at_risk`).
- Knowledge bands (`not_started`, `emerging`, `developing`, `reliable`) and difficulty (observed after 3+ answers, else learner rating, else Claude's estimate) are explainable estimates.
- Kolokvij simulations (multiple choice + open questions) are answered in a RecallSpring form: drafts autosave, submission stores every answer exactly in one transaction, multiple choice is graded from the key, open answers by Claude. About 75 % of practice questions follow the past-paper style, 25 % are deeper Bloom 4–5 questions.

### Implemented: learning first (ADR-006)

- Each concept is `not_studied`, `studied` or `known`. New material is taught before it is practised: the assistant explains it part by part (the size of a part follows the explanation pace: step by step, balanced, larger chunks or auto; 2026-11-26) in the order of the material, every concept completely and concretely (what it is, how it works or why, a worked example from the material, how it connects to what came before, the usual mistakes, with citations; never only an outline; 2026-11-26), the learner writes a summary in their own words (saved exactly as a note), then 2–3 short checks. Only then do practice questions and kolokvij simulations follow. The assistant never assumes that something was studied or understood (not from earlier chats, its memory, the order of the material or a usual course): only `study_status`, the learner's notes and what it taught in the same conversation count (2026-11-26; in the connector instructions, Chat's instructions, the `get_study_context` rules, the Codex and Antigravity study folders and the Claude project templates).
- Simulation retakes (2026-11-26, migration 0036): a retake reuses the questions as a new version; the first version stays the benchmark and later ones are "seen questions". A retake submitted the same local day as an earlier version is practice only: graded and shown, but, like Check first, out of the review schedule, the Bloom ramp and the last feedback (`services/quiz_filters.py`), because the keys and feedback were seen hours earlier. On a later day it counts as normal evidence; early answers already never lengthen an interval. Readiness only counts a first version as a recent simulation.
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
