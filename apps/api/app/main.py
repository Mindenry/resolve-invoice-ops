"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.api.automation import router as automation_router
from app.api.health import router as health_router
from app.api.metrics import MetricsMiddleware
from app.api.metrics import router as metrics_router
from app.api.router import api_router
from app.config.settings import settings
from app.core.context import current_request_id
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import limiter
from app.db.session import SessionLocal, engine, init_models
from app.middleware.request_context import RequestContextMiddleware, SecurityHeadersMiddleware

logger = get_logger("app")

OPENAPI_TAGS = [
    {"name": "Authentication", "description": "Sessions, refresh rotation and password security."},
    {"name": "Users", "description": "Profiles and organization membership."},
    {"name": "Organizations", "description": "Organization settings, roles and permissions."},
    {"name": "Vendors", "description": "Vendor master data, duplicate detection and merges."},
    {"name": "Purchase Orders", "description": "Purchase order lifecycle and invoice matching data."},
    {"name": "Invoices", "description": "Invoice lifecycle, deterministic validation and matching."},
    {"name": "Exceptions", "description": "Detection rules, exception queue and triage."},
    {"name": "Cases", "description": "Case workspace, assignment, SLA, comments and merges."},
    {"name": "Documents", "description": "Upload, processing, extraction review and knowledge retrieval."},
    {"name": "Investigation", "description": "AI investigation with evidence validation."},
    {"name": "Resolutions", "description": "Resolution proposals, approvals and audited execution."},
    {"name": "Automation", "description": "Integrations, webhooks, n8n workflows and background jobs."},
    {"name": "Notifications", "description": "In-app, email and webhook notifications."},
    {"name": "Analytics", "description": "Command center metrics and operational analytics."},
    {"name": "AI Evaluation", "description": "Evaluation datasets, runs and real measured metrics."},
    {"name": "Audit", "description": "Immutable audit trail."},
    {"name": "Health", "description": "Liveness and readiness probes."},
    {"name": "System", "description": "Service metadata."},
]


def create_app() -> FastAPI:
    configure_logging()
    problems = settings.validate_runtime()
    if problems:
        raise RuntimeError("Invalid production configuration: " + "; ".join(problems))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "application_starting",
            version=__version__,
            environment=settings.ENV,
            database="postgresql" if not settings.is_sqlite else "sqlite",
            task_runner="celery" if settings.celery_enabled else "local",
            ai_provider=settings.AI_PROVIDER,
        )
        if settings.AUTO_CREATE_SCHEMA and not settings.is_production:
            init_models()
            from app.modules.auth.service import ensure_rbac

            with SessionLocal() as db:
                ensure_rbac(db)
                db.commit()
        yield
        logger.info("application_stopping")

    app = FastAPI(
        title="RESOLVE API",
        summary="Intelligent exception management, AI investigation and workflow resolution",
        description=(
            "RESOLVE detects operational exceptions, investigates them with evidence-grounded AI, "
            "and resolves them through audited human-in-the-loop workflows. "
            "Authentication uses a bearer access token plus a rotating refresh cookie. "
            "Organization-scoped endpoints honour the X-Organization-Id header."
        ),
        version=__version__,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        contact={"name": "RESOLVE", "url": "https://github.com/resolve/resolve"},
        license_info={"name": "MIT"},
    )

    app.state.limiter = limiter
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Organization-Id",
            "X-Organization-Slug",
            "X-Request-ID",
            "X-Correlation-ID",
        ],
        expose_headers=["X-Request-ID", "X-Correlation-ID", "Retry-After"],
        max_age=600,
    )

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(automation_router, prefix=settings.API_V1_PREFIX)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    _register_error_handlers(app)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "name": "RESOLVE API",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
            "api": settings.API_V1_PREFIX,
        }

    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        headers: dict[str, str] = {}
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = 'Bearer realm="resolve"'
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(request_id=current_request_id()),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for error in exc.errors():
            errors.append(
                {
                    "loc": ".".join(str(part) for part in error.get("loc", [])),
                    "message": error.get("msg", "Invalid value"),
                    "type": error.get("type", "value_error"),
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request payload is invalid.",
                    "details": errors,
                    "request_id": current_request_id(),
                }
            },
        )

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limited",
                    "message": "Too many requests. Please retry later.",
                    "request_id": current_request_id(),
                }
            },
            headers={"Retry-After": str(getattr(getattr(exc, "detail", None), "limit", 60))},
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("database_integrity_error", error=str(exc.orig)[:300])
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "conflict",
                    "message": "The request conflicts with existing data.",
                    "request_id": current_request_id(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred. The incident has been logged.",
                    "request_id": current_request_id(),
                }
            },
        )


app = create_app()


# Expose the engine for operational scripts and health checks.
__all__ = ["app", "create_app", "engine"]
