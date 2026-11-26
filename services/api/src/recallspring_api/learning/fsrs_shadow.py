"""FSRS-6 in shadow (ADR-014 §5): pure, deterministic, no I/O and no model calls.

FSRS-6 (py-fsrs, MIT, Open Spaced Repetition) runs beside the ladder with its default parameters, fuzz off, no
learning steps and a maximum interval of 120 days. Its results are stored (``review_shadow``) and read only by
``recallspring shadow-report``: never shown and never used for dates until the owner decides (phase B, §6).

- **One review per concept per local day:** the day's first certain answer; later answers that day stay audit only.
  A Check first result is a first review (Easy) when nothing came before it; the 21-day first review of ADR-009
  stays as an overlay.
- **Whole days:** every review is passed at UTC midnight of the learner's local date, so elapsed time is whole
  calendar days and a late-evening answer followed by a morning one is never same-day.
- **Grades to ratings (owner 2026-11-26):** 0 No evidence and 1 Fragile are Again; 2 Partial is Hard in
  ``rs-fsrs6-v1`` and Again in ``rs-fsrs6-v1a``, computed side by side; 3 Solid and 4 Transfer are Good.
- **Exam cap from R(E):** when FSRS's date (with the overlay) is after the day before the concept's next exam and
  FSRS's R on the exam morning is below that exam's target T, the capped date is the day before the exam.

R is FSRS's estimate fitted on other people's flashcards with default parameters: not a chance of remembering and not
a measure of mastery (ADR-014 §7).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib import metadata
from typing import Literal

from fsrs import Card, Rating, Scheduler, State

from .scheduler import CHECK_KNOWN_DAYS

VARIANTS = ("rs-fsrs6-v1", "rs-fsrs6-v1a")
Variant = Literal["rs-fsrs6-v1", "rs-fsrs6-v1a"]
LIBRARY_VERSION = metadata.version("fsrs")
DESIRED_RETENTION = 0.90
MAXIMUM_INTERVAL = 120
SCHEDULER = Scheduler(
    learning_steps=(),
    relearning_steps=(),
    enable_fuzzing=False,
    desired_retention=DESIRED_RETENTION,
    maximum_interval=MAXIMUM_INTERVAL,
)
PARAMS_HASH = hashlib.sha256(json.dumps([round(w, 6) for w in SCHEDULER.parameters]).encode()).hexdigest()[:16]

Source = Literal["answer", "check_first"]


@dataclass(frozen=True)
class ShadowReview:
    """One review of a concept: the day's first certain answer, or a Check first result."""

    local_date: date
    source: Source
    attempt_id: uuid.UUID | None = None
    grade: int | None = None
    bloom_level: int | None = None
    evaluator_kind: str | None = None
    confidence: str | None = None


@dataclass(frozen=True)
class ShadowExam:
    """A study target whose scope holds the concept (any status but cancelled)."""

    target_id: uuid.UUID
    day: date
    target: float  # T, the target for the exam morning


@dataclass(frozen=True)
class ShadowRow:
    variant: str
    seq: int
    review: ShadowReview
    rating: int
    elapsed_days: int | None
    r_before: float | None
    s_before: float | None
    d_before: float | None
    s_after: float
    d_after: float
    fsrs_due: date
    capped_due: date
    exam: ShadowExam | None
    exam_r: float | None


def rating_for(review: ShadowReview, variant: str) -> Rating:
    if review.source == "check_first":
        return Rating.Easy
    grade = review.grade
    if grade is None:
        raise ValueError("an answer review needs a grade")
    if grade <= 1:
        return Rating.Again
    if grade == 2:
        return Rating.Hard if variant == "rs-fsrs6-v1" else Rating.Again
    return Rating.Good


def midnight(day: date) -> datetime:
    """A local date as FSRS sees it: UTC midnight, so elapsed time is whole calendar days."""
    return datetime.combine(day, time(0), UTC)


def first_per_day(candidates: Iterable[tuple[datetime, str, ShadowReview]]) -> list[ShadowReview]:
    """The day's first review per local date, in date order. Candidates are (when, tie-break key, review); a Check
    first result counts only as the very first review (after practice it is a diagnostic, not evidence)."""
    by_day: dict[date, ShadowReview] = {}
    for _, _, review in sorted(candidates, key=lambda c: (c[0], c[1])):
        by_day.setdefault(review.local_date, review)
    out = [by_day[d] for d in sorted(by_day)]
    return [r for i, r in enumerate(out) if r.source == "answer" or i == 0]


def next_exam(exams: Iterable[ShadowExam], day: date) -> ShadowExam | None:
    later = [e for e in exams if e.day > day]
    return min(later, key=lambda e: (e.day, str(e.target_id))) if later else None


def retrievability(stability: float, difficulty: float, last_day: date, on: date) -> float:
    """FSRS's R on the morning of ``on`` for a state last reviewed on ``last_day`` (for the report)."""
    card = Card(
        card_id=1,
        state=State.Review,
        stability=stability,
        difficulty=difficulty,
        due=midnight(on),
        last_review=midnight(last_day),
    )
    return float(SCHEDULER.get_card_retrievability(card, midnight(on)))


def run(concept_id: uuid.UUID, reviews: list[ShadowReview], exams: list[ShadowExam], variant: str) -> list[ShadowRow]:
    """Replay a concept's reviews through FSRS-6 for one variant."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}")
    rows: list[ShadowRow] = []
    if not reviews:
        return rows
    card = Card(card_id=concept_id.int % 2**63, due=midnight(reviews[0].local_date))
    previous: date | None = None
    for seq, review in enumerate(reviews, start=1):
        when = midnight(review.local_date)
        if previous is None:
            elapsed = r_before = s_before = d_before = None
        else:
            elapsed = (review.local_date - previous).days
            r_before = float(SCHEDULER.get_card_retrievability(card, when))
            s_before, d_before = card.stability, card.difficulty
        rating = rating_for(review, variant)
        card, _ = SCHEDULER.review_card(card, rating, review_datetime=when)
        assert card.stability is not None and card.difficulty is not None
        fsrs_due = card.due.astimezone(UTC).date()
        due = fsrs_due
        if review.source == "check_first":  # ADR-009: the first review after Check first comes in 21 days
            due = max(due, review.local_date + timedelta(days=CHECK_KNOWN_DAYS))
        exam = next_exam(exams, review.local_date)
        exam_r = float(SCHEDULER.get_card_retrievability(card, midnight(exam.day))) if exam else None
        if exam is not None and exam_r is not None:
            eve = exam.day - timedelta(days=1)
            if due > eve > review.local_date and exam_r < exam.target:
                due = eve
        rows.append(
            ShadowRow(
                variant=variant,
                seq=seq,
                review=review,
                rating=int(rating),
                elapsed_days=elapsed,
                r_before=r_before,
                s_before=s_before,
                d_before=d_before,
                s_after=float(card.stability),
                d_after=float(card.difficulty),
                fsrs_due=fsrs_due,
                capped_due=due,
                exam=exam,
                exam_r=exam_r,
            )
        )
        previous = review.local_date
    return rows
