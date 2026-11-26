"""RecallSpring's grading scale: one text, the same for every assistant (Claude, Codex, Antigravity, ChatGPT in Chat
and the in-app evaluator), so their grades mean the same thing in the review schedule (owner decision 2026-11-22).

It is sent with everything an assistant grades from (``GET /connector/attempts/{id}``, simulation results) and is
part of the in-app evaluation instructions. Change the version when the meaning of a grade changes.
"""

from __future__ import annotations

GRADING_SCALE_VERSION = "scale-v1"

GRADING_SCALE = """\
RecallSpring grading scale (scale-v1), the same for every assistant. Grade what the saved answer shows (text and \
photos) against the question and its expected points, not how confident it sounds or whether it agrees with you.
0 No evidence: blank, "I don't know", off-topic, or the core idea is wrong.
1 Fragile: a relevant term or fragment, but most expected points are missing or wrong.
2 Partial: the core idea is right, but an important step or expected point is missing or wrong (for example a \
correct conversion without the normalisation the question asks for).
3 Solid: everything the question asks for is correct and justified; small slips of wording or notation that do not \
change the meaning are fine. A fully correct answer to a recall, true/false or standard-procedure question is 3.
4 Transfer: correct and beyond the material: applies it to a new case, gives a valid counterexample or own example, \
or connects ideas the material does not connect. Use it sparingly: between 3 and 4, give 3.
Rules: check each expected point; a wrong statement lowers the grade even when other points are right. Status \
"provisional" when several readings are defensible or you are unsure; "ungraded" with grade null when the answer \
cannot be judged from the question, expected points and sources. In the feedback name the expected points that \
were met and those that were missing."""

# Owner 2026-11-26: an open answer the learner marked as unsure is graded like any other; the mark only says
# that more explanation may help. Sent with such an answer (GET /connector/attempts/{id}).
UNSURE_NOTE = (
    "The learner marked this answer as unsure. Grade it exactly like any other answer by the scale: being unsure "
    "never raises or lowers the grade. If it is below Solid, offer once, briefly, to explain that part again "
    "(from the material, with citations)."
)

GRADE_NAMES: dict[int, str] = {0: "No evidence", 1: "Fragile", 2: "Partial", 3: "Solid", 4: "Transfer"}

# Owner 2026-11-25: "3/4, grade saved" read like points on a test. Sent with every recorded grade.
TELL_THE_LEARNER = (
    "Tell the learner the level by its name in their language and what it means for this answer in one sentence "
    "(e.g. Solid: everything the question asks is correct), what was missing, and when it comes back for review "
    '(the schedule). Never write a bare number such as 3/4 or "grade saved": it reads like test points.'
)
