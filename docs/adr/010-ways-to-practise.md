# ADR-010 — Ways to practise: Quiz, Exam answer, Discuss, and Concept-to-Clarity

Status: **accepted** 2026-11-23 (agreed in chat with the owner, who confirmed the start of implementation).
Extends ADR-006 (learning first) and ADR-009 (check first, practice limit).

## Context

RecallSpring has one way to practise studied material: questions (single, or as a quiz or simulation), graded 0-4
and scheduled for review. Two further needs came up from a real midterm:

- **Saying what counts in the space given.** Knowing a concept is not the same as answering about it on paper: the
  learner wrote 14 lines where 8 were expected, repeating points out of fear of leaving one out. This is exam technique,
  not knowledge, and it can be trained.
- **Understanding a concept well enough to explain it**, and seeing that explanation get clearer over time.

It was also agreed that no method is pushed on the learner: each is offered only when it helps, the learner can
ask for any of them at any time, and every option says what it trains.

The "Feynman technique" was considered and dropped as a named method: it is not well studied as such. Its useful
core (explain in your own words, get feedback on the gaps, improve the explanation) is self-explanation, which has
good research support, and is kept as **Concept-to-Clarity (C2C)** below.

## Decision

### Four ways to practise

| Way | What it trains | What it does not train | Graded? |
|---|---|---|---|
| **Quiz** (exists) | Recall, kept fresh by spaced reviews | Explaining in depth; answer technique | Yes, 0-4 |
| **Exam answer** (new) | Saying what counts within a word limit | New knowledge | Yes, 0-4 for knowledge; answer technique as separate feedback |
| **Discuss** (new, text only) | Applying and defending ideas (transfer) | Recall of details | The conversation no; its check questions yes |
| **C2C** (new) | Understanding one concept, shown by your own explanation getting clearer | Speed, recall under pressure | No: feedback only |

Each line ("what it trains / what it does not") is shown wherever the option is offered.

### Concept-to-Clarity (C2C)

- **One explanation per concept, in versions** (v1, v2, ...), not a new note each time. Each version is the
  learner's text **saved exactly, before any assistant reads it**, with its source: written by the learner,
  written at the end of a Discuss, or added from an exam answer.
- **Feedback per version** from the assistant that gave it (provider and model recorded): what is correct, what is
  missing, what is wrong, each with citations of sections it actually read. **No grade.** The assistant never
  rewrites the explanation; only the learner writes versions.
- The concept page shows all versions with their feedback and what changed between them.
- C2C is separate from **My notes**: notes summarise material, an explanation shows the learner's understanding of
  one concept. Saving a C2C version does not mark a concept studied by itself (a summary does); it is evidence for
  the learner, not for the scheduler.
- Versions are soft-deleted only after confirmation and stay restorable for 30 days.

### Exam answer

- A question kind (`practice_kind = "exam_answer"`) with a **word limit**. The assistant recommends the length for
  each question from its expected points and the exam profile. Without a recommendation RecallSpring uses 20 words
  per expected point, rounded to 10, between 20 and 300.
- **The learner can change the limit for each question.** RecallSpring records the recommended and the chosen
  length, that the learner set it and when; the assistant sees this explicitly when it reads the answer
  ("the learner changed the recommended length from 60 to 90 words") and respects the learner's choice.
- Words, not lines: lines depend on handwriting and paper; words can be counted. A live counter shows words used and
  the limit; going over is never blocked.
- **Grading:** the 0-4 grade measures knowledge exactly as for any other question; length never changes it.
  **Answer technique** is separate feedback stored with the assessment: which part of the answer covers which
  expected point, where a point is repeated, which point is missing, words used against the limit, and one piece of
  advice (typically "outline the points first, then write"). Repetition is shown, never penalised.
- Respects the practice limit (ADR-009) like every question.

### Bridges between Exam answer and C2C (both started only by the learner)

- **Exam answer → C2C** ("Add to C2C" after the feedback): the learner's exact answer becomes a new version of a
  concept the learner picks among the question's concepts. The version is labelled "From an exam answer to
  question ..., written with a N-word limit"; the assistant's C2C feedback knows this and does not count the limited
  scope against it. The answer's grade stays with the answer.
- **C2C → Exam answer** ("Practise saying this in N words"): a new exam-answer question asks for the concept in the
  recommended length. Its expected points come from the material, **never from the learner's own explanation**.
- Exam answers are never added to C2C automatically.

### Discuss (text only for now)

- A Socratic conversation about studied material: the assistant asks, challenges reasoning, and cites the material;
  it gives no grades for what is said in the conversation (only the chat transcript of the assistant's app holds it,
  so there is no saved raw input to grade).
- It ends, if the learner wants, with a new C2C version (with feedback) and 2-3 check questions, which are saved and
  graded like any question. `record_session_summary` records that a discussion took place and on which concepts.
- Works with every assistant: in Claude Desktop, Codex and Antigravity through the connector instructions; in
  RecallSpring's Chat (ChatGPT) through a "Discuss" start in the course and Chat. Voice is decided later.

### When something is suggested

At most **one** suggestion at a time, only when its condition holds, and each kind of suggestion can be turned off
in Settings → Study → Ways to practise. The learner can always ask for any way, at any time, in the app (the course
page's "Ways to practise") or by asking their assistant.

- **Quiz:** reviews that are due, and facts, definitions and lists (the default, as today).
- **Exam answer:** 7-21 days before a midterm or exam whose profile has open questions, or when the learner's open
  answers are clearly longer than needed (their last answers used more than 1.5 times the words their expected
  points call for).
- **Discuss:** a concept that is studied but whose last two graded answers stayed at Partial (2/4) or below.
- **C2C:** offered after Discuss and after an exam answer (the bridge), and on the concept page; not suggested on
  its own.

Suggestions are deterministic (server rules, no model call) and appear in the study plan and the course page, and
in the assistants' plan, with the "what it trains" line.

## Data (migration 0024, downgrade drops it all)

- `questions`: `practice_kind` (`quiz` | `exam_answer`, default `quiz`), `length_recommended_words`,
  `length_words`, `length_set_by` (`assistant` | `default` | `learner`), `length_changed_at`.
- `assessments.answer_technique` JSONB (coverage per expected point, repetitions, missing points, words used and
  limit, advice), filled only for exam answers.
- `explanations` (one per concept and user), `explanation_versions` (number, exact text, source, source attempt,
  word limit when from an exam answer, client request id for idempotency, created, deleted), and
  `explanation_feedback` (version, provider and model, correct / missing / wrong lists, cited section ids,
  feedback text, created).
- `users.practice_suggestions` JSONB: which kinds of suggestion are on (all on by default).

## Interfaces (outline; details in docs/07 when implemented)

- Web: concept page C2C panel (write a version, versions with feedback and differences); course page "Ways to
  practise"; answer form word counter and limit editor for exam answers; "Add to C2C"; Settings → Study → Ways to
  practise.
- Connector and Chat tools: `open_explanation_form` (concept), `get_explanation` (versions and feedback),
  `record_explanation_feedback` (version, structured feedback, cited sections); `create_questions` and `create_quiz`
  accept `practice_kind` and `length_words`; `record_assessment(s)` accept `answer_technique` for exam answers. The
  ChatGPT study tool set stays within its limit of 20 tools (some rarely used tools may move to the planning set).

## Rollout

Three steps, each with tests, docs and its own commit: (1) C2C; (2) Exam answer with the bridges; (3) Discuss,
suggestions and the Settings switches.

Step 1 (C2C) implemented 2026-11-23: migration `0024_ways_to_practise` (tables `explanations`,
`explanation_versions`, `explanation_feedback`; the columns for exam answers and suggestions are added now and
used from step 2), owner and connector routes, MCP form `ui://recallspring/explanation`, Chat form, the card on
the concept page and the `/explain` page.

## Consequences

- More evidence per concept, but only graded answers move reviews; C2C and answer technique are feedback.
- Answer-technique feedback and C2C feedback are AI-written: study feedback, not a validated measure.
- The assistant instructions grow (Discuss, exam answers, C2C); they stay short by pointing to the tools' own
  descriptions.
