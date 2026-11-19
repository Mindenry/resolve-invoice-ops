"""Rate limiting (slowapi) shared by the application and route decorators."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config.settings import settings


def _key(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return f"user:{principal.user_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_key,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    headers_enabled=True,
    strategy="fixed-window",
)
