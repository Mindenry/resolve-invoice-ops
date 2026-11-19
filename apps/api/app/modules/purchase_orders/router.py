"""Purchase order endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import PurchaseOrderStatus
from app.modules.purchase_orders import service
from app.modules.purchase_orders.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderDetail,
    PurchaseOrderOut,
    PurchaseOrderTransition,
    PurchaseOrderUpdate,
)
from app.schemas.common import APIMessage

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])

POReader = Annotated[Principal, Depends(require_permission("po:read"))]
POWriter = Annotated[Principal, Depends(require_permission("po:create"))]
POEditor = Annotated[Principal, Depends(require_permission("po:update"))]


@router.get("", response_model=Page[PurchaseOrderOut], summary="List purchase orders")
def list_purchase_orders(
    principal: POReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    search: str | None = Query(None, max_length=120),
    vendor_id: uuid.UUID | None = Query(None),
    status: PurchaseOrderStatus | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> Page[PurchaseOrderOut]:
    items, total = service.list_purchase_orders(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        search=search,
        vendor_id=vendor_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    db.commit()
    return Page.build(items, total, pagination)


@router.post("", response_model=PurchaseOrderDetail, status_code=201, summary="Create a purchase order")
def create_purchase_order(
    payload: PurchaseOrderCreate, principal: POWriter, db: Annotated[Session, Depends(get_db)]
) -> PurchaseOrderDetail:
    po = service.create_purchase_order(
        db, org_id=principal.org_id, actor_id=principal.user_id, payload=payload
    )
    db.commit()
    return service.detail(db, po)


@router.get("/summary", summary="Purchase order totals for the organization")
def purchase_order_summary(
    principal: POReader, db: Annotated[Session, Depends(get_db)]
) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.models.finance import PurchaseOrder

    rows = db.execute(
        select(PurchaseOrder.status, func.count())
        .where(PurchaseOrder.org_id == principal.org_id, PurchaseOrder.deleted_at.is_(None))
        .group_by(PurchaseOrder.status)
    ).all()
    return {status.value: count for status, count in rows}


@router.get("/{po_id}", response_model=PurchaseOrderDetail, summary="Purchase order detail")
def get_purchase_order(
    po_id: uuid.UUID, principal: POReader, db: Annotated[Session, Depends(get_db)]
) -> PurchaseOrderDetail:
    po = service.get_purchase_order(db, org_id=principal.org_id, po_id=po_id)
    return service.detail(db, po)


@router.patch("/{po_id}", response_model=PurchaseOrderDetail, summary="Update a purchase order")
def update_purchase_order(
    po_id: uuid.UUID,
    payload: PurchaseOrderUpdate,
    principal: POEditor,
    db: Annotated[Session, Depends(get_db)],
) -> PurchaseOrderDetail:
    po = service.get_purchase_order(db, org_id=principal.org_id, po_id=po_id)
    service.update_purchase_order(db, po=po, actor_id=principal.user_id, payload=payload)
    db.commit()
    return service.detail(db, po)


@router.post("/{po_id}/transition", response_model=PurchaseOrderDetail, summary="Change PO status")
def transition_purchase_order(
    po_id: uuid.UUID,
    payload: PurchaseOrderTransition,
    principal: POEditor,
    db: Annotated[Session, Depends(get_db)],
) -> PurchaseOrderDetail:
    po = service.get_purchase_order(db, org_id=principal.org_id, po_id=po_id)
    service.transition(db, po=po, status=payload.status, actor_id=principal.user_id, note=payload.note)
    db.commit()
    return service.detail(db, po)


@router.delete("/{po_id}", response_model=APIMessage, summary="Archive a draft purchase order")
def archive_purchase_order(
    po_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission("po:update"))],
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    po = service.get_purchase_order(db, org_id=principal.org_id, po_id=po_id)
    if po.status not in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.CANCELLED}:
        from app.core.errors import BadRequestError

        raise BadRequestError(
            "Only draft or cancelled purchase orders can be archived.", code="purchase_order_not_archivable"
        )
    from app.core.security import utcnow
    from app.services.audit import record_audit

    po.deleted_at = utcnow()
    record_audit(
        db,
        org_id=principal.org_id,
        action="purchase_order.archived",
        entity_type="purchase_order",
        entity_id=po.id,
        summary=f"Purchase order {po.po_number} archived",
        actor=principal.user,
    )
    db.commit()
    return APIMessage(message="Purchase order archived.")
