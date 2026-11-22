"""Which assistant did something: connector clients, the provider stored on their grades, and display names.

A grade from Codex counts exactly like one from Claude (owner decision 2026-11-21); only the label differs. The model
name comes from the assistant itself and is stored with ``model_reported_by = "assistant"``: unverified. ChatGPT in
RecallSpring's Chat (client ``chatgpt``, no token) is the exception: OpenAI reports the model, ``"provider"``.
"""

from __future__ import annotations

from typing import Any

# Connector token clients (connector_tokens.client, migration 0016) -> the provider stored on their assessments.
CLIENTS: dict[str, str] = {
    "claude": "claude_app",
    "codex": "codex_app",
    "antigravity": "antigravity_app",
    "chatgpt": "chatgpt",
}
CLIENT_NAMES: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "antigravity": "Antigravity",
    "chatgpt": "ChatGPT",
}
DEFAULT_LABEL: dict[str, str] = {"claude": "Claude Desktop", "codex": "Codex", "antigravity": "Antigravity"}

_PROVIDER_NAMES: dict[str, str] = {
    "claude_app": "Claude",
    "codex_app": "Codex",
    "antigravity_app": "Antigravity",
    "chatgpt": "ChatGPT",
    "siwc": "ChatGPT",
    "mock": "Simulated AI",
}


def provider_for(client: str | None) -> str:
    return CLIENTS.get(client or "claude", "claude_app")


def provenance(client: str | None, reported_model: str | None, assistant_model: str | None) -> dict[str, Any]:
    """Who wrote a question or simulation: ``reported_model`` is set only for ChatGPT in Chat (from OpenAI)."""
    if reported_model:
        return {"origin": "chatgpt_chat", "model": reported_model, "model_reported_by": "provider"}
    return {"origin": "claude_connector", "model": assistant_model, "model_reported_by": "assistant"}


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
    if evaluator_kind == "self":
        return {"name": "You (self-assessed)", "model": None}
    return {"name": "You", "model": None}
