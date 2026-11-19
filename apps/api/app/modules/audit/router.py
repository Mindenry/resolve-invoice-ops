"""Audit trail queries. Audit rows are append-only and exposed read-only."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.models.audit import AuditLog
from app.models.identity import User
from app.schemas.common import ORMModel
from app.services.audit import record_audit

router = APIRouter(prefix="/audit", tags=["Audit"])


class AuditOut(ORMModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    summary: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    context: dict[str, Any] = {}
    ip_address: str | None = None
    request_id: str | None = None
    created_at: datetime


@router.get("", response_model=Page[AuditOut], summary="Search the audit trail")
def list_audit(
    principal: Annotated[Principal, Depends(require_permission("audit:read"))],
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    action: str | None = Query(None, max_length=80),
    entity_type: str | None = Query(None, max_length=60),
    entity_id: str | None = Query(None, max_length=64),
    actor_user_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None, max_length=160),
) -> Page[AuditOut]:
    stmt = select(AuditLog).where(AuditLog.org_id == principal.org_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(func.lower(AuditLog.summary).like(pattern), func.lower(AuditLog.action).like(pattern))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return Page.build([AuditOut.model_validate(row) for row in rows], total, pagination)


@router.get("/actions", response_model=list[dict[str, Any]], summary="Distinct audit actions")
def audit_actions(
    principal: Annotated[Principal, Depends(require_permission("audit:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(AuditLog.action, func.count())
        .where(AuditLog.org_id == principal.org_id)
        .group_by(AuditLog.action)
        .order_by(AuditLog.action)
    ).all()
    return [{"action": action, "count": int(count)} for action, count in rows]


@router.get("/export", summary="Export audit records as CSV")
def export_audit(
    principal: Annotated[Principal, Depends(require_permission("audit:read"))],
    db: Annotated[Session, Depends(get_db)],
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    action: str | None = Query(None, max_length=80),
) -> Response:
    stmt = select(AuditLog).where(AuditLog.org_id == principal.org_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(10_000)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["created_at", "actor", "action", "entity_type", "entity_id", "summary", "request_id"])
    for row in rows:
        writer.writerow(
            [
                row.created_at.isoformat() if row.created_at else "",
                row.actor_email or "",
                row.action,
                row.entity_type,
                row.entity_id or "",
                row.summary,
                row.request_id or "",
            ]
        )
    record_audit(
        db,
        org_id=principal.org_id,
        action="audit.exported",
        entity_type="audit_log",
        summary=f"Audit export generated ({len(rows)} rows)",
        actor=principal.user,
    )
    db.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="resolve-audit.csv"'},
    )


@router.get("/{log_id}", response_model=AuditOut, summary="Audit record detail")
def get_audit(
    log_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission("audit:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> AuditOut:
    row = db.scalar(
        select(AuditLog).where(AuditLog.id == log_id, AuditLog.org_id == principal.org_id)
    )
    if row is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Audit record not found.", code="audit_not_found")
    return AuditOut.model_validate(row)


# Keeps the actor join available for future actor filters without changing the API shape.
_ = User
