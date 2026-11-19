"""Integration Hub, webhooks, workflow executions and job monitoring."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.errors import UnauthorizedError
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import Direction, JobStatus, WorkflowStatus
from app.modules.integrations import service
from app.modules.integrations.schemas import (
    BackgroundJobOut,
    ConnectionTestOut,
    CredentialsUpdate,
    IntegrationCreate,
    IntegrationOut,
    IntegrationUpdate,
    TriggerWorkflowRequest,
    WebhookAck,
    WebhookEventOut,
    WorkflowExecutionOut,
    WorkflowTemplateOut,
)
from app.modules.integrations.workflows import WORKFLOW_TEMPLATES
from app.schemas.common import APIMessage

router = APIRouter(tags=["Automation"])

IntegrationReader = Annotated[Principal, Depends(require_permission("integration:read"))]
IntegrationManager = Annotated[Principal, Depends(require_permission("integration:manage"))]
WorkflowRunner = Annotated[Principal, Depends(require_permission("workflow:run"))]


def _integration_out(db: Session, integration) -> IntegrationOut:  # type: ignore[no-untyped-def]
    return IntegrationOut(
        id=integration.id,
        name=integration.name,
        kind=integration.kind,
        status=integration.status,
        is_enabled=integration.is_enabled,
        config=service.redact_config(integration.config or {}),
        event_filter=integration.event_filter or [],
        credential_keys=service.credential_keys(db, integration),
        last_checked_at=integration.last_checked_at,
        last_success_at=integration.last_success_at,
        last_error=integration.last_error,
        created_at=integration.created_at,
    )


@router.get("/integrations", response_model=list[IntegrationOut], summary="List integrations")
def list_integrations(principal: IntegrationReader, db: Annotated[Session, Depends(get_db)]) -> list[IntegrationOut]:
    return [
        _integration_out(db, integration)
        for integration in service.list_integrations(db, org_id=principal.org_id)
    ]


@router.post("/integrations", response_model=IntegrationOut, status_code=201, summary="Create an integration")
def create_integration(
    payload: IntegrationCreate,
    principal: IntegrationManager,
    db: Annotated[Session, Depends(get_db)],
) -> IntegrationOut:
    integration = service.create_integration(
        db,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        name=payload.name,
        kind=payload.kind,
        config=payload.config,
        event_filter=payload.event_filter,
        is_enabled=payload.is_enabled,
        credentials=payload.credentials,
    )
    db.commit()
    return _integration_out(db, integration)


@router.get("/integrations/events", response_model=list[WebhookEventOut], summary="Webhook event log")
def list_webhook_events(
    principal: IntegrationReader,
    db: Annotated[Session, Depends(get_db)],
    direction: Direction | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[WebhookEventOut]:
    return [
        WebhookEventOut.model_validate(event)
        for event in service.list_webhook_events(
            db, org_id=principal.org_id, direction=direction, limit=limit
        )
    ]


@router.get("/integrations/{integration_id}", response_model=IntegrationOut, summary="Integration detail")
def get_integration(
    integration_id: uuid.UUID, principal: IntegrationReader, db: Annotated[Session, Depends(get_db)]
) -> IntegrationOut:
    integration = service.get_integration(db, org_id=principal.org_id, integration_id=integration_id)
    return _integration_out(db, integration)


@router.patch("/integrations/{integration_id}", response_model=IntegrationOut, summary="Update an integration")
def update_integration(
    integration_id: uuid.UUID,
    payload: IntegrationUpdate,
    principal: IntegrationManager,
    db: Annotated[Session, Depends(get_db)],
) -> IntegrationOut:
    integration = service.get_integration(db, org_id=principal.org_id, integration_id=integration_id)
    service.update_integration(
        db, integration=integration, actor_id=principal.user_id, changes=payload.model_dump(exclude_unset=True)
    )
    db.commit()
    return _integration_out(db, integration)


@router.delete("/integrations/{integration_id}", response_model=APIMessage, summary="Disable an integration")
def disable_integration(
    integration_id: uuid.UUID,
    principal: IntegrationManager,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    integration = service.get_integration(db, org_id=principal.org_id, integration_id=integration_id)
    service.update_integration(
        db, integration=integration, actor_id=principal.user_id, changes={"is_enabled": False}
    )
    db.commit()
    return APIMessage(message="Integration disabled.")


@router.post(
    "/integrations/{integration_id}/test", response_model=ConnectionTestOut, summary="Test connection"
)
def test_connection(
    integration_id: uuid.UUID,
    principal: IntegrationManager,
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionTestOut:
    result = service.test_connection(db, org_id=principal.org_id, integration_id=integration_id)
    db.commit()
    return ConnectionTestOut(**result)


@router.put(
    "/integrations/{integration_id}/credentials",
    response_model=APIMessage,
    summary="Store integration credentials (encrypted)",
)
def set_credentials(
    integration_id: uuid.UUID,
    payload: CredentialsUpdate,
    principal: IntegrationManager,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    integration = service.get_integration(db, org_id=principal.org_id, integration_id=integration_id)
    count = service.set_credentials(
        db, integration=integration, actor_id=principal.user_id, credentials=payload.credentials
    )
    db.commit()
    return APIMessage(message=f"{count} credential(s) stored.")


@router.get("/workflows/templates", response_model=list[WorkflowTemplateOut], summary="Automation templates")
def workflow_templates(principal: WorkflowRunner) -> list[WorkflowTemplateOut]:
    return [
        WorkflowTemplateOut(
            key=template.key,
            name=template.name,
            description=template.description,
            trigger_event=template.trigger_event,
            file_name=template.file_name,
            required_parameters=list(template.required_parameters),
        )
        for template in WORKFLOW_TEMPLATES
    ]


@router.get("/workflows/executions", response_model=list[WorkflowExecutionOut], summary="Workflow executions")
def workflow_executions(
    principal: Annotated[Principal, Depends(require_permission("workflow:read"))],
    db: Annotated[Session, Depends(get_db)],
    status_filter: WorkflowStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[WorkflowExecutionOut]:
    return [
        WorkflowExecutionOut.model_validate(execution)
        for execution in service.list_workflow_executions(
            db, org_id=principal.org_id, status=status_filter, limit=limit
        )
    ]


@router.post(
    "/workflows/{workflow_key}/trigger",
    response_model=WorkflowExecutionOut,
    summary="Trigger an n8n workflow",
)
def trigger_workflow(
    workflow_key: str,
    payload: TriggerWorkflowRequest,
    principal: WorkflowRunner,
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowExecutionOut:
    execution = service.trigger_workflow(
        db,
        org_id=principal.org_id,
        workflow_key=workflow_key,
        case_id=payload.case_id,
        payload=payload.payload,
        actor_id=principal.user_id,
    )
    db.commit()
    return WorkflowExecutionOut.model_validate(execution)


@router.post(
    "/workflows/executions/{execution_id}/retry",
    response_model=WorkflowExecutionOut,
    summary="Retry a failed workflow",
)
def retry_workflow(
    execution_id: uuid.UUID,
    principal: WorkflowRunner,
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowExecutionOut:
    from app.core.errors import NotFoundError
    from app.models.automation import WorkflowExecution

    execution = db.get(WorkflowExecution, execution_id)
    if execution is None or execution.org_id != principal.org_id:
        raise NotFoundError("Workflow execution not found.", code="execution_not_found")
    new_execution = service.retry_workflow(db, execution=execution, actor_id=principal.user_id)
    db.commit()
    return WorkflowExecutionOut.model_validate(new_execution)


@router.get("/jobs", response_model=list[BackgroundJobOut], summary="Background jobs")
def list_jobs(
    principal: Annotated[Principal, Depends(require_permission("workflow:read"))],
    db: Annotated[Session, Depends(get_db)],
    status_filter: JobStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[BackgroundJobOut]:
    return [
        BackgroundJobOut.model_validate(job)
        for job in service.list_background_jobs(
            db, org_id=principal.org_id, status=status_filter, limit=limit
        )
    ]


@router.post("/jobs/{job_id}/retry", response_model=APIMessage, summary="Retry a failed background job")
def retry_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission("workflow:run"))],
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    from app.core.errors import BadRequestError, NotFoundError
    from app.models.automation import BackgroundJob
    from app.workers.dispatch import retry_job as _retry

    job = db.get(BackgroundJob, job_id)
    if job is None or job.org_id != principal.org_id:
        raise NotFoundError("Background job not found.", code="job_not_found")
    try:
        _retry(job.id, job.org_id)
    except ValueError as exc:
        raise BadRequestError(str(exc), code="job_not_retryable") from exc
    return APIMessage(message="Job queued for retry.")


@router.post(
    "/webhooks/{integration_id}",
    response_model=WebhookAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Inbound webhook receiver (HMAC signed)",
)
@limiter.limit("120/minute")
async def receive_webhook(
    request: Request,
    integration_id: uuid.UUID,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    x_resolve_signature: Annotated[str | None, Header(alias="X-Resolve-Signature")] = None,
) -> WebhookAck:
    body = await request.body()
    if not body:
        raise UnauthorizedError("Webhook body is required.", code="empty_webhook_body")
    from app.core.errors import NotFoundError
    from app.models.automation import Integration

    integration = db.get(Integration, integration_id)
    if integration is None:
        raise NotFoundError("Integration not found.", code="integration_not_found")
    event = service.receive_webhook(
        db,
        integration=integration,
        body=body,
        signature=x_resolve_signature,
        headers=dict(request.headers),
    )
    db.commit()
    return WebhookAck(id=event.id, status=event.status.value)
