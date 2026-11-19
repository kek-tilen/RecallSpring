"""Deterministic mock provider for development and tests.

Every result is marked ``simulated`` and every assessment is ``provisional`` with ``low`` confidence, so a
mock can never lengthen an interval or promote mastery (docs/04 → Adapter: mock).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from .provider import (
    ConnectionStatus,
    ModelInfo,
    ProviderCapabilities,
    ProviderInvalidOutput,
    ProviderTimeout,
    ProviderUnavailable,
    SourceExcerpt,
    StructuredRequest,
    StructuredResult,
    TurnEvent,
)

MOCK_MODEL = "mock-deterministic-v1"
SIMULATED_PREFIX = "[Simulated — not a real AI assessment] "

_WORD = re.compile(r"\w{4,}", re.UNICODE)

_TEMPLATES = {
    3: "Apply: describe a concrete situation in which {term} decides the outcome, and explain step by step why.",
    4: "Analyze: compare {term} with a closely related idea from this course. Where exactly do they differ, "
    "and what follows from that difference?",
    5: "Evaluate: someone claims that {term} only matters in textbook examples. Judge this claim using explicit "
    "criteria and at least one counterexample.",
    1: "Recall: state what {term} is in one or two sentences.",
    2: "Explain: describe {term} in your own words and give an example.",
    6: "Create: design a short new scenario that requires {term} and explain how it would be resolved.",
}


class MockProvider:
    id = "mock"

    def __init__(self, behavior: str = "normal") -> None:
        self.behavior = behavior

    def capabilities(self, model: str) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True, structured_output=True)

    async def connection_status(self) -> ConnectionStatus:
        return ConnectionStatus("connected", "Simulated provider for development and tests.")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(MOCK_MODEL, "Simulated (development only)")]

    async def stream_turn(
        self, model: str, instructions: str, history: list[dict[str, str]], sources: tuple[SourceExcerpt, ...]
    ) -> AsyncIterator[TurnEvent]:
        self._maybe_fail()
        for chunk in ("[Simulated tutor] ", "This is a placeholder reply ", "for development."):
            yield TurnEvent("text.delta", chunk)
        yield TurnEvent("turn.completed")

    async def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        self._maybe_fail()
        if self.behavior == "invalid":
            return StructuredResult(
                {"grade": "excellent", "script": "<script>alert(1)</script>"}, self.id, MOCK_MODEL, True
            )
        if request.task == "evaluation":
            data: Any = self._evaluate(request.hints)
        elif request.task == "question_generation":
            data = self._questions(request.hints)
        else:
            raise ProviderInvalidOutput(f"mock does not implement task {request.task}")
        return StructuredResult(data, self.id, MOCK_MODEL, True)

    def _maybe_fail(self) -> None:
        if self.behavior == "timeout":
            raise ProviderTimeout("simulated timeout")
        if self.behavior == "error":
            raise ProviderUnavailable("simulated outage")

    @staticmethod
    def _evaluate(hints: dict[str, Any]) -> dict[str, Any]:
        answer_words = {w.lower() for w in _WORD.findall(hints.get("answer_text", ""))}
        points: list[str] = [str(p) for p in hints.get("expected_points", [])]
        covered = [p for p in points if {w.lower() for w in _WORD.findall(p)} & answer_words]
        if not answer_words:
            grade = 0
        elif points:
            grade = min(4, round(4 * len(covered) / len(points)))
        else:
            grade = 2
        missing = [p for p in points if p not in covered]
        return {
            "status": "provisional",
            "grade": grade,
            "confidence": "low",
            "rubric_version": "mock-rubric-v1",
            "feedback": SIMULATED_PREFIX + f"Matched {len(covered)} of {len(points)} expected points by keyword.",
            "evidence_refs": list(hints.get("allowed_refs", []))[:2],
            "strengths": [f"Mentions: {p}" for p in covered][:8],
            "gaps": [f"Missing: {p}" for p in missing][:8],
            "remediation": "Re-read the cited section and explain the missing points from memory." if missing else None,
        }

    @staticmethod
    def _questions(hints: dict[str, Any]) -> dict[str, Any]:
        items = []
        concepts: list[dict[str, Any]] = hints.get("concepts", [])
        for i, level in enumerate(hints.get("bloom_levels", [3])):
            concept = concepts[i % len(concepts)]
            items.append(
                {
                    "bloom_level": level,
                    "prompt": _TEMPLATES[level].format(term=concept["term"]),
                    "concept_ids": [concept["id"]],
                    "expected_points": [concept["definition"]] if concept.get("definition") else [],
                    "source_refs": list(hints.get("allowed_refs", []))[:2],
                }
            )
        return {"questions": items}
