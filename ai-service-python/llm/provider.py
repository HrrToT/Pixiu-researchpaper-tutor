from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


DEFAULT_RESEARCH_OUTPUT_TOKENS = 2000


@dataclass(frozen=True)
class LLMRequest:
    prompt: str = ""
    messages: Optional[List[Dict[str, str]]] = None
    stop: Optional[List[str]] = None
    extra_body: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Optional[float] = None


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated: bool = False
    cached_input_tokens: Optional[int] = None
    cache_write_input_tokens: Optional[int] = None


@dataclass(frozen=True)
class LLMResult:
    provider: str
    model: str
    content: str
    usage: LLMUsage
    finish_reason: Optional[str] = None
    # Untrusted provider-reported label, distinct from the configured model ID.
    # It is audit metadata, not proof of underlying weights or a routing input.
    reported_model: Optional[str] = None
    provider_observation: Optional[Dict[str, Any]] = None


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str,
        retryable: bool = False,
        status_code: Optional[int] = None,
        failure_kind: Optional[str] = None,
        provider_observation: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.retryable = retryable
        self.status_code = status_code
        self.failure_kind = failure_kind
        self.provider_observation = provider_observation


@runtime_checkable
class LLMProvider(Protocol):
    def invoke(self, request: LLMRequest) -> LLMResult:
        ...
