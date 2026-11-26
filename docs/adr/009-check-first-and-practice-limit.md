# ADR-009 — Check first and the practice limit

Status: accepted 2026-11-22 (owner in chat). Extends ADR-006 (learning first) and ADR-003 (scheduling, now `rs-interval-v2`).

## Context

Learning first is the right default, but it slows down a learner who already knows part of the material (from
lectures, or an earlier course). The owner asked for a check that shows what is already known, puts it in the
background and brings the rest forward, as a quiet option rather than a step everyone must take. The owner also
wanted to choose how far up Bloom's taxonomy practice goes in a course, without the exam paper being silently ignored.

## Decision

**Check first** is the existing diagnostic quiz (`quizzes.mode = 'diagnostic'`), offered gently instead of only on
request:

- **Where:** the course page has a folded "Already know some of this? You can check first" section with one quiet
  link per chapter (the course's topics, otherwise the material file a concept comes from) and "a bit of everything"
  for the active midterm or exam (the whole course without one). Assistants mention it once when a new chapter or
  target starts and never insist. RecallSpring cannot write questions itself, so the link gives the learner a message
  for their assistant.
- **Size:** a chapter check covers up to 12 of its concepts; "a bit of everything" up to 15, at least one per chapter
  and the rest in proportion. Concepts not checked yet come first, then those whose last check was not green.
- **Question kind:** with an exam profile, the share of closed questions on the paper (multiple choice, true/false)
  decides how many concepts are checked with two closed questions instead of one open question.
- **Level:** each concept is asked at its current level: 2 Understand before it is studied, otherwise the next level
  of its practice ramp, never above the practice limit. Check answers never move the ramp.
- **Scoring (deterministic):** an open answer graded final 3-4, not low confidence, is one full green; each correct
  closed answer is half a green (two make one, an odd count rounds down); a closed answer marked **"I'm guessing"**
  counts nothing, even when correct. Green = known; half a green, a Partial or an unsure open grade = yellow; nothing
  correct = red; an open answer still to grade = pending.
- **What follows:** a concept that was only marked `known` (never studied in a session) and is yellow or red in
  the check goes back to `not_studied`, so it is learned first again; studied concepts stay studied.
  Green concepts become `known` and get rare reviews: the first after 21 days at step 3, then 30,
  60, 120 days (`KnownFromCheck` in the scheduler; it changes nothing when practice evidence already exists).
  In the plan, red concepts are learned before yellow ones (both in material order); yellow ones take less time,
  because only the gaps are explained and the own-words summary may be skipped. The result is shown only in the
  course details (a "Check first" column), not on the Courses list.

**"I'm guessing"** is stored with the raw answer (`attempts.guessing`). In practice simulations a guessed correct
answer is graded 3 with low confidence, so it never lengthens a review interval.

**Practice limit** (`courses.bloom_ceiling`, 2-6 since migration 0034; empty = automatic: 5, or 6 Create while an
upcoming exam's profile has Bloom 6 questions, owner notes 2026-11-26; an explicit 5 stays 5) caps practice ramps, simulations, single questions and
checks; the server refuses higher levels (`409 above_practice_limit`). When an upcoming exam's profile has questions
above the limit, RecallSpring shows how large that share is until the learner keeps the limit on purpose
(`bloom_ceiling_confirmed_at`, audited); a newer profile or a new limit asks again. Without an exam profile there is
nothing to compare and no warning. At a limit of 6 RecallSpring adds `model_tip`: Create questions (design, plan or
produce something of one's own) are hard to ask and to grade, so it recommends the most capable model on offer.

## Consequences

- The scheduler policy is now `rs-interval-v2`; v1 schedules are unchanged unless a concept has a green check.
- Diagnostic answers still never enter the review evidence or the practice ramp; only the green result does.
- Migration 0023 adds `courses.bloom_ceiling`, `courses.bloom_ceiling_confirmed_at` and `attempts.guessing`
  (downgrade drops them).
- Checks are AI-graded for open answers: a green is study feedback, not a validated measure of knowledge.
