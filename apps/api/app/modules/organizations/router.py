"""Organization profile, RBAC catalog and settings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError
from app.core.pagination import Pagination
from app.db.session import get_db
from app.dependencies.auth import Principal, get_principal, require_permission
from app.models.identity import Permission, Role
from app.modules.auth.service import ensure_rbac, permissions_for_role
from app.modules.organizations.schemas import (
    OrganizationOut,
    OrganizationSettingsOut,
    OrganizationSettingsUpdate,
    OrganizationUpdate,
    PermissionOut,
    RoleOut,
    RolePermissionMatrix,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.get("/current", response_model=OrganizationOut, summary="Current organization")
def current_organization(principal: Annotated[Principal, Depends(get_principal)]) -> OrganizationOut:
    return OrganizationOut.model_validate(principal.organization)


@router.patch("/current", response_model=OrganizationOut, summary="Update organization profile")
def update_organization(
    payload: OrganizationUpdate,
    principal: Annotated[Principal, Depends(require_permission("org:update"))],
    db: Annotated[Session, Depends(get_db)],
) -> OrganizationOut:
    organization = principal.organization
    before = {"name": organization.name, "currency": organization.default_currency}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, field, value)
    record_audit(
        db,
        org_id=organization.id,
        action="organization.updated",
        entity_type="organization",
        entity_id=organization.id,
        summary="Organization profile updated",
        actor=principal.user,
        before=before,
        after={"name": organization.name, "currency": organization.default_currency},
    )
    db.commit()
    return OrganizationOut.model_validate(organization)


@router.get("/roles", response_model=list[RoleOut], summary="Roles available in the organization")
def list_roles(
    principal: Annotated[Principal, Depends(require_permission("role:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[RoleOut]:
    ensure_rbac(db)
    db.commit()
    return [RoleOut.model_validate(role) for role in db.scalars(select(Role).order_by(Role.rank.desc()))]


@router.get("/permissions", response_model=list[PermissionOut], summary="Permission catalog")
def list_permissions(
    principal: Annotated[Principal, Depends(require_permission("role:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[PermissionOut]:
    return [
        PermissionOut.model_validate(permission)
        for permission in db.scalars(select(Permission).order_by(Permission.group, Permission.code))
    ]


@router.get("/roles/matrix", response_model=RolePermissionMatrix, summary="Role/permission matrix")
def role_matrix(
    principal: Annotated[Principal, Depends(require_permission("role:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> RolePermissionMatrix:
    roles = list(db.scalars(select(Role).order_by(Role.rank.desc())))
    permissions = list(db.scalars(select(Permission).order_by(Permission.group, Permission.code)))
    return RolePermissionMatrix(
        roles=[RoleOut.model_validate(role) for role in roles],
        permissions=[PermissionOut.model_validate(permission) for permission in permissions],
        matrix={role.code: sorted(permissions_for_role(db, role.id)) for role in roles},
    )


@router.get("/settings", response_model=OrganizationSettingsOut, summary="Organization settings")
def get_settings(principal: Annotated[Principal, Depends(require_permission("org:read"))]) -> OrganizationSettingsOut:
    return OrganizationSettingsOut(
        settings=principal.organization.settings or {},
        branding=principal.organization.branding or {},
    )


@router.put("/settings", response_model=OrganizationSettingsOut, summary="Update organization settings")
def update_settings(
    payload: OrganizationSettingsUpdate,
    principal: Annotated[Principal, Depends(require_permission("org:update"))],
    db: Annotated[Session, Depends(get_db)],
) -> OrganizationSettingsOut:
    organization = principal.organization
    before = {"settings": dict(organization.settings or {}), "branding": dict(organization.branding or {})}
    if payload.settings is not None:
        merged = {**(organization.settings or {}), **payload.settings}
        approval = merged.get("approval_policy")
        if isinstance(approval, dict):
            risk = str(approval.get("approval_required_risk", "HIGH")).upper()
            if risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise BadRequestError("approval_policy.approval_required_risk is invalid.", code="invalid_setting")
        organization.settings = merged
    if payload.branding is not None:
        organization.branding = {**(organization.branding or {}), **payload.branding}
    record_audit(
        db,
        org_id=organization.id,
        action="organization.settings_updated",
        entity_type="organization",
        entity_id=organization.id,
        summary="Organization settings updated",
        actor=principal.user,
        before=before,
        after={"settings": organization.settings, "branding": organization.branding},
    )
    db.commit()
    return OrganizationSettingsOut(
        settings=organization.settings or {}, branding=organization.branding or {}
    )


@router.get("/ai-configuration", response_model=OrganizationSettingsOut, summary="AI configuration (read-only provider)")
def ai_configuration(
    principal: Annotated[Principal, Depends(require_permission("ai:configure"))],
) -> OrganizationSettingsOut:
    from app.ai.registry import provider_status

    status = provider_status()
    ai_settings = (principal.organization.settings or {}).get("ai", {})
    return OrganizationSettingsOut(
        settings={
            "provider": status.llm_provider,
            "model": status.llm_model,
            "configured": status.llm_configured,
            "embedding_provider": status.embedding_provider,
            "embedding_model": status.embedding_model,
            "embeddings_configured": status.embeddings_configured,
            "deterministic_stub": status.is_stub,
            "features": ai_settings,
            "managed_by": "environment",
        },
        branding={},
    )
@router.get("/members/assignable", summary="Members who can be assigned cases")
def assignable_members(
    principal: Annotated[Principal, Depends(require_permission("user:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, str]]:
    from app.modules.users import service

    members, _ = service.list_members(
        db,
        org_id=principal.org_id,
        pagination=Pagination(page=1, page_size=200),
        active_only=True,
    )
    return [
        {
            "id": str(member.user_id),
            "membership_id": str(member.id),
            "full_name": member.full_name,
            "email": member.email,
            "role": member.role_code.value,
        }
        for member in members
    ]

