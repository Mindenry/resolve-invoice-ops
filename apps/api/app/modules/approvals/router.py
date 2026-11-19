"""Approval center endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import ApprovalStatus, RiskLevel
from app.modules.approvals import service
from app.modules.approvals.schemas import (
    ApprovalDecisionOut,
    ApprovalDecisionRequest,
    ApprovalDetail,
    ApprovalOut,
    ApprovalStats,
)
from app.modules.cases.service import get_case
from app.modules.resolutions.schemas import ApprovalCreateRequest

router = APIRouter(prefix="/approvals", tags=["Approvals"])

ApprovalReader = Annotated[Principal, Depends(require_permission("approval:read"))]
ApprovalDecider = Annotated[Principal, Depends(require_permission("approval:decide"))]
ApprovalRequester = Annotated[Principal, Depends(require_permission("resolution:propose"))]


@router.get("/stats", response_model=ApprovalStats, summary="Approval workload statistics")
def approval_stats(principal: ApprovalReader, db: Annotated[Session, Depends(get_db)]) -> ApprovalStats:
    return service.stats(db, org_id=principal.org_id)


@router.get("", response_model=Page[ApprovalOut], summary="List approval requests")
def list_approvals(
    principal: ApprovalReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    status: list[ApprovalStatus] | None = Query(None),
    risk: RiskLevel | None = Query(None),
    mine: bool = Query(False),
) -> Page[ApprovalOut]:
    items, total = service.list_approvals(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        status=status,
        risk=risk,
        mine=mine,
        viewer_id=principal.user_id,
        viewer_permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
    )
    return Page.build(items, total, pagination)


@router.get("/{approval_id}", response_model=ApprovalDetail, summary="Approval detail")
def get_approval(
    approval_id: uuid.UUID, principal: ApprovalReader, db: Annotated[Session, Depends(get_db)]
) -> ApprovalDetail:
    approval = service.get_approval(db, org_id=principal.org_id, approval_id=approval_id)
    return service.detail(
        db,
        approval=approval,
        viewer_id=principal.user_id,
        viewer_permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
    )


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionOut, summary="Approve a request")
def approve(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    principal: ApprovalDecider,
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalDecisionOut:
    approval = service.get_approval(db, org_id=principal.org_id, approval_id=approval_id)
    approval, execution_error = service.decide(
        db,
        approval=approval,
        actor=principal.user,
        permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
        approve=True,
        comment=payload.comment,
        execute_after_approval=payload.execute_after_approval,
    )
    db.commit()
    detail = service.detail(
        db,
        approval=approval,
        viewer_id=principal.user_id,
        viewer_permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
    )
    return ApprovalDecisionOut(
        approval=detail, resolution_status=detail.resolution_status, execution_error=execution_error
    )


@router.post("/{approval_id}/reject", response_model=ApprovalDecisionOut, summary="Reject a request")
def reject(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    principal: ApprovalDecider,
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalDecisionOut:
    approval = service.get_approval(db, org_id=principal.org_id, approval_id=approval_id)
    approval, _ = service.decide(
        db,
        approval=approval,
        actor=principal.user,
        permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
        approve=False,
        comment=payload.comment,
    )
    db.commit()
    detail = service.detail(
        db,
        approval=approval,
        viewer_id=principal.user_id,
        viewer_permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
    )
    return ApprovalDecisionOut(approval=detail, resolution_status=detail.resolution_status)


@router.post("/cases/{case_id}/request", response_model=ApprovalOut, status_code=201, summary="Request a manual approval")
def request_manual_approval(
    case_id: uuid.UUID,
    payload: ApprovalCreateRequest,
    principal: ApprovalRequester,
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalOut:
    case = get_case(db, org_id=principal.org_id, case_id=case_id)
    approval = service.create_manual_request(db, case=case, actor_id=principal.user_id, payload=payload)
    db.commit()
    return service._approval_out(
        db,
        approval,
        viewer_id=principal.user_id,
        viewer_permissions=set(principal.permissions),
        is_superadmin=principal.is_superadmin,
    )
