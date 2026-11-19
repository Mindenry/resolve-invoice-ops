"""Provider-neutral AI interfaces."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(slots=True)
class LLMResult:
    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    dimensions: int
    input_tokens: int = 0
    latency_ms: int = 0


class ProviderError(RuntimeError):
    """Transport/provider failure. `retryable` guides the bounded retry loop."""

    def __init__(self, message: str, *, retryable: bool = True, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.rate_limited = rate_limited


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        json_mode: bool = True,
        schema: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> LLMResult: ...

    async def health(self) -> tuple[bool, str]: ...


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    async def embed(self, texts: list[str], *, timeout: float = 60.0) -> EmbeddingResult: ...

    async def health(self) -> tuple[bool, str]: ...


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)


def estimate_tokens(text: str) -> int:
    """Rough estimation used only when a provider does not return usage."""
    return max(1, len(text) // 4)
