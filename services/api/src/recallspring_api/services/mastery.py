"""Explainable knowledge bands and difficulty (docs/05 → Study insights). Estimates, not psychometric scores."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Concept, ReviewState

BANDS = ("not_started", "emerging", "developing", "reliable")
BAND_LABELS = {"not_started": "Not started", "emerging": "Emerging", "developing": "Developing", "reliable": "Reliable"}


def band(state: ReviewState | None) -> str:
    """Deterministic band from the replayed review state.

    * no evidence → not_started
    * last certain answer showed no/fragile knowledge (lapse) → emerging
    * at least three spaced successes and a 7-day+ interval → reliable
    * anything else (first successes, partial or uncertain answers) → developing
    """
    if state is None:
        return "not_started"
    code = state.due_reason.get("code")
    grade = state.due_reason.get("grade")
    if code == "lapse" or (code == "first_evidence" and grade is not None and grade <= 1):
        return "emerging"
    if state.step >= 2 and state.consecutive_successes >= 3:
        return "reliable"
    return "developing"


@dataclass(frozen=True)
class Difficulty:
    value: int  # 1 (easy) .. 5 (hard)
    source: str  # "observed" | "learner" | "claude" | "default"


def difficulty(concept: Concept, state: ReviewState | None) -> Difficulty:
    """Observed results win once there are at least three pieces of evidence; before that a learner rating beats
    Claude's estimate, which beats the neutral default of 3."""
    if state is not None and state.evidence_count >= 3:
        observed = 3 + 0.5 * state.lapse_count - (1 if state.step >= 3 else 0)
        if state.due_reason.get("code") in ("partial", "lapse"):
            observed += 0.5
        return Difficulty(max(1, min(5, round(observed))), "observed")
    if concept.difficulty_estimate is not None:
        return Difficulty(concept.difficulty_estimate, concept.difficulty_source or "claude")
    return Difficulty(3, "default")
