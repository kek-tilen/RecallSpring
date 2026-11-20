# ADR-007 — Personal interests, university first and a focus period

- **Status:** Accepted by owner, 2026-11-20
- **Extends:** ADR-005 (`plan-v1`) to `plan-v2`; ADR-006 (learning first) applies unchanged

## Context

The owner also wants to learn things that have nothing to do with university and no deadline, e.g. data analysis or
machine learning / computer vision in their free time, only to practise. University must keep priority by default.
The owner should be able to say clearly that university comes first, have the interests take over once the
university work is done, or decide to work on an interest now.

## Decision

- **Interest = a course of kind `interest`** (`courses.kind`, default `course`). It has a **goal** (the course
  description, in the learner's own words) instead of exams: creating a study target for it is refused
  (`422 interest_has_no_exams`), and it is never filed under a university / faculty / semester
  (`422 interest_not_filed`). A course becomes an interest only without upcoming exams (`409 course_has_exams`);
  it then leaves its semester. An interest can be paused by archiving it, like a course. Materials, concepts, notes,
  learning sessions, practice, simulations and reviews work exactly as for courses.
- **Study context of an interest:** the goal, progress and rules (no exam; teach toward the goal; learn first; prefer
  applied exercises, small projects and real data). Without a goal `needs_setup` is true and Claude asks: what the
  learner wants to be able to do, their level, the material, and how it should fit around university.
- **Priority (`users.interest_percent`, 0-50, default 0):**
  - *University first* (0): interests get only the minutes left after today's course work (at most 6 course items as
    before), and only while **every** active exam of a university course is `ok`. When one is `tight` or `at_risk`
    the whole day goes to the courses and the plan says which exam and why. This is the reading of "university first
    until its requirements are met": on track = requirements met for now.
  - *A share* (1-50 %): that share of each day is kept for interests first (at least one item), courses get the
    rest; exam capacity checks count only the rest, so the learner sees what the share costs. Left-over time still
    goes to interests only while every exam is on track.
- **Focus (`courses.focus_until`):** on the learner's clear request, one course or interest comes first until a day
  (inclusive; default today; at most 60 days). There is at most one focus; a new one replaces the old one; it ends by
  itself after its day or when the course is archived or deleted. Focus items come first (marked `focus`), other
  courses get the time left (no guaranteed item), other interests only while every exam is on track. Capacity checks
  of the other courses do not count the focus days (conservative: the warning appears early), and the plan's `focus`
  message names every exam that is tight or at risk meanwhile.
- **Plan `plan-v2`:** adds `course_kind` and `focus` per item, `interests` (policy, share, reserved and planned
  minutes, explanation) and `focus` to the plan. Interest items get at most 3 places. A plan for one course or
  interest (`course_id`) is the learner's explicit choice: no priority rules apply. Without interests and focus the
  plan equals `plan-v1`.
- **Who may change it:** the web app (Settings → Interests; course page → Focus on this / End focus; Courses → New
  interest; Edit → Type and Goal) and Claude, only when the learner clearly asks (`set_availability
  interest_percent`, `set_focus`, `set_interest_goal`, `create_course kind="interest"`). Every change is audited
  (`study.settings_changed`, `study.availability_changed`, `study.focus_changed`, `course.goal_changed`,
  `course.updated`). No model is called by the planner.

## Consequences

- Interests never take time from an exam that is behind unless the learner chose a share or a focus, and then the
  exam warnings say what it costs.
- The owner's existing courses are unchanged (migration `0009` is additive; all rows become `course`, share 0, no
  focus); the downgrade refuses while interests exist.
- "University first" is judged by the deterministic capacity check, which is an estimate, not a guarantee.
