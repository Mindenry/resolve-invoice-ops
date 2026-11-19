"""Member and profile endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, get_principal, require_permission
from app.domain.enums import RoleCode
from app.modules.users import service
from app.modules.users.schemas import (
    InviteMemberRequest,
    MemberOut,
    UpdateMemberRequest,
    UpdateProfileRequest,
    UserProfile,
)
from app.schemas.common import APIMessage

router = APIRouter(tags=["Users"])

MemberReader = Annotated[Principal, Depends(require_permission("user:read"))]
MemberManager = Annotated[Principal, Depends(require_permission("user:manage"))]


@router.get("/users/me", response_model=UserProfile, summary="Your profile")
def get_profile(principal: Annotated[Principal, Depends(get_principal)]) -> UserProfile:
    return UserProfile.model_validate(principal.user)


@router.patch("/users/me", response_model=UserProfile, summary="Update your profile")
def update_profile(
    payload: UpdateProfileRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> UserProfile:
    user = service.update_profile(
        db,
        user=principal.user,
        full_name=payload.full_name,
        job_title=payload.job_title,
        locale=payload.locale,
    )
    return UserProfile.model_validate(user)


@router.get("/users", response_model=Page[MemberOut], summary="List organization members")
def list_members(
    principal: MemberReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    search: str | None = Query(None, max_length=120),
    role: RoleCode | None = Query(None),
    active_only: bool = Query(False),
) -> Page[MemberOut]:
    items, total = service.list_members(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        search=search,
        role=role,
        active_only=active_only,
    )
    return Page.build(items, total, pagination)


@router.post("/users", response_model=MemberOut, status_code=201, summary="Invite a member")
def invite_member(
    payload: InviteMemberRequest,
    principal: MemberManager,
    db: Annotated[Session, Depends(get_db)],
) -> MemberOut:
    member, _invited = service.invite_member(
        db,
        org_id=principal.org_id,
        actor=principal.user,
        actor_role=principal.role,
        payload=payload,
    )
    return member


@router.patch("/users/{membership_id}", response_model=MemberOut, summary="Update a member")
def update_member(
    membership_id: uuid.UUID,
    payload: UpdateMemberRequest,
    principal: MemberManager,
    db: Annotated[Session, Depends(get_db)],
) -> MemberOut:
    return service.update_member(
        db,
        org_id=principal.org_id,
        actor=principal.user,
        actor_role=principal.role,
        membership_id=membership_id,
        payload=payload,
    )


@router.delete("/users/{membership_id}", response_model=APIMessage, summary="Deactivate a member")
def deactivate_member(
    membership_id: uuid.UUID,
    principal: MemberManager,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    service.update_member(
        db,
        org_id=principal.org_id,
        actor=principal.user,
        actor_role=principal.role,
        membership_id=membership_id,
        payload=UpdateMemberRequest(is_active=False),
    )
    return APIMessage(message="Member deactivated.")
