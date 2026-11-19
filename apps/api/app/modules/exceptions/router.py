"""Exception queue, detection and rule configuration endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import ExceptionStatus, ExceptionType, Severity
from app.modules.cases.service import get_case
from app.modules.exceptions import service
from app.modules.exceptions.schemas import (
    DetectionRequest,
    DetectionResult,
    ExceptionDetail,
    ExceptionOut,
    ExceptionStatusUpdate,
    ExceptionSummary,
    RuleDetail,
    RuleOut,
    RuleUpdate,
)
from app.schemas.common import APIMessage

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])

ExceptionReader = Annotated[Principal, Depends(require_permission("exception:read"))]
ExceptionTriage = Annotated[Principal, Depends(require_permission("exception:triage"))]
RuleAdmin = Annotated[Principal, Depends(require_permission("org:update"))]


@router.get("", response_model=Page[ExceptionOut], summary="List exceptions")
def list_exceptions(
    principal: ExceptionReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    search: str | None = Query(None, max_length=160),
    exception_type: list[ExceptionType] | None = Query(None),
    severity: list[Severity] | None = Query(None),
    status: list[ExceptionStatus] | None = Query(None),
    entity_type: str | None = Query(None, max_length=40),
    entity_id: uuid.UUID | None = Query(None),
    case_id: uuid.UUID | None = Query(None),
    unassigned: bool | None = Query(None),
) -> Page[ExceptionOut]:
    items, total = service.list_exceptions(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        search=search,
        exception_type=exception_type,
        severity=severity,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        case_id=case_id,
        unassigned=unassigned,
    )
    return Page.build(items, total, pagination)


@router.get("/summary", response_model=ExceptionSummary, summary="Exception distribution summary")
def exception_summary(
    principal: ExceptionReader, db: Annotated[Session, Depends(get_db)]
) -> ExceptionSummary:
    return service.summary(db, org_id=principal.org_id)


@router.get("/rules", response_model=list[RuleOut], summary="List exception rules")
def list_rules(principal: ExceptionReader, db: Annotated[Session, Depends(get_db)]) -> list[RuleOut]:
    result = service.list_rules(db, org_id=principal.org_id)
    db.commit()
    return result


@router.get("/rules/{code}", response_model=RuleDetail, summary="Rule detail and version history")
def get_rule(code: str, principal: ExceptionReader, db: Annotated[Session, Depends(get_db)]) -> RuleDetail:
    detail = service.get_rule(db, org_id=principal.org_id, code=code)
    db.commit()
    return detail


@router.patch("/rules/{code}", response_model=RuleDetail, summary="Update a rule (creates a new version)")
def update_rule(
    code: str,
    payload: RuleUpdate,
    principal: RuleAdmin,
    db: Annotated[Session, Depends(get_db)],
) -> RuleDetail:
    detail = service.update_rule(
        db, org_id=principal.org_id, code=code, actor_id=principal.user_id, payload=payload
    )
    db.commit()
    return detail


@router.post("/scan", response_model=DetectionResult, summary="Run the detection engine")
def scan(
    payload: DetectionRequest,
    principal: ExceptionTriage,
    db: Annotated[Session, Depends(get_db)],
) -> DetectionResult:
    result = service.run_detection(
        db,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        invoice_id=payload.invoice_id,
        include_invoices=payload.include_invoices,
        include_vendors=payload.include_vendors,
        include_integrations=payload.include_integrations,
        create_cases=payload.create_cases,
        limit=payload.limit,
    )
    db.commit()
    return result


@router.get("/{exception_id}", response_model=ExceptionDetail, summary="Exception detail")
def get_exception(
    exception_id: uuid.UUID, principal: ExceptionReader, db: Annotated[Session, Depends(get_db)]
) -> ExceptionDetail:
    record = service.get_exception(db, org_id=principal.org_id, exception_id=exception_id)
    return service.detail(db, record)


@router.post("/{exception_id}/status", response_model=ExceptionDetail, summary="Triage an exception")
def update_status(
    exception_id: uuid.UUID,
    payload: ExceptionStatusUpdate,
    principal: ExceptionTriage,
    db: Annotated[Session, Depends(get_db)],
) -> ExceptionDetail:
    record = service.get_exception(db, org_id=principal.org_id, exception_id=exception_id)
    service.update_status(
        db, record=record, status=payload.status, actor_id=principal.user_id, note=payload.note
    )
    db.commit()
    return service.detail(db, record)


@router.post("/{exception_id}/attach", response_model=APIMessage, summary="Attach an exception to a case")
def attach_to_case(
    exception_id: uuid.UUID,
    case_id: uuid.UUID,
    principal: ExceptionTriage,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    record = service.get_exception(db, org_id=principal.org_id, exception_id=exception_id)
    case = get_case(db, org_id=principal.org_id, case_id=case_id)
    if case.status.value in {"CLOSED", "CANCELLED"}:
        raise NotFoundError("Case is closed and cannot accept exceptions.", code="case_closed")
    service.attach_to_case(db, record=record, case=case, actor_id=principal.user_id)
    db.commit()
    return APIMessage(message=f"Exception attached to {case.case_number}.")
