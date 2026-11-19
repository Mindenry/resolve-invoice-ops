"""Resolution proposal, catalogue, execution and cancellation endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import ResolutionStatus
from app.modules.cases.service import get_case
from app.modules.resolutions import service
from app.modules.resolutions.actions import action_catalog
from app.modules.resolutions.schemas import (
    ResolutionCancel,
    ResolutionCreate,
    ResolutionOut,
)

router = APIRouter(tags=["Resolutions"])

ResolutionReader = Annotated[Principal, Depends(require_permission("resolution:read"))]
ResolutionProposer = Annotated[Principal, Depends(require_permission("resolution:propose"))]
ResolutionExecutor = Annotated[Principal, Depends(require_permission("resolution:execute"))]


@router.get("/resolutions/actions", summary="Allow-listed resolution actions")
def list_actions(principal: ResolutionReader) -> list[dict[str, object]]:
    return action_catalog()


@router.get("/resolutions", response_model=Page[ResolutionOut], summary="List resolutions")
def list_resolutions(
    principal: ResolutionReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    case_id: uuid.UUID | None = Query(None),
    status: list[ResolutionStatus] | None = Query(None),
) -> Page[ResolutionOut]:
    rows, total = service.list_resolutions(
        db, org_id=principal.org_id, pagination=pagination, case_id=case_id, status=status
    )
    return Page.build([service.resolution_out(db, row) for row in rows], total, pagination)


@router.get("/resolutions/{resolution_id}", response_model=ResolutionOut, summary="Resolution detail")
def get_resolution(
    resolution_id: uuid.UUID, principal: ResolutionReader, db: Annotated[Session, Depends(get_db)]
) -> ResolutionOut:
    resolution = service.get_resolution(db, org_id=principal.org_id, resolution_id=resolution_id)
    return service.resolution_out(db, resolution)


@router.get("/cases/{case_id}/resolutions", response_model=list[ResolutionOut], summary="Resolutions for a case")
def case_resolutions(
    case_id: uuid.UUID, principal: ResolutionReader, db: Annotated[Session, Depends(get_db)]
) -> list[ResolutionOut]:
    case = get_case(db, org_id=principal.org_id, case_id=case_id)
    from sqlalchemy import select

    from app.models.ai import Resolution

    rows = db.scalars(
        select(Resolution)
        .where(Resolution.case_id == case.id, Resolution.org_id == principal.org_id)
        .order_by(Resolution.created_at.desc())
    ).all()
    return [service.resolution_out(db, row) for row in rows]


@router.post(
    "/cases/{case_id}/resolutions",
    response_model=ResolutionOut,
    status_code=201,
    summary="Propose a resolution action",
)
def propose_resolution(
    case_id: uuid.UUID,
    payload: ResolutionCreate,
    principal: ResolutionProposer,
    db: Annotated[Session, Depends(get_db)],
) -> ResolutionOut:
    case = get_case(db, org_id=principal.org_id, case_id=case_id)
    resolution = service.create_resolution(
        db,
        case=case,
        actor_id=principal.user_id,
        action_type=payload.action_type,
        description=payload.description,
        parameters=payload.parameters,
        evidence=payload.evidence,
        risk_level=payload.risk_level,
    )
    if payload.request_approval and resolution.requires_approval and resolution.status.value == "VALIDATED":
        service.request_approval(
            db,
            resolution=resolution,
            requester_id=principal.user_id,
            approver_role=payload.approver_role,
            assigned_approver_id=payload.approver_id,
            note=payload.note,
        )
    db.commit()
    return service.resolution_out(db, resolution)


@router.post("/resolutions/{resolution_id}/execute", response_model=ResolutionOut, summary="Execute a resolution")
def execute_resolution(
    resolution_id: uuid.UUID,
    principal: ResolutionExecutor,
    db: Annotated[Session, Depends(get_db)],
) -> ResolutionOut:
    resolution = service.get_resolution(db, org_id=principal.org_id, resolution_id=resolution_id)
    resolution = service.execute_resolution(
        db, resolution=resolution, actor_id=principal.user_id, permissions=set(principal.permissions)
    )
    db.commit()
    return service.resolution_out(db, resolution)


@router.post("/resolutions/{resolution_id}/retry", response_model=ResolutionOut, summary="Retry a failed resolution")
def retry_resolution(
    resolution_id: uuid.UUID,
    principal: ResolutionExecutor,
    db: Annotated[Session, Depends(get_db)],
) -> ResolutionOut:
    resolution = service.get_resolution(db, org_id=principal.org_id, resolution_id=resolution_id)
    resolution = service.retry_execution(
        db, resolution=resolution, actor_id=principal.user_id, permissions=set(principal.permissions)
    )
    db.commit()
    return service.resolution_out(db, resolution)


@router.post("/resolutions/{resolution_id}/cancel", response_model=ResolutionOut, summary="Cancel a resolution")
def cancel_resolution(
    resolution_id: uuid.UUID,
    payload: ResolutionCancel,
    principal: ResolutionProposer,
    db: Annotated[Session, Depends(get_db)],
) -> ResolutionOut:
    resolution = service.get_resolution(db, org_id=principal.org_id, resolution_id=resolution_id)
    resolution = service.cancel_resolution(
        db, resolution=resolution, actor_id=principal.user_id, reason=payload.reason
    )
    db.commit()
    return service.resolution_out(db, resolution)
