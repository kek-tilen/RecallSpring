# ADR-003 — Review scheduling policy `rs-interval-v1`

- **Status:** Accepted (deterministic refinement allowed by docs/05), 2026-11-19
- **Code:** `services/api/src/recallspring_api/learning/scheduler.py`; tests: `services/api/tests/test_scheduler.py`

## Decision

The review state of a concept is a **pure function of its evidence**: the effective assessment of every attempt linked to the concept (a learner correction wins over AI or deterministic evaluations; otherwise the latest) plus explicit deferrals, replayed in chronological order. The stored `review_state` row is only a cache, recomputed after every new assessment, correction or deferral. Corrections therefore never overwrite history and always yield the exact schedule.

Rules, with intervals `[1, 3, 7, 14, 30, 60, 120]` days:

| Situation | Effect |
|---|---|
| First evidence for a concept | step 0, due the next local day |
| Uncertain evidence (`provisional`, `ungraded`, or low confidence) | never promotes or lengthens; short follow-up the next local day (never later than an earlier existing due date) |
| Certain grade ≥ 3 at/after the due time | step + 1 (max 6), due after `INTERVALS[step]` days |
| Certain grade ≥ 3 **before** the due time | interval kept (refinement: massed practice in one sitting must not climb the ladder) |
| Certain grade 2 | step − 1 (min 0), due after `min(3, INTERVALS[step])` days |
| Certain grade ≤ 1 | step 0, due the next local day; lapse counted after a success streak |
| "I don't know" | deterministic assessment grade 0 (final, high confidence) |
| Skip | no evidence; the review stays due |
| Deferral | due becomes `max(due, until)`; step unchanged; audited |

Due dates are **local midnights** in the learner's timezone (default Europe/Ljubljana), stored in UTC, so a review is never placed in the past by timezone handling and DST transitions are handled by `zoneinfo`. Evidence time is the attempt's submission time, so a delayed evaluation does not shift the schedule. Every state carries a `due_reason` (code, English message, interval, grade, attempt) shown to the learner as the *why*.

## Consequences

- Mock and other uncertain evaluations can only ever shorten intervals; a simulated grader can never inflate the schedule.
- Exam-aware prioritization and post-exam long-term maintenance live in the planner (next slice); the scheduler never discards concepts.
- This is an explainable heuristic, not a calibrated memory model; changing a rule requires a new policy version and tests.
