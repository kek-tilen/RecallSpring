"""Visual explanations in model replies are data checked against the allowlisted schema; nothing is ever run."""

from __future__ import annotations

import json
from typing import Any

import pytest

from recallspring_api.services import visual_blocks as vb


def fence(block: Any) -> str:
    body = block if isinstance(block, str) else json.dumps(block)
    return f"```recallspring-visual\n{body}\n```"


def base(kind: str, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"type": kind, "title": "T", "alt_text": "A description.", "data": data, **extra}


GRAPH = {"nodes": [{"id": "a", "label": "Plan"}, {"id": "b", "label": "Do"}], "edges": [{"from": "a", "to": "b"}]}
VALID = [
    base("process_flow", GRAPH),
    base("concept_map", GRAPH),
    base("comparison", {"columns": ["QA", "QC"], "rows": [{"criterion": "Focus", "values": ["process", "product"]}]}),
    base("timeline", {"events": [{"label": "1", "description": "x"}, {"label": "2", "description": "y"}]}),
    base(
        "data_chart",
        {"chart": "bar", "x_label": "x", "y_label": "y", "points": [{"x": "A", "y": 1}, {"x": "B", "y": 2}]},
    ),
    base(
        "interactive_parameter",
        {"parameter": "k", "minimum": 0, "maximum": 2, "step": 0.1, "initial": 1, "preset": "exponential_decay"},
    ),
]


@pytest.mark.parametrize("block", VALID, ids=[b["type"] for b in VALID])
def test_each_allowed_type_passes(block: dict[str, Any]) -> None:
    [result] = vb.from_reply(f"Text first.\n\n{fence(block)}\n\nText after.")
    assert result["ok"] is True and result["block"]["type"] == block["type"]


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        ("<svg onload=alert(1)>", "not valid JSON"),
        ("[1, 2]", "one JSON object"),
        (base("html_widget", {}), "allowed shape"),
        ({**VALID[0], "script": "alert(1)"}, "allowed shape"),
        (
            base("process_flow", {"nodes": [{"id": "a", "label": "x"}], "edges": [{"from": "a", "to": "z"}]}),
            "inconsistent",
        ),
        (base("process_flow", {"nodes": [{"id": "a", "label": "x"}, {"id": "a", "label": "y"}], "edges": []}), "share"),
        (
            base("comparison", {"columns": ["A", "B", "C"], "rows": [{"criterion": "c", "values": ["1", "2"]}]}),
            "one value",
        ),
        (
            '{"type": "data_chart", "title": "T", "alt_text": "a", "data": {"chart": "line", "x_label": "x",'
            ' "y_label": "y", "points": [{"x": 1, "y": NaN}, {"x": 2, "y": 1}]}}',
            "not valid JSON",
        ),
        (
            base(
                "interactive_parameter",
                {"parameter": "k", "minimum": 0, "maximum": 1e9, "step": 0.001, "initial": 1, "preset": "unit_circle"},
            ),
            "too many steps",
        ),
        (
            base(
                "interactive_parameter",
                {"parameter": "k", "minimum": 5, "maximum": 1, "step": 1, "initial": 2, "preset": "linear_growth"},
            ),
            "minimum",
        ),
    ],
)
def test_anything_else_is_refused_with_a_reason(block: Any, reason: str) -> None:
    [result] = vb.from_reply(fence(block))
    assert result["ok"] is False and reason in result["error"]


def test_ungrounded_visuals_lose_source_refs_and_charts_are_illustrative() -> None:
    chart = {**VALID[4], "source_refs": ["sec_123"], "illustrative": False}
    [result] = vb.from_reply(fence(chart))
    assert "source_refs" not in result["block"] and result["block"]["illustrative"] is True


def test_only_tagged_fences_count_and_their_number_is_bounded() -> None:
    text = "```html\n<b>x</b>\n```\n" + "\n".join(fence(VALID[0]) for _ in range(5))
    results = vb.from_reply(text)
    assert [r["ok"] for r in results] == [True, True, True, True, False]
    assert vb.from_reply("```mermaid\ngraph TD; A-->B\n```") == []


def test_instructions_name_every_type_and_forbid_code() -> None:
    for kind in ("process_flow", "concept_map", "comparison", "timeline", "data_chart", "interactive_parameter"):
        assert f'"{kind}"' in vb.INSTRUCTIONS
    assert "Never write HTML" in vb.INSTRUCTIONS
