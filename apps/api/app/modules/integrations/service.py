"""Integration registry, webhooks, workflow executions and outbox fan-out."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import BadRequestError, ConflictError, IntegrationError, NotFoundError
from app.core.logging import get_logger
from app.core.security import utcnow
from app.domain.enums import (
    Direction,
    EventType,
    IntegrationKind,
    IntegrationStatus,
    JobStatus,
    WebhookStatus,
    WorkflowStatus,
)
from app.models.audit import DomainEvent
from app.models.automation import (
    BackgroundJob,
    Integration,
    IntegrationCredential,
    WebhookEvent,
    WorkflowExecution,
)
from app.modules.integrations.workflows import WORKFLOW_TEMPLATES, get_template
from app.services.audit import record_audit
from app.services.storage import get_storage

logger = get_logger(__name__)

SENSITIVE_KEYS = {"api_key", "secret", "token", "password", "authorization", "signing_secret"}


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    def _redact(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {str(k): _redact(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact(item, key) for item in value]
        if key and any(marker in key.lower() for marker in SENSITIVE_KEYS) and value:
            return "••••••••"
        return value

    return {str(key): _redact(value, str(key)) for key, value in (config or {}).items()}


def split_secret_config(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Move top-level secret-like config values into encrypted credentials."""
    clean: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    for key, value in (config or {}).items():
        if any(marker in key.lower() for marker in SENSITIVE_KEYS) and value:
            secrets[key] = str(value)
        else:
            clean[key] = value
    return clean, secrets


def _validate_http_url(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BadRequestError(
            "Integration URLs must be absolute http(s) URLs.", code="invalid_integration_url"
        )
    return url


def list_integrations(db: Session, *, org_id: uuid.UUID) -> list[Integration]:
    return list(
        db.scalars(
            select(Integration).where(Integration.org_id == org_id).order_by(Integration.name)
        )
    )


def get_integration(db: Session, *, org_id: uuid.UUID, integration_id: uuid.UUID) -> Integration:
    integration = db.scalar(
        select(Integration).where(Integration.id == integration_id, Integration.org_id == org_id)
    )
    if integration is None:
        raise NotFoundError("Integration not found.", code="integration_not_found")
    return integration


def _validate_integration_config(config: dict[str, Any], kind: IntegrationKind) -> None:
    """Reject unusable URLs at write time instead of failing delivery later."""
    if kind not in {IntegrationKind.WEBHOOK, IntegrationKind.N8N}:
        return
    for key in ("webhook_url", "base_url"):
        value = config.get(key)
        if value:
            _validate_http_url(str(value))


def create_integration(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    name: str,
    kind: IntegrationKind,
    config: dict[str, Any],
    event_filter: list[str],
    is_enabled: bool = True,
    credentials: dict[str, str] | None = None,
) -> Integration:
    existing = db.scalar(
        select(Integration).where(Integration.org_id == org_id, Integration.name == name)
    )
    if existing is not None:
        raise ConflictError("An integration with this name already exists.", code="integration_name_taken")
    clean_config, extracted_secrets = split_secret_config(config or {})
    _validate_integration_config(clean_config, kind)
    all_credentials = {**extracted_secrets, **(credentials or {})}
    integration = Integration(
        org_id=org_id,
        name=name,
        kind=kind,
        config=clean_config,
        event_filter=event_filter or [],
        is_enabled=is_enabled,
        status=IntegrationStatus.UNTESTED if is_enabled else IntegrationStatus.DISABLED,
        created_by_id=actor_id,
    )
    db.add(integration)
    db.flush()
    for key, value in all_credentials.items():
        db.add(
            IntegrationCredential(
                integration_id=integration.id, key=key, encrypted_value=encrypt_secret(value)
            )
        )
    record_audit(
        db,
        org_id=org_id,
        action="integration.created",
        entity_type="integration",
        entity_id=integration.id,
        summary=f"Integration '{name}' created ({kind.value})",
        actor_id=actor_id,
        after={"kind": kind.value, "config": redact_config(clean_config)},
    )
    return integration


def update_integration(
    db: Session, *, integration: Integration, actor_id: uuid.UUID | None, changes: dict[str, Any]
) -> Integration:
    before = {"name": integration.name, "enabled": integration.is_enabled}
    for field, value in changes.items():
        if field == "config" and value is not None:
            clean_config, extracted_secrets = split_secret_config(value)
            _validate_integration_config(clean_config, integration.kind)
            integration.config = clean_config
            if extracted_secrets:
                set_credentials(
                    db, integration=integration, actor_id=actor_id, credentials=extracted_secrets
                )
        elif field == "event_filter" and value is not None:
            integration.event_filter = value
        elif field == "is_enabled" and value is not None:
            integration.is_enabled = value
            if not value:
                integration.status = IntegrationStatus.DISABLED
        elif field == "name" and value:
            integration.name = value
    record_audit(
        db,
        org_id=integration.org_id,
        action="integration.updated",
        entity_type="integration",
        entity_id=integration.id,
        summary=f"Integration '{integration.name}' updated",
        actor_id=actor_id,
        before=before,
        after={"name": integration.name, "enabled": integration.is_enabled},
    )
    return integration


def set_credentials(
    db: Session, *, integration: Integration, actor_id: uuid.UUID | None, credentials: dict[str, str]
) -> int:
    count = 0
    for key, value in credentials.items():
        row = db.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_id == integration.id,
                IntegrationCredential.key == key,
            )
        )
        if row is None:
            db.add(
                IntegrationCredential(
                    integration_id=integration.id, key=key, encrypted_value=encrypt_secret(value)
                )
            )
        else:
            row.encrypted_value = encrypt_secret(value)
        count += 1
    record_audit(
        db,
        org_id=integration.org_id,
        action="integration.credentials_updated",
        entity_type="integration",
        entity_id=integration.id,
        summary=f"{count} credential(s) updated",
        actor_id=actor_id,
        after={"keys": sorted(credentials)},
    )
    return count


def credential_keys(db: Session, integration: Integration) -> list[str]:
    return list(
        db.scalars(
            select(IntegrationCredential.key).where(
                IntegrationCredential.integration_id == integration.id
            )
        )
    )


def get_credential(db: Session, integration: Integration, key: str) -> str | None:
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.integration_id == integration.id,
            IntegrationCredential.key == key,
        )
    )
    if row is None:
        return None
    return decrypt_secret(row.encrypted_value)


def _resolve_secret(db: Session, integration: Integration, key: str) -> str:
    return get_credential(db, integration, key) or settings.N8N_API_KEY or settings.N8N_WEBHOOK_SECRET


def test_connection(db: Session, *, org_id: uuid.UUID, integration_id: uuid.UUID) -> dict[str, Any]:
    integration = get_integration(db, org_id=org_id, integration_id=integration_id)
    started = time.perf_counter()
    ok = False
    detail = ""
    try:
        if integration.kind in {IntegrationKind.WEBHOOK, IntegrationKind.N8N, IntegrationKind.REST}:
            if integration.kind == IntegrationKind.N8N:
                base_url = str(integration.config.get("base_url") or settings.N8N_BASE_URL or "").rstrip("/")
                if not base_url:
                    detail = "n8n base_url is not configured."
                else:
                    _validate_http_url(base_url)
                    api_key = _resolve_secret(db, integration, "api_key")
                    headers = {"X-N8N-API-KEY": api_key} if api_key and settings.N8N_API_KEY else {}
                    with httpx.Client(timeout=8.0) as client:
                        response = client.get(f"{base_url}/api/v1/workflows", headers=headers, params={"limit": 1})
                    ok = response.status_code < 400
                    detail = f"n8n responded HTTP {response.status_code}"
            else:
                url = str(integration.config.get("webhook_url") or integration.config.get("base_url") or "")
                if not url:
                    detail = "A webhook_url or base_url is required."
                else:
                    _validate_http_url(url)
                    with httpx.Client(timeout=8.0) as client:
                        response = client.request(
                            str(integration.config.get("test_method", "HEAD")).upper(), url
                        )
                    ok = response.status_code < 500
                    detail = f"Endpoint responded HTTP {response.status_code}"
        elif integration.kind == IntegrationKind.MINIO:
            ok, detail = get_storage().health()
        elif integration.kind == IntegrationKind.EMAIL:
            ok = settings.EMAIL_BACKEND in {"sink", "smtp"}
            detail = f"Email backend: {settings.EMAIL_BACKEND}"
        elif integration.kind in {IntegrationKind.CSV, IntegrationKind.EXCEL}:
            ok = True
            detail = "File import adapters are local and require no connection."
        else:
            detail = f"Unsupported integration kind {integration.kind.value}."
    except httpx.HTTPError as exc:
        detail = f"Connection failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        detail = f"Connection failed: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    integration.last_checked_at = utcnow()
    if ok:
        integration.status = IntegrationStatus.CONNECTED
        integration.last_success_at = utcnow()
        integration.last_error = None
    else:
        integration.status = IntegrationStatus.DEGRADED if integration.is_enabled else IntegrationStatus.DISABLED
        integration.last_error = detail[:2000]
    record_audit(
        db,
        org_id=org_id,
        action="integration.tested",
        entity_type="integration",
        entity_id=integration.id,
        summary=f"Connection test {'succeeded' if ok else 'failed'}: {detail}",
        after={"ok": ok, "detail": detail[:500]},
    )
    return {"ok": ok, "status": integration.status.value, "detail": detail, "latency_ms": latency_ms}


def _sign(body: bytes, secret: str | None = None) -> str:
    key = secret or settings.N8N_WEBHOOK_SECRET
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, signature: str | None, secret: str | None = None) -> bool:
    if not signature:
        return False
    expected = hmac.new((secret or settings.N8N_WEBHOOK_SECRET).encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def publish_pending_events(org_id: uuid.UUID, limit: int = 50) -> dict[str, Any]:
    from app.db.session import session_scope

    published = 0
    failed = 0
    skipped = 0
    with session_scope() as db:
        events = db.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.org_id == org_id,
                DomainEvent.status == "PENDING",
                DomainEvent.attempts < 5,
            )
            .order_by(DomainEvent.created_at)
            .limit(limit)
        ).all()
        integrations = [
            integration
            for integration in list_integrations(db, org_id=org_id)
            if integration.is_enabled
            and integration.kind in {IntegrationKind.WEBHOOK, IntegrationKind.N8N}
        ]
        if not integrations:
            for event in events:
                event.status = "SKIPPED"
                event.published_at = utcnow()
                event.last_error = "No enabled webhook or n8n integration is subscribed to this event."
            return {"published": 0, "failed": 0, "skipped": len(events), "note": "no_integrations"}

        for event in events:
            targets = [
                integration
                for integration in integrations
                if not integration.event_filter or event.event_type in integration.event_filter
            ]
            if not targets:
                event.status = "SKIPPED"
                event.published_at = utcnow()
                skipped += 1
                continue
            event.attempts += 1
            payload = {
                "id": str(event.id),
                "event_type": event.event_type,
                "occurred_at": event.created_at.isoformat() if event.created_at else None,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "data": event.payload,
            }
            body = json.dumps(payload, default=str).encode()
            event_ok = False
            for integration in targets:
                url = str(
                    integration.config.get("webhook_url")
                    or integration.config.get("base_url")
                    or ""
                )
                if not url:
                    event.last_error = f"Integration '{integration.name}' has no webhook URL."
                    continue
                try:
                    _validate_http_url(url)
                except BadRequestError:
                    event.last_error = f"Integration '{integration.name}' has an invalid URL."
                    continue
                signature = _sign(body, get_credential(db, integration, "signing_secret"))
                response_status: int | None = None
                error: str | None = None
                try:
                    with httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
                        response = client.post(
                            url,
                            content=body,
                            headers={
                                "Content-Type": "application/json",
                                "X-Resolve-Event": event.event_type,
                                "X-Resolve-Signature": signature,
                                "X-Resolve-Event-Id": str(event.id),
                                "Idempotency-Key": str(event.id),
                            },
                        )
                    response_status = response.status_code
                    event_ok = event_ok or response.status_code < 400
                    if response.status_code >= 400:
                        error = f"HTTP {response.status_code}: {response.text[:300]}"
                except httpx.HTTPError as exc:
                    error = str(exc)[:400]
                db.add(
                    WebhookEvent(
                        org_id=org_id,
                        integration_id=integration.id,
                        direction=Direction.OUTBOUND,
                        event_type=event.event_type,
                        payload=payload,
                        signature_valid=True,
                        status=WebhookStatus.SENT if response_status and response_status < 400 else WebhookStatus.FAILED,
                        response_status=response_status,
                        attempts=1,
                        last_error=error,
                        idempotency_key=f"{event.id}:{integration.id}",
                    )
                )
                if integration.kind == IntegrationKind.N8N:
                    db.add(
                        WorkflowExecution(
                            org_id=org_id,
                            integration_id=integration.id,
                            workflow_key=str(integration.config.get("workflow_key", "n8n-webhook")),
                            trigger_type="EVENT",
                            case_id=uuid.UUID(event.entity_id)
                            if event.entity_type == "CASE" and event.entity_id
                            else None,
                            status=WorkflowStatus.COMPLETED if response_status and response_status < 400 else WorkflowStatus.FAILED,
                            payload=payload,
                            result={"status_code": response_status},
                            attempts=1,
                            error=error,
                            idempotency_key=str(event.id),
                            started_at=utcnow(),
                            finished_at=utcnow(),
                        )
                    )
                if error:
                    integration.status = IntegrationStatus.DEGRADED
                    integration.last_error = error
                    integration.last_checked_at = utcnow()
            if event_ok:
                event.status = "PUBLISHED"
                event.published_at = utcnow()
                event.last_error = None
                published += 1
            else:
                event.status = "PENDING" if event.attempts < 5 else "FAILED"
                failed += 1
    return {"published": published, "failed": failed, "skipped": skipped}


def event_matches_any(filters: list[str], events: list[DomainEvent]) -> bool:
    return any(not filters or event.event_type in filters for event in events)


def list_webhook_events(
    db: Session, *, org_id: uuid.UUID, direction: Direction | None = None, limit: int = 100
) -> list[WebhookEvent]:
    stmt = select(WebhookEvent).where(WebhookEvent.org_id == org_id)
    if direction:
        stmt = stmt.where(WebhookEvent.direction == direction)
    return list(db.scalars(stmt.order_by(WebhookEvent.created_at.desc()).limit(limit)))


def receive_webhook(
    db: Session,
    *,
    integration: Integration,
    body: bytes,
    signature: str | None,
    headers: dict[str, str],
) -> WebhookEvent:
    if not integration.is_enabled:
        raise BadRequestError("This integration is disabled.", code="integration_disabled")
    if len(body) > 1_000_000:
        raise BadRequestError("Webhook payload is too large.", code="webhook_payload_too_large")
    secret = get_credential(db, integration, "signing_secret")
    valid = verify_signature(body, signature, secret)
    if not valid:
        raise BadRequestError("Webhook signature is invalid.", code="invalid_webhook_signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequestError("Webhook payload must be valid JSON.", code="invalid_webhook_payload") from exc
    event_type = str(payload.get("event_type") or headers.get("x-resolve-event") or "unknown")
    idempotency_key = str(
        headers.get("idempotency-key")
        or headers.get("x-idempotency-key")
        or payload.get("id")
        or uuid.uuid4()
    )
    existing = db.scalar(
        select(WebhookEvent).where(
            WebhookEvent.org_id == integration.org_id,
            WebhookEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    event = WebhookEvent(
        org_id=integration.org_id,
        integration_id=integration.id,
        direction=Direction.INBOUND,
        event_type=event_type,
        payload=payload if isinstance(payload, dict) else {"value": payload},
        headers={key[:60]: value[:300] for key, value in headers.items()},
        signature_valid=True,
        status=WebhookStatus.RECEIVED,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()
    from app.services.deferred import queue_task_after_commit

    queue_task_after_commit(
        db, "process_webhook_event", {"webhook_event_id": str(event.id)}, integration.org_id
    )
    return event


def process_inbound_event(webhook_event_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope

    with session_scope() as db:
        event = db.get(WebhookEvent, webhook_event_id)
        if event is None or event.org_id != org_id:
            return {"status": "skipped", "reason": "event_not_found"}
        if event.status == WebhookStatus.PROCESSED:
            return {"status": "skipped", "reason": "already_processed"}
        payload = event.payload or {}
        try:
            if event.event_type in {"invoice.received", "invoice.created"}:
                from app.modules.exceptions.service import detect_for_invoice
                from app.modules.invoices.schemas import InvoiceCreate
                from app.modules.invoices.service import create_invoice, validate_invoice

                invoice_payload = payload.get("invoice") or payload.get("data") or {}
                if not isinstance(invoice_payload, dict):
                    raise IntegrationError("Invoice payload must be an object.", code="invalid_webhook_payload")
                model = InvoiceCreate.model_validate(invoice_payload)
                invoice = create_invoice(
                    db, org_id=org_id, actor_id=None, payload=model, status=None
                )
                validate_invoice(db, invoice=invoice, actor_id=None)
                detect_for_invoice(db, org_id=org_id, invoice=invoice, actor_id=None)
                event.status = WebhookStatus.PROCESSED
                event.processed_at = utcnow()
                event.last_error = None
                return {"status": "processed", "invoice_id": str(invoice.id)}
            if event.event_type == "integration.ping":
                event.status = WebhookStatus.PROCESSED
                event.processed_at = utcnow()
                return {"status": "processed", "pong": True}
            event.status = WebhookStatus.FAILED
            event.last_error = f"Unsupported inbound event type '{event.event_type}'"
            return {"status": "failed", "reason": event.last_error}
        except Exception as exc:  # noqa: BLE001
            logger.exception("inbound_webhook_processing_failed", event_id=str(event.id))
            event.status = WebhookStatus.FAILED
            event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            return {"status": "failed", "reason": event.last_error}


# ------------------------------------------------------------------------- workflows


def list_workflow_executions(
    db: Session, *, org_id: uuid.UUID, limit: int = 100, status: WorkflowStatus | None = None
) -> list[WorkflowExecution]:
    stmt = select(WorkflowExecution).where(WorkflowExecution.org_id == org_id)
    if status:
        stmt = stmt.where(WorkflowExecution.status == status)
    return list(
        db.scalars(stmt.order_by(WorkflowExecution.created_at.desc()).limit(limit))
    )


def trigger_workflow(
    db: Session,
    *,
    org_id: uuid.UUID,
    workflow_key: str,
    case_id: uuid.UUID | None,
    payload: dict[str, Any],
    actor_id: uuid.UUID | None,
) -> WorkflowExecution:
    template = get_template(workflow_key)
    executions = [
        integration
        for integration in list_integrations(db, org_id=org_id)
        if integration.kind == IntegrationKind.N8N and integration.is_enabled
    ]
    execution = WorkflowExecution(
        org_id=org_id,
        integration_id=executions[0].id if executions else None,
        workflow_key=template.key,
        trigger_type="MANUAL",
        case_id=case_id,
        status=WorkflowStatus.RUNNING,
        payload=payload,
        started_at=utcnow(),
        attempts=1,
    )
    db.add(execution)
    db.flush()
    if case_id:
        from app.modules.cases.service import get_case, log_activity

        case = get_case(db, org_id=org_id, case_id=case_id)
        log_activity(
            db,
            case=case,
            actor_id=actor_id,
            activity_type="WORKFLOW_TRIGGERED",
            summary=f"Workflow '{template.name}' triggered",
            payload={"execution_id": str(execution.id)},
        )
    if not executions:
        execution.status = WorkflowStatus.FAILED
        execution.error = (
            "No enabled n8n integration is configured. Add an n8n integration in the Integration Hub "
            "before triggering workflows."
        )
        execution.finished_at = utcnow()
        record_audit(
            db,
            org_id=org_id,
            action="workflow.failed",
            entity_type="workflow_execution",
            entity_id=execution.id,
            summary=f"Workflow '{template.name}' could not run: n8n not configured",
            actor_id=actor_id,
        )
        return execution
    integration = executions[0]
    url = str(integration.config.get("workflow_webhook_map", {}).get(template.key, "")) or str(
        integration.config.get("webhook_url", "")
    )
    if not url:
        execution.status = WorkflowStatus.FAILED
        execution.error = "The n8n integration has no webhook URL."
        execution.finished_at = utcnow()
        return execution
    body = json.dumps(
        {"workflow": template.key, "case_id": str(case_id) if case_id else None, "payload": payload},
        default=str,
    ).encode()
    try:
        with httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            response = client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Resolve-Workflow": template.key,
                    "X-Resolve-Signature": _sign(
                        body, get_credential(db, integration, "signing_secret")
                    ),
                },
            )
        execution.result = {"status_code": response.status_code, "body": response.text[:500]}
        execution.status = WorkflowStatus.COMPLETED if response.status_code < 400 else WorkflowStatus.FAILED
        execution.error = None if response.status_code < 400 else f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        execution.status = WorkflowStatus.FAILED
        execution.error = str(exc)[:1000]
    execution.finished_at = utcnow()
    record_audit(
        db,
        org_id=org_id,
        action="workflow.triggered",
        entity_type="workflow_execution",
        entity_id=execution.id,
        summary=f"Workflow '{template.name}' {execution.status.value.lower()}",
        actor_id=actor_id,
        after={"status": execution.status.value, "error": execution.error},
    )
    return execution


def retry_workflow(db: Session, *, execution: WorkflowExecution, actor_id: uuid.UUID | None) -> WorkflowExecution:
    if execution.status != WorkflowStatus.FAILED:
        raise BadRequestError("Only failed executions can be retried.", code="workflow_not_failed")
    return trigger_workflow(
        db,
        org_id=execution.org_id,
        workflow_key=execution.workflow_key,
        case_id=execution.case_id,
        payload=execution.payload or {},
        actor_id=actor_id,
    )


def list_background_jobs(
    db: Session, *, org_id: uuid.UUID, limit: int = 100, status: JobStatus | None = None
) -> list[BackgroundJob]:
    stmt = select(BackgroundJob).where(BackgroundJob.org_id == org_id)
    if status:
        stmt = stmt.where(BackgroundJob.status == status)
    return list(db.scalars(stmt.order_by(BackgroundJob.created_at.desc()).limit(limit)))


def job_failure_stats(db: Session, *, org_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(BackgroundJob.status, func.count())
        .where(BackgroundJob.org_id == org_id)
        .group_by(BackgroundJob.status)
    ).all()
    return {status.value: int(count) for status, count in rows}


def sync_all(org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope

    tested = 0
    failures = 0
    with session_scope() as db:
        integrations = [
            integration
            for integration in list_integrations(db, org_id=org_id)
            if integration.is_enabled and integration.kind not in {IntegrationKind.CSV, IntegrationKind.EXCEL}
        ]
        for integration in integrations:
            result = test_connection(db, org_id=org_id, integration_id=integration.id)
            tested += 1
            if not result["ok"]:
                failures += 1
    return {"tested": tested, "failures": failures}


__all__ = [
    "WORKFLOW_TEMPLATES",
    "credential_keys",
    "create_integration",
    "get_integration",
    "list_integrations",
    "list_webhook_events",
    "process_inbound_event",
    "publish_pending_events",
    "receive_webhook",
    "redact_config",
    "set_credentials",
    "test_connection",
    "trigger_workflow",
    "verify_signature",
    "timedelta",
    "EventType",
]
