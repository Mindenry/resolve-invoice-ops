"""Request authentication and permission enforcement."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import bind_identity
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.permissions import ALL_PERMISSIONS
from app.core.security import decode_access_token
from app.db.session import get_db
from app.domain.enums import RoleCode
from app.models.identity import Membership, Organization, Role, User
from app.modules.auth.service import permissions_for_role

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


@dataclass(slots=True, frozen=True)
class Principal:
    user: User
    organization: Organization
    membership: Membership | None
    role: RoleCode
    permissions: frozenset[str]
    is_superadmin: bool

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication credentials were not provided.", code="missing_token")
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("Access token subject is invalid.", code="invalid_token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise UnauthorizedError("Account is inactive or no longer exists.", code="account_inactive")
    request.state.token_payload = payload
    return user


def _resolve_org(
    db: Session,
    user: User,
    payload_org: str | None,
    header_org: str | None,
    header_slug: str | None,
) -> tuple[Organization, Membership | None]:
    organization: Organization | None = None
    if header_slug:
        organization = db.scalar(
            select(Organization).where(
                Organization.slug == header_slug.lower(), Organization.deleted_at.is_(None)
            )
        )
        if organization is None:
            raise ForbiddenError("Organization not found.", code="organization_not_found")
    elif header_org or payload_org:
        raw = header_org or payload_org
        try:
            org_id = uuid.UUID(str(raw))
        except ValueError as exc:
            raise ForbiddenError("Organization identifier is invalid.", code="organization_invalid") from exc
        organization = db.get(Organization, org_id)
        if organization is None or organization.deleted_at is not None:
            raise ForbiddenError("Organization not found.", code="organization_not_found")
    else:
        membership = db.scalar(
            select(Membership)
            .join(Organization, Organization.id == Membership.org_id)
            .where(
                Membership.user_id == user.id,
                Membership.is_active.is_(True),
                Organization.deleted_at.is_(None),
            )
            .order_by(Membership.created_at)
        )
        if membership is None:
            raise ForbiddenError(
                "Select an organization with the X-Organization-Id header.", code="organization_required"
            )
        organization = db.get(Organization, membership.org_id)
        if organization is None:
            raise ForbiddenError("Organization not found.", code="organization_not_found")

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.org_id == organization.id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None and not user.is_superadmin:
        raise ForbiddenError(
            "You do not have access to this organization.", code="cross_organization_access_denied"
        )
    return organization, membership


def get_principal(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
    x_organization_slug: Annotated[str | None, Header(alias="X-Organization-Slug")] = None,
) -> Principal:
    payload = getattr(request.state, "token_payload", {}) or {}
    organization, membership = _resolve_org(
        db, user, payload.get("org"), x_organization_id, x_organization_slug
    )

    if user.is_superadmin:
        role_code = RoleCode.SUPER_ADMIN
        permissions = ALL_PERMISSIONS
    else:
        if membership is None:
            raise ForbiddenError("Membership is not active.", code="membership_inactive")
        role = db.get(Role, membership.role_id)
        if role is None:
            raise ForbiddenError("Your role assignment is invalid.", code="invalid_role")
        role_code = RoleCode(role.code)
        permissions = permissions_for_role(db, role.id) | {"notification:read"}

    bind_identity(user.id, organization.id)
    principal = Principal(
        user=user,
        organization=organization,
        membership=membership,
        role=role_code,
        permissions=permissions,
        is_superadmin=user.is_superadmin,
    )
    request.state.principal = principal
    request.state.user = user
    request.state.organization = organization
    return principal


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_permission(*permissions: str) -> Callable[..., Principal]:
    """Dependency factory enforcing one or more permissions (all required)."""

    def _checker(principal: CurrentPrincipal) -> Principal:
        missing = [p for p in permissions if p not in principal.permissions]
        if missing:
            raise ForbiddenError(
                "You do not have permission to perform this action.",
                code="missing_permission",
                details={"required": list(permissions), "missing": missing},
            )
        return principal

    return _checker


PermissionChecker = Callable[..., Principal]


__all__ = [
    "CurrentPrincipal",
    "CurrentUser",
    "PermissionChecker",
    "Principal",
    "get_current_user",
    "get_principal",
    "require_permission",
]
