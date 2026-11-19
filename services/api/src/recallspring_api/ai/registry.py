"""Per-task provider routing for in-app AI (Mode B).

v1 supports ``none`` and ``mock``; real adapters (anthropic_api, siwc, openai_compatible) plug in here behind
the same ``LLMProvider`` interface, together with persisted routing, limits and the usage ledger.
"""

from __future__ import annotations

from ..config import get_settings
from .mock import MOCK_MODEL, MockProvider
from .provider import LLMProvider, ProviderNotConfigured, Task


def provider_for(task: Task) -> tuple[LLMProvider, str]:
    settings = get_settings()
    name = settings.ai_evaluation_provider if task == "evaluation" else settings.ai_question_provider
    if name == "mock":
        return MockProvider(settings.mock_ai_behavior), MOCK_MODEL
    raise ProviderNotConfigured(f"no in-app provider configured for {task}")
