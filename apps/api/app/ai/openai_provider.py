"""OpenAI-compatible chat and embedding provider.

Works with the official OpenAI API, Azure-style gateways that expose the same paths, and
self-hosted OpenAI-compatible servers (vLLM, LM Studio, OpenRouter). Base URL and model
are configuration, never hardcoded.
"""

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


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            if schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "structured_output", "schema": schema, "strict": False},
                }
            else:
                payload["response_format"] = {"type": "json_object"}

        watch = Stopwatch()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("AI provider timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"AI provider request failed: {exc}", retryable=True) from exc

        if response.status_code == 429:
            raise ProviderError("AI provider rate limit reached.", retryable=True, rate_limited=True)
        if response.status_code >= 500:
            raise ProviderError(
                f"AI provider returned {response.status_code}.", retryable=True
            )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise ProviderError(
                f"AI provider rejected the request ({response.status_code}): {detail}", retryable=False
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("AI provider returned an unexpected response shape.", retryable=True) from exc

        usage = data.get("usage") or {}
        prompt_text = "\n".join(m.content for m in messages)
        return LLMResult(
            content=content,
            provider=self.name,
            model=data.get("model") or self.model,
            input_tokens=int(usage.get("prompt_tokens") or estimate_tokens(prompt_text)),
            output_tokens=int(usage.get("completion_tokens") or estimate_tokens(content)),
            latency_ms=watch.elapsed_ms,
            raw={"finish_reason": data["choices"][0].get("finish_reason")},
        )

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code < 400:
                return True, f"{self.name} reachable ({self.model})"
            return False, f"{self.name} returned HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            return False, f"{self.name} unreachable: {exc}"


class OpenAICompatibleEmbeddings(EmbeddingProvider):
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str, dimensions: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def embed(self, texts: list[str], *, timeout: float = 60.0) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.name, self.model, self.dimensions)
        watch = Stopwatch()
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings", headers=self._headers(), json=payload
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("Embedding provider timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Embedding request failed: {exc}", retryable=True) from exc
        if response.status_code == 429:
            raise ProviderError("Embedding rate limit reached.", retryable=True, rate_limited=True)
        if response.status_code >= 400:
            raise ProviderError(
                f"Embedding provider rejected the request ({response.status_code}).", retryable=False
            )
        data = response.json()
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise ProviderError("Embedding response shape was invalid.", retryable=True) from exc
        usage = data.get("usage") or {}
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=data.get("model") or self.model,
            dimensions=len(vectors[0]) if vectors else self.dimensions,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            latency_ms=watch.elapsed_ms,
        )

    async def health(self) -> tuple[bool, str]:
        try:
            result = await self.embed(["health check"], timeout=8.0)
            return True, f"{self.name} embeddings reachable ({len(result.vectors[0])} dims)"
        except ProviderError as exc:
            return False, str(exc)
