"""Visual explanations in model replies, as data only (docs/07 → AI visual output, AGENTS.md).

A model may add a fenced block tagged ``recallspring-visual`` holding one JSON object in the allowlisted shape of
``visual-block.schema.json``. RecallSpring parses it, checks it against the schema and the rules below, and the web
app draws it with its own components. Nothing a model writes (HTML, SVG, CSS, JavaScript, Mermaid, …) is ever run;
a block that does not pass is shown as "could not be shown" with the reason, and the reply's text stays as written.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from ..contracts import schema_errors

SCHEMA = "visual-block.schema.json"
LANG = "recallspring-visual"
MAX_BLOCKS = 4
MAX_BLOCK_CHARS = 20_000
MAX_SLIDER_STEPS = 2000
_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+#.-]*)\s*$")

INSTRUCTIONS = f"""
Visual explanations: when a diagram genuinely makes something easier to understand (a process, a comparison, a
timeline, how concepts relate, numeric data, or a parameter worth exploring), you may add up to 2 visual blocks.
Explain in words as usual; a visual only complements the text. Write each visual as a fenced code block with the
language tag {LANG} that contains exactly one JSON object and nothing else:
{{"type": "...", "title": "≤120 chars", "alt_text": "a complete text description of what it shows, ≤700 chars",
"illustrative": true, "data": {{...}}}}
Set "illustrative" to true whenever numbers or details are examples rather than established facts.
Allowed types and their "data":
- "process_flow" (steps in order) or "concept_map" (how ideas relate): {{"nodes": [{{"id": "a", "label": "≤140
  chars"}}] (1-18 nodes), "edges": [{{"from": "a", "to": "b"}}] (up to 30, using node ids)}}
- "comparison": {{"columns": ["Item A", "Item B"] (2-4 items compared), "rows": [{{"criterion": "...", "values": ["for
  A", "for B"]}}] (1-12 rows; one value per column)}}
- "timeline": {{"events": [{{"label": "1950 or step name", "description": "≤200 chars"}}] (2-20, in order)}}
- "data_chart": {{"chart": "line" | "bar" | "scatter", "x_label": "...", "y_label": "...", "points": [{{"x": number or
  text, "y": number}}] (2-50)}}
- "interactive_parameter" (a slider the learner moves): {{"parameter": "name and unit", "minimum": n, "maximum": n,
  "step": n, "initial": n, "preset": "linear_growth" (y = p·x) | "exponential_decay" (y = e^(−p·x)) |
  "quadratic_curve" (y = p·x²) | "unit_circle" (angle p in degrees)}}
Write titles, labels and descriptions in the learner's language. Never write HTML, SVG, CSS, JavaScript, Mermaid or any
other drawing code: it is not run and is shown only as text.
""".strip()


def fenced_blocks(text: str) -> list[str]:
    """The bodies of ``recallspring-visual`` fences, in order (an unclosed fence runs to the end, as in the web
    app's Markdown)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        marker, lang = m.group(1), m.group(2).lower()
        body: list[str] = []
        i += 1
        while i < len(lines) and not lines[i].strip().startswith(marker):
            body.append(lines[i])
            i += 1
        i += 1
        if lang == LANG:
            out.append("\n".join(body))
    return out


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _rule_errors(block: dict[str, Any]) -> list[str]:
    """What the schema cannot say: references, matching lengths and sane numbers."""
    kind, data = block["type"], block["data"]
    if kind in ("process_flow", "concept_map"):
        ids = [n["id"] for n in data["nodes"]]
        if len(set(ids)) != len(ids):
            return ["two nodes share an id"]
        known = set(ids)
        if any(e["from"] not in known or e["to"] not in known for e in data["edges"]):
            return ["an edge points to a node that does not exist"]
    elif kind == "comparison":
        width = len(data["columns"])
        if any(len(r["values"]) != width for r in data["rows"]):
            return ["each row needs one value per column"]
    elif kind == "data_chart":
        if not all(_finite(p["y"]) for p in data["points"]):
            return ["a y value is not a finite number"]
        xs = [p["x"] for p in data["points"]]
        if data["chart"] == "scatter" and not all(_finite(x) for x in xs):
            return ["a scatter chart needs numeric x values"]
    elif kind == "interactive_parameter":
        lo, hi, step, start = data["minimum"], data["maximum"], data["step"], data["initial"]
        if not all(_finite(v) for v in (lo, hi, step, start)):
            return ["slider values must be finite numbers"]
        if not lo < hi:
            return ["the minimum must be below the maximum"]
        if not lo <= start <= hi:
            return ["the starting value must lie between the minimum and the maximum"]
        if (hi - lo) / step > MAX_SLIDER_STEPS:
            return ["the slider has too many steps"]
    return []


def check(raw: str, *, grounded: bool = False) -> dict[str, Any]:
    """One block: ``{"ok": True, "block": {...}}`` or ``{"ok": False, "error": "..."}`` (no values echoed).

    ``grounded`` is False for providers that cannot see the learner's material (ChatGPT here): any ``source_refs``
    are removed, since they could not be real, and numeric charts are marked illustrative."""
    if len(raw) > MAX_BLOCK_CHARS:
        return {"ok": False, "error": "The visual is too large."}
    try:
        block = json.loads(raw, parse_constant=_no_constants)  # no NaN or Infinity
    except ValueError:
        return {"ok": False, "error": "The visual is not valid JSON."}
    if not isinstance(block, dict):
        return {"ok": False, "error": "The visual must be one JSON object."}
    errors = schema_errors(SCHEMA, block)
    if errors:
        return {"ok": False, "error": f"The visual does not match an allowed shape ({errors[0]})."}
    rules = _rule_errors(block)
    if rules:
        return {"ok": False, "error": f"The visual is inconsistent: {rules[0]}."}
    if not grounded:
        block.pop("source_refs", None)
        if block["type"] == "data_chart":
            block["illustrative"] = True
    elif block["type"] == "data_chart" and not block.get("source_refs"):
        block["illustrative"] = True
    return {"ok": True, "block": block}


def from_reply(text: str, *, grounded: bool = False) -> list[dict[str, Any]]:
    """Every ``recallspring-visual`` block of a reply, checked, in order (beyond ``MAX_BLOCKS`` refused)."""
    out = []
    for i, raw in enumerate(fenced_blocks(text)):
        if i >= MAX_BLOCKS:
            out.append({"ok": False, "error": f"At most {MAX_BLOCKS} visuals are shown per reply."})
        else:
            out.append(check(raw, grounded=grounded))
    return out
