"""HTTP request context, correlation ids and security headers."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config.settings import settings
from app.core.context import (
    RequestContext,
    clear_identity,
    correlation_id_var,
    http_context_var,
    request_id_var,
)
from app.core.logging import get_logger

logger = get_logger("http")

_IGNORED_PATHS = {"/health", "/health/live", "/health/ready", "/metrics"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming_id = request.headers.get("X-Request-ID", "")
        request_id = incoming_id if 0 < len(incoming_id) <= 64 else uuid.uuid4().hex
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        context = RequestContext(
            request_id=request_id,
            correlation_id=correlation_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            path=request.url.path,
            method=request.method,
        )
        request_id_token = request_id_var.set(request_id)
        correlation_token = correlation_id_var.set(correlation_id)
        http_token = http_context_var.set(context)
        structlog.contextvars.bind_contextvars(request_id=request_id, correlation_id=correlation_id)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            if request.url.path not in _IGNORED_PATHS:
                log = logger.info if status_code < 500 else logger.error
                log(
                    "request_completed",
                    method=request.method,
                    path=request.url.path,
                    status=status_code,
                    duration_ms=duration_ms,
                )
            structlog.contextvars.clear_contextvars()
            clear_identity()
            request_id_var.reset(request_id_token)
            correlation_id_var.reset(correlation_token)
            http_context_var.reset(http_token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith(settings.API_V1_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
