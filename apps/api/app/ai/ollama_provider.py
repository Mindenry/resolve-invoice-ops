"""Local LLM and embedding provider for Ollama."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.ai.base import (
    ChatMessage,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    ProviderError,
    Stopwatch,
    estimate_tokens,
)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, *, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        json_mode: bool = True,
        schema: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = schema or "json"
        watch = Stopwatch()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError("Ollama timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            raise ProviderError(f"Ollama returned HTTP {response.status_code}.", retryable=False)
        data = response.json()
        content = (data.get("message") or {}).get("content", "")
        return LLMResult(
            content=content,
            provider=self.name,
            model=data.get("model") or self.model,
            input_tokens=int(data.get("prompt_eval_count") or estimate_tokens(" ".join(m.content for m in messages))),
            output_tokens=int(data.get("eval_count") or estimate_tokens(content)),
            latency_ms=watch.elapsed_ms,
        )

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            if response.status_code < 400:
                models = [m.get("name") for m in response.json().get("models", [])]
                if self.model not in models and f"{self.model}:latest" not in models:
                    return False, f"Ollama is reachable but model '{self.model}' is not installed."
                return True, f"Ollama reachable ({self.model})"
            return False, f"Ollama returned HTTP {response.status_code}"
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            return False, f"Ollama unreachable: {exc}"


class OllamaEmbeddings(EmbeddingProvider):
    name = "ollama"

    def __init__(self, *, base_url: str, model: str, dimensions: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: list[str], *, timeout: float = 60.0) -> EmbeddingResult:
        watch = Stopwatch()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama embedding request failed: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            raise ProviderError("Ollama rejected the embedding request.", retryable=False)
        data = response.json()
        vectors = data.get("embeddings") or []
        if not vectors:
            raise ProviderError("Ollama returned no embeddings.", retryable=True)
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            dimensions=len(vectors[0]),
            latency_ms=watch.elapsed_ms,
        )

    async def health(self) -> tuple[bool, str]:
        try:
            await self.embed(["health"], timeout=8.0)
            return True, f"Ollama embeddings reachable ({self.model})"
        except ProviderError as exc:
            return False, str(exc)
