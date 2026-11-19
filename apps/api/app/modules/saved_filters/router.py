"""Saved filter endpoints for operator queues."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, NotFoundError
from app.db.session import get_db
from app.dependencies.auth import Principal, get_principal
from app.models.cases import SavedFilter
from app.schemas.common import APIMessage, ORMModel

router = APIRouter(prefix="/saved-filters", tags=["Saved Filters"])

FilterUser = Annotated[Principal, Depends(get_principal)]


class SavedFilterCreate(ORMModel):
    resource: str = Field(min_length=2, max_length=40, pattern=r"^[a-z_]+$")
    name: str = Field(min_length=1, max_length=80)
    query: dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False


class SavedFilterOut(ORMModel):
    id: uuid.UUID
    resource: str
    name: str
    query: dict[str, Any]
    is_shared: bool
    is_owner: bool


@router.get("", response_model=list[SavedFilterOut], summary="List saved filters")
def list_filters(
    principal: FilterUser,
    db: Annotated[Session, Depends(get_db)],
    resource: str | None = Query(None, max_length=40),
) -> list[SavedFilterOut]:
    stmt = select(SavedFilter).where(
        SavedFilter.org_id == principal.org_id,
        or_(SavedFilter.user_id == principal.user_id, SavedFilter.is_shared.is_(True)),
    )
    if resource:
        stmt = stmt.where(SavedFilter.resource == resource)
    rows = db.scalars(stmt.order_by(SavedFilter.name)).all()
    return [
        SavedFilterOut(
            id=row.id,
            resource=row.resource,
            name=row.name,
            query=row.query,
            is_shared=row.is_shared,
            is_owner=row.user_id == principal.user_id,
        )
        for row in rows
    ]


@router.post("", response_model=SavedFilterOut, status_code=201, summary="Save a filter")
def create_filter(
    payload: SavedFilterCreate,
    principal: FilterUser,
    db: Annotated[Session, Depends(get_db)],
) -> SavedFilterOut:
    from sqlalchemy.exc import IntegrityError

    from app.core.errors import ConflictError

    row = SavedFilter(
        org_id=principal.org_id,
        user_id=principal.user_id,
        resource=payload.resource,
        name=payload.name,
        query=payload.query,
        is_shared=payload.is_shared,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("A saved filter with this name already exists.", code="filter_name_taken") from exc
    db.commit()
    return SavedFilterOut(
        id=row.id,
        resource=row.resource,
        name=row.name,
        query=row.query,
        is_shared=row.is_shared,
        is_owner=True,
    )


@router.delete("/{filter_id}", response_model=APIMessage, summary="Delete a saved filter")
def delete_filter(
    filter_id: uuid.UUID,
    principal: FilterUser,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    row = db.scalar(
        select(SavedFilter).where(SavedFilter.id == filter_id, SavedFilter.org_id == principal.org_id)
    )
    if row is None:
        raise NotFoundError("Saved filter not found.", code="filter_not_found")
    if row.user_id != principal.user_id and not principal.is_superadmin:
        raise ForbiddenError("Only the owner can delete this saved filter.", code="filter_not_owned")
    db.delete(row)
    db.commit()
    return APIMessage(message="Saved filter deleted.")
