"""Liveness, readiness and service metadata endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.ai.registry import provider_status
from app.config.settings import settings
from app.db.session import SessionLocal
from app.services.storage import get_storage

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness probe")
def health() -> dict[str, object]:
    return {"status": "ok", "version": __version__, "environment": settings.ENV}


@router.get("/health/live", summary="Liveness probe (Kubernetes style)")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe with dependency checks")
def ready(response: Response) -> dict[str, object]:
    components: dict[str, dict[str, object]] = {}
    healthy = True

    started = time.perf_counter()
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        components["database"] = {
            "status": "ok",
            "dialect": "postgresql" if not settings.is_sqlite else "sqlite",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        healthy = False
        components["database"] = {"status": "error", "error": str(exc)[:200]}

    storage_ok, storage_detail = get_storage().health()
    healthy = healthy and storage_ok
    components["storage"] = {
        "status": "ok" if storage_ok else "error",
        "backend": get_storage().name,
        "detail": storage_detail,
    }

    if settings.REDIS_URL and not settings.is_sqlite:
        try:
            import redis

            client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
            client.ping()
            components["redis"] = {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            components["redis"] = {"status": "unavailable", "error": str(exc)[:160]}

    components["ai"] = {
        "status": "configured" if settings.ai_configured else "unavailable",
        "provider": settings.AI_PROVIDER,
        "model": settings.AI_MODEL if settings.ai_configured else None,
    }
    components["task_runner"] = {
        "status": "ok",
        "mode": "celery" if settings.celery_enabled else "local",
    }

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if healthy else "degraded", "components": components}


@router.get("/api/v1/system/info", tags=["System"], summary="Public service metadata")
def system_info() -> dict[str, object]:
    ai = provider_status()
    return {
        "name": settings.APP_NAME,
        "version": __version__,
        "environment": settings.ENV,
        "demo_mode": settings.DEMO_MODE,
        "api_prefix": settings.API_V1_PREFIX,
        "features": {
            "ai_investigation": settings.ai_configured,
            "embeddings": settings.embeddings_configured,
            "ocr": settings.OCR_ENABLED and settings.OCR_PROVIDER != "none",
            "celery": settings.celery_enabled,
            "n8n": bool(settings.N8N_BASE_URL),
            "storage_backend": settings.STORAGE_BACKEND,
        },
        "ai": {
            "llm_provider": ai.llm_provider,
            "llm_model": ai.llm_model if ai.llm_configured else None,
            "llm_configured": ai.llm_configured,
            "embedding_provider": ai.embedding_provider,
            "embeddings_configured": ai.embeddings_configured,
            "deterministic_stub": ai.is_stub,
        },
    }
