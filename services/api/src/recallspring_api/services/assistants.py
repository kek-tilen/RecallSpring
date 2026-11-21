"""Which assistant did something: connector clients, the provider stored on their grades, and display names.

A grade from Codex counts exactly like one from Claude (owner decision 2026-11-21); only the label differs. The model
name comes from the assistant itself and is stored with ``model_reported_by = "assistant"``: unverified.
"""

from __future__ import annotations

from typing import Any

# Connector token clients (connector_tokens.client, migration 0016) -> the provider stored on their assessments.
CLIENTS: dict[str, str] = {"claude": "claude_app", "codex": "codex_app"}
CLIENT_NAMES: dict[str, str] = {"claude": "Claude", "codex": "Codex"}
DEFAULT_LABEL: dict[str, str] = {"claude": "Claude Desktop", "codex": "Codex"}

_PROVIDER_NAMES: dict[str, str] = {
    "claude_app": "Claude",
    "codex_app": "Codex",
    "chatgpt": "ChatGPT",
    "siwc": "ChatGPT",
    "mock": "Simulated AI",
}


def provider_for(client: str | None) -> str:
    return CLIENTS.get(client or "claude", "claude_app")


def name_of(client: str | None) -> str:
    return CLIENT_NAMES.get(client or "claude", "Claude")


def provider_name(provider: str | None) -> str:
    """Display name for an assessment's provider; old connector grades (``claude_app``) stay "Claude"."""
    if provider is None:
        return "AI"
    return _PROVIDER_NAMES.get(provider, provider)


def grader(evaluator_kind: str | None, provider: str | None, model: str | None) -> dict[str, Any] | None:
    """Who graded, for the web app: ``{"name": "Codex", "model": "gpt-…"}``; None for ungraded attempts."""
    if evaluator_kind is None:
        return None
    if evaluator_kind == "ai":
        return {"name": provider_name(provider), "model": model}
    if evaluator_kind == "deterministic":
        return {"name": "RecallSpring (answer key)", "model": None}
    return {"name": "You", "model": None}
