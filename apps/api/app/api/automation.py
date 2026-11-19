"""Service-to-service automation endpoints used by n8n.

These endpoints are not part of the user-facing API surface. They are only
reachable from the Docker network (the API is bound to loopback on the host) and
require a shared secret. The Redis-backed claim store provides durable,
cluster-safe idempotency for webhook consumers so retried deliveries cannot
create duplicate notifications, cases or emails.
"""

from __future__ import annotations

import hmac
from typing import Annotated

import redis
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.core.errors import ServiceUnavailableError, UnauthorizedError

router = APIRouter(prefix="/internal/automation", tags=["Automation (internal)"])

CLAIM_PREFIX = "resolve:automation:claim:"


class ClaimRequest(BaseModel):
    key: str = Field(min_length=8, max_length=200)
    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)


class ClaimResponse(BaseModel):
    key: str
    claimed: bool
    ttl_seconds: int


def _redis() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)


@router.post("/claims", response_model=ClaimResponse, summary="Claim an automation idempotency key")
def claim(
    payload: ClaimRequest,
    x_automation_secret: Annotated[str | None, Header(alias="X-Automation-Secret")] = None,
) -> ClaimResponse:
    expected = settings.N8N_WEBHOOK_SECRET or ""
    supplied = x_automation_secret or ""
    if not expected or not hmac.compare_digest(expected, supplied):
        raise UnauthorizedError("Invalid automation secret.", code="invalid_automation_secret")
    try:
        client = _redis()
        claimed = bool(
            client.set(f"{CLAIM_PREFIX}{payload.key}", "1", nx=True, ex=payload.ttl_seconds)
        )
    except redis.RedisError as exc:  # fail closed: consumers must not process twice
        raise ServiceUnavailableError(
            "Idempotency store is unavailable.", code="claim_store_unavailable"
        ) from exc
    return ClaimResponse(key=payload.key, claimed=claimed, ttl_seconds=payload.ttl_seconds)
