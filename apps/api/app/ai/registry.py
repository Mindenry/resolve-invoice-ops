"""Provider registry and availability reporting."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.base import EmbeddingProvider, LLMProvider
from app.ai.ollama_provider import OllamaEmbeddings, OllamaProvider
from app.ai.openai_provider import OpenAICompatibleEmbeddings, OpenAICompatibleProvider
from app.ai.stub_provider import StubEmbeddingProvider, StubLLMProvider
from app.config.settings import settings
from app.core.errors import AIUnavailableError


def build_llm_provider() -> LLMProvider | None:
    provider = settings.AI_PROVIDER
    if provider == "openai":
        if not settings.AI_API_KEY:
            return None
        return OpenAICompatibleProvider(
            base_url=settings.AI_BASE_URL, api_key=settings.AI_API_KEY, model=settings.AI_MODEL
        )
    if provider == "ollama":
        return OllamaProvider(base_url=settings.AI_BASE_URL, model=settings.AI_MODEL)
    if provider == "stub":
        return StubLLMProvider()
    return None


def build_embedding_provider() -> EmbeddingProvider | None:
    provider = settings.AI_EMBEDDING_PROVIDER
    if provider == "openai":
        api_key = settings.AI_EMBEDDING_API_KEY or settings.AI_API_KEY
        if not api_key:
            return None
        return OpenAICompatibleEmbeddings(
            base_url=settings.AI_EMBEDDING_BASE_URL or settings.AI_BASE_URL,
            api_key=api_key,
            model=settings.AI_EMBEDDING_MODEL,
            dimensions=settings.AI_EMBEDDING_DIM,
        )
    if provider == "ollama":
        return OllamaEmbeddings(
            base_url=settings.AI_EMBEDDING_BASE_URL or settings.AI_BASE_URL,
            model=settings.AI_EMBEDDING_MODEL,
            dimensions=settings.AI_EMBEDDING_DIM,
        )
    if provider == "stub":
        return StubEmbeddingProvider(dimensions=settings.AI_EMBEDDING_DIM)
    return None


def require_llm() -> LLMProvider:
    provider = build_llm_provider()
    if provider is None:
        raise AIUnavailableError(
            "No LLM provider is configured. Set AI_PROVIDER and the matching credentials.",
            details={"provider": settings.AI_PROVIDER},
        )
    return provider


def require_embeddings() -> EmbeddingProvider:
    provider = build_embedding_provider()
    if provider is None:
        raise AIUnavailableError(
            "No embedding provider is configured. Set AI_EMBEDDING_PROVIDER and the matching credentials.",
            details={"provider": settings.AI_EMBEDDING_PROVIDER},
        )
    return provider


@dataclass(slots=True)
class ProviderStatus:
    llm_configured: bool
    llm_provider: str
    llm_model: str
    embeddings_configured: bool
    embedding_provider: str
    embedding_model: str
    is_stub: bool


def provider_status() -> ProviderStatus:
    return ProviderStatus(
        llm_configured=settings.ai_configured,
        llm_provider=settings.AI_PROVIDER,
        llm_model=settings.AI_MODEL,
        embeddings_configured=settings.embeddings_configured,
        embedding_provider=settings.AI_EMBEDDING_PROVIDER,
        embedding_model=settings.AI_EMBEDDING_MODEL,
        is_stub=settings.AI_PROVIDER == "stub" or settings.AI_EMBEDDING_PROVIDER == "stub",
    )
