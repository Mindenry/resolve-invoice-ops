"""Prometheus metrics for RESOLVE.

The API is the only component that knows the business state, so a small set of
gauges is refreshed on scrape and HTTP counters/histograms are recorded by
middleware. The endpoint is reachable only on the loopback API port; Prometheus
scrapes it over the internal Docker network.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.domain.enums import (
    ApprovalStatus,
    CaseStatus,
    DocumentStatus,
    ExceptionStatus,
    JobStatus,
    Priority,
)
from app.models.ai import ApprovalRequest
from app.models.audit import DomainEvent
from app.models.automation import BackgroundJob
from app.models.cases import Case, ExceptionRecord
from app.models.documents import Document, DocumentChunk
from app.models.finance import Invoice

logger = get_logger(__name__)

REQUEST_COUNT = Counter(
    "resolve_http_requests_total",
    "HTTP requests handled by the RESOLVE API",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "resolve_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
DB_UP = Gauge("resolve_db_up", "1 when the application database is reachable")
REDIS_UP = Gauge("resolve_redis_up", "1 when Redis is reachable")
STORAGE_UP = Gauge("resolve_storage_up", "1 when document storage is healthy")
AI_CONFIGURED = Gauge("resolve_ai_configured", "1 when an LLM provider is configured")
CASES_TOTAL = Gauge("resolve_cases_total", "Total cases")
CASES_OPEN = Gauge("resolve_cases_open", "Open/in-progress cases")
CASES_RESOLVED = Gauge("resolve_cases_resolved", "Resolved/closed cases")
CASES_CRITICAL = Gauge("resolve_cases_critical", "Open critical-priority cases")
CASES_OVERDUE = Gauge("resolve_cases_overdue", "Open cases past their due date")
EXCEPTIONS_OPEN = Gauge("resolve_exceptions_open", "Open exceptions")
INVOICES_TOTAL = Gauge("resolve_invoices_total", "Total invoices")
DOCUMENTS_TOTAL = Gauge("resolve_documents_total", "Total documents")
CHUNKS_TOTAL = Gauge("resolve_chunks_total", "Document chunks")
CHUNK_VECTORS_TOTAL = Gauge("resolve_chunk_vectors_total", "Chunks with a pgvector representation")
APPROVALS_PENDING = Gauge("resolve_approvals_pending", "Pending approval requests")
VECTOR_DIMENSION = Gauge("resolve_vector_dimension", "Configured embedding dimension")
QUEUE_BACKLOG = Gauge("resolve_approval_backlog", "Pending approvals (alias for dashboards)")
DOCUMENTS_FAILED = Gauge("resolve_documents_failed", "Documents whose processing failed")
JOBS_FAILED = Gauge("resolve_jobs_failed", "Background jobs in FAILED state")
OUTBOX_PENDING = Gauge("resolve_outbox_pending", "Domain events waiting for webhook fan-out")
OUTBOX_OLDEST_SECONDS = Gauge(
    "resolve_outbox_oldest_seconds", "Age of the oldest pending domain event in seconds"
)

router = APIRouter(tags=["Observability"])


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request, call_next: Callable[[object], Awaitable[Response]]
    ) -> Response:  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        label = getattr(route, "path", None) or request.url.path
        REQUEST_COUNT.labels(request.method, label, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, label).observe(time.perf_counter() - started)
        return response


def _refresh_gauges() -> None:
    VECTOR_DIMENSION.set(settings.AI_EMBEDDING_DIM)
    AI_CONFIGURED.set(1 if settings.ai_configured else 0)
    try:
        from app.services.storage import get_storage

        storage_ok, _ = get_storage().health()
        STORAGE_UP.set(1 if storage_ok else 0)
    except Exception:  # noqa: BLE001 - metrics must not fail the scrape
        STORAGE_UP.set(0)

    try:
        import redis

        redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2).ping()
        REDIS_UP.set(1)
    except Exception:  # noqa: BLE001
        REDIS_UP.set(0)

    db = SessionLocal()
    try:
        db.execute(select(1))
        DB_UP.set(1)
    except Exception as exc:  # noqa: BLE001
        DB_UP.set(0)
        logger.warning("metrics_db_unreachable", error=str(exc)[:200])
        db.close()
        return

    def _scalar(statement) -> int:  # type: ignore[no-untyped-def]
        return int(db.scalar(statement) or 0)

    try:
        CASES_TOTAL.set(_scalar(select(func.count()).select_from(Case)))
        CASES_OPEN.set(
            _scalar(
                select(func.count())
                .select_from(Case)
                .where(
                    Case.status.in_(
                        [
                            CaseStatus.OPEN,
                            CaseStatus.INVESTIGATING,
                            CaseStatus.AWAITING_APPROVAL,
                            CaseStatus.RESOLUTION_IN_PROGRESS,
                        ]
                    )
                )
            )
        )
        EXCEPTIONS_OPEN.set(
            _scalar(
                select(func.count())
                .select_from(ExceptionRecord)
                .where(ExceptionRecord.status == ExceptionStatus.OPEN)
            )
        )
        CASES_RESOLVED.set(
            _scalar(
                select(func.count())
                .select_from(Case)
                .where(Case.status.in_([CaseStatus.RESOLVED, CaseStatus.CLOSED]))
            )
        )
        CASES_CRITICAL.set(
            _scalar(
                select(func.count())
                .select_from(Case)
                .where(
                    Case.priority == Priority.URGENT,
                    Case.status.notin_(
                        [CaseStatus.RESOLVED, CaseStatus.CLOSED, CaseStatus.CANCELLED]
                    ),
                )
            )
        )
        CASES_OVERDUE.set(
            _scalar(
                select(func.count())
                .select_from(Case)
                .where(
                    Case.due_at.is_not(None),
                    Case.due_at < utcnow(),
                    Case.status.notin_(
                        [CaseStatus.RESOLVED, CaseStatus.CLOSED, CaseStatus.CANCELLED]
                    ),
                )
            )
        )
        INVOICES_TOTAL.set(_scalar(select(func.count()).select_from(Invoice)))
        DOCUMENTS_TOTAL.set(_scalar(select(func.count()).select_from(Document)))
        CHUNKS_TOTAL.set(_scalar(select(func.count()).select_from(DocumentChunk)))
        pending = _scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING)
        )
        APPROVALS_PENDING.set(pending)
        QUEUE_BACKLOG.set(pending)
        DOCUMENTS_FAILED.set(
            _scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.status == DocumentStatus.FAILED)
            )
        )
        JOBS_FAILED.set(
            _scalar(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.status == JobStatus.FAILED)
            )
        )
        OUTBOX_PENDING.set(
            _scalar(
                select(func.count())
                .select_from(DomainEvent)
                .where(DomainEvent.status == "PENDING")
            )
        )
        oldest = db.scalar(
            select(func.min(DomainEvent.created_at)).where(DomainEvent.status == "PENDING")
        )
        if oldest is not None:
            OUTBOX_OLDEST_SECONDS.set(max(0.0, (utcnow() - oldest).total_seconds()))
    except Exception as exc:  # noqa: BLE001 - a broken query must not mark the DB down
        logger.warning("metrics_business_query_failed", error=str(exc)[:200])

    try:
        from sqlalchemy import text

        vectors = db.scalar(
            text("select count(embedding_vec) from document_chunks where embedding_vec is not null")
        )
        CHUNK_VECTORS_TOTAL.set(int(vectors or 0))
    except Exception:  # noqa: BLE001 - pgvector is optional
        CHUNK_VECTORS_TOTAL.set(0)
    finally:
        db.close()


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    _refresh_gauges()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
