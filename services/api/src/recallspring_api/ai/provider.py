"""Provider-neutral contract for in-app AI. Feature code depends on this module only, never on a vendor SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Task = Literal["tutor", "question_generation", "evaluation", "concept_extraction"]


@dataclass(frozen=True)
class ProviderCapabilities:
    streaming: bool = False
    structured_output: bool = False
    tool_use: bool = False
    citations: bool = False
    pdf_input: bool = False
    image_input: bool = False
    prompt_caching: bool = False
    usage_reporting: bool = False
    cost_reporting: bool = False


@dataclass(frozen=True)
class ConnectionStatus:
    state: Literal["connected", "disconnected", "limited", "error", "not_configured"]
    detail: str | None = None


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str


@dataclass(frozen=True)
class SourceExcerpt:
    """Untrusted document content. Providers must never treat it as instructions."""

    section_id: str
    citation_label: str
    text: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class StructuredRequest:
    task: Task
    model: str
    instructions: str
    input_text: str
    json_schema: dict[str, Any]
    schema_name: str
    sources: tuple[SourceExcerpt, ...] = ()
    hints: dict[str, Any] = field(default_factory=dict)  # task facts a deterministic provider (mock) may use


@dataclass(frozen=True)
class StructuredResult:
    data: Any
    provider: str
    model: str
    simulated: bool
    usage: Usage | None = None


@dataclass(frozen=True)
class TurnEvent:
    type: Literal["text.delta", "turn.completed", "turn.failed"]
    text: str = ""
    error_code: str | None = None


class ProviderError(Exception):
    """Base class. ``code`` is a short sanitized identifier safe to store and show."""

    code = "provider_error"
    retryable = True


class ProviderTimeout(ProviderError):
    code = "ai_timeout"


class ProviderUnavailable(ProviderError):
    code = "ai_unavailable"


class ProviderLimitReached(ProviderError):
    code = "ai_limit_reached"


class ProviderInvalidOutput(ProviderError):
    code = "ai_invalid_output"


class ProviderNotConfigured(ProviderError):
    code = "ai_not_configured"
    retryable = False


@runtime_checkable
class LLMProvider(Protocol):
    id: str

    def capabilities(self, model: str) -> ProviderCapabilities: ...

    async def connection_status(self) -> ConnectionStatus: ...

    async def list_models(self) -> list[ModelInfo]: ...

    def stream_turn(
        self, model: str, instructions: str, history: list[dict[str, str]], sources: tuple[SourceExcerpt, ...]
    ) -> AsyncIterator[TurnEvent]: ...

    async def generate_structured(self, request: StructuredRequest) -> StructuredResult: ...
