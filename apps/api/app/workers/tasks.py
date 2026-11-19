"""Background task handlers.

Every handler is idempotent at the domain level: jobs may be retried by Celery, by the
local runner, or manually from the UI after an operator inspects the failure.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logging import get_logger
from app.workers.registry import register_task

logger = get_logger(__name__)


@register_task("process_document", description="Parse, OCR, extract and index a document", timeout_seconds=900)
def process_document(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.documents.service import process_document_job

    return process_document_job(uuid.UUID(payload["document_id"]), org_id)


@register_task("index_document", description="Build knowledge chunks and embeddings", timeout_seconds=600)
def index_document(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.models.documents import Document
    from app.modules.documents.service import index_document as _index

    with session_scope() as db:
        document = db.get(Document, uuid.UUID(payload["document_id"]))
        if document is None or document.org_id != org_id:
            return {"status": "skipped", "reason": "document_not_found"}
        result = _index(db, document=document)
        db.flush()
        return result


@register_task("deliver_pending_notifications", description="Send queued notification emails")
def deliver_pending_notifications(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.services.notifications import deliver_email, deliver_pending_emails

    with session_scope() as db:
        if payload.get("notification_id"):
            result = deliver_email(db, uuid.UUID(payload["notification_id"]))
            db.flush()
            return result
        delivered = deliver_pending_emails(db, org_id=org_id)
        db.flush()
        return {"delivered": delivered}


@register_task("publish_domain_events", description="Fan out the transactional outbox to webhooks")
def publish_domain_events(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.integrations.service import publish_pending_events

    return publish_pending_events(org_id=org_id, limit=int(payload.get("limit", 50)))


@register_task("process_webhook_event", description="Process an inbound webhook event")
def process_webhook_event(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.integrations.service import process_inbound_event

    return process_inbound_event(uuid.UUID(payload["webhook_event_id"]), org_id)


@register_task("expire_approvals", description="Expire stale approval requests")
def expire_approvals(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.approvals.service import expire_overdue

    return expire_overdue(org_id)

@register_task("run_investigation", description="Run an AI investigation with evidence validation", timeout_seconds=300)
def run_investigation(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.investigation.service import run_investigation_job

    return run_investigation_job(uuid.UUID(payload["investigation_id"]), org_id)


@register_task("execute_resolution", description="Execute an approved resolution action")
def execute_resolution(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.resolutions.service import execute_resolution_job

    return execute_resolution_job(uuid.UUID(payload["resolution_id"]), org_id)


@register_task("run_evaluation", description="Run an AI evaluation over a dataset", timeout_seconds=1800)
def run_evaluation(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.ai_evaluation.service import run_evaluation_job

    return run_evaluation_job(uuid.UUID(payload["run_id"]), org_id)


@register_task("sync_integrations", description="Refresh integration health and scheduled syncs")
def sync_integrations(payload: dict[str, Any], org_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.integrations.service import sync_all

    return sync_all(org_id)
