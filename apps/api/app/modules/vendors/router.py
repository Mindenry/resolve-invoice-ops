"""Vendor endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import VendorStatus
from app.modules.vendors import service
from app.modules.vendors.schemas import (
    VendorCreate,
    VendorDetail,
    VendorDuplicateGroup,
    VendorMergeRequest,
    VendorOut,
    VendorUpdate,
)
from app.schemas.common import APIMessage

router = APIRouter(prefix="/vendors", tags=["Vendors"])

VendorReader = Annotated[Principal, Depends(require_permission("vendor:read"))]
VendorCreator = Annotated[Principal, Depends(require_permission("vendor:create"))]
VendorEditor = Annotated[Principal, Depends(require_permission("vendor:update"))]
VendorMerger = Annotated[Principal, Depends(require_permission("vendor:merge"))]


@router.get("", response_model=Page[VendorOut], summary="List vendors")
def list_vendors(
    principal: VendorReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    search: str | None = Query(None, max_length=160),
    status: VendorStatus | None = Query(None),
    risk_flag: str | None = Query(None, max_length=60),
) -> Page[VendorOut]:
    items, total = service.list_vendors(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        search=search,
        status=status,
        risk_flag=risk_flag,
    )
    return Page.build(items, total, pagination)


@router.get("/duplicates", response_model=list[VendorDuplicateGroup], summary="Deterministic duplicate vendor candidates")
def duplicate_vendors(
    principal: VendorReader, db: Annotated[Session, Depends(get_db)]
) -> list[VendorDuplicateGroup]:
    return service.find_duplicates(db, org_id=principal.org_id)


@router.post("", response_model=VendorOut, status_code=201, summary="Create a vendor")
def create_vendor(
    payload: VendorCreate, principal: VendorCreator, db: Annotated[Session, Depends(get_db)]
) -> VendorOut:
    vendor = service.create_vendor(
        db, org_id=principal.org_id, actor_id=principal.user_id, payload=payload
    )
    db.commit()
    return vendor


@router.get("/{vendor_id}", response_model=VendorDetail, summary="Vendor profile")
def get_vendor(
    vendor_id: uuid.UUID, principal: VendorReader, db: Annotated[Session, Depends(get_db)]
) -> VendorDetail:
    return service.detail(db, org_id=principal.org_id, vendor_id=vendor_id)


@router.patch("/{vendor_id}", response_model=VendorOut, summary="Update a vendor")
def update_vendor(
    vendor_id: uuid.UUID,
    payload: VendorUpdate,
    principal: VendorEditor,
    db: Annotated[Session, Depends(get_db)],
) -> VendorOut:
    vendor = service.get_vendor(db, org_id=principal.org_id, vendor_id=vendor_id)
    result = service.update_vendor(db, vendor=vendor, actor_id=principal.user_id, payload=payload)
    db.commit()
    return result


@router.delete("/{vendor_id}", response_model=APIMessage, summary="Archive a vendor")
def archive_vendor(
    vendor_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission("vendor:delete"))],
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    vendor = service.get_vendor(db, org_id=principal.org_id, vendor_id=vendor_id)
    service.archive_vendor(db, vendor=vendor, actor_id=principal.user_id)
    db.commit()
    return APIMessage(message="Vendor archived.")


@router.post("/{vendor_id}/merge", response_model=VendorOut, summary="Merge a duplicate vendor")
def merge_vendor(
    vendor_id: uuid.UUID,
    payload: VendorMergeRequest,
    principal: VendorMerger,
    db: Annotated[Session, Depends(get_db)],
) -> VendorOut:
    result = service.merge_vendors(
        db,
        org_id=principal.org_id,
        target_id=vendor_id,
        source_id=payload.source_vendor_id,
        actor_id=principal.user_id,
        note=payload.note,
    )
    db.commit()
    return result
