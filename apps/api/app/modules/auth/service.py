"""Authentication, registration, refresh-token rotation and RBAC bootstrap."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.core.logging import get_logger
from app.core.permissions import (
    PERMISSIONS,
    ROLE_DESCRIPTIONS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    ROLE_RANK,
    PermissionDef,
)
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    utcnow,
    validate_password_strength,
    verify_password,
)
from app.domain.enums import RoleCode
from app.models.identity import (
    Membership,
    Organization,
    PasswordResetToken,
    Permission,
    RefreshToken,
    Role,
    User,
    role_permissions,
)
from app.modules.auth.schemas import LoginResponse, OrganizationChoice, RegisterRequest
from app.modules.organizations.schemas import OrganizationOut
from app.modules.users.schemas import UserProfile
from app.services.audit import record_audit
from app.services.email import send_email

logger = get_logger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
RESET_TOKEN_MINUTES = 30


# --------------------------------------------------------------------------- RBAC


def ensure_rbac(db: Session) -> None:
    """Idempotently synchronize the permission catalog and system roles."""
    existing_permissions = {p.code: p for p in db.scalars(select(Permission)).all()}
    created = 0
    for definition in PERMISSIONS:
        if definition.code not in existing_permissions:
            permission = Permission(
                code=definition.code, description=definition.description, group=definition.group
            )
            db.add(permission)
            existing_permissions[definition.code] = permission
            created += 1
    db.flush()

    existing_roles = {r.code: r for r in db.scalars(select(Role)).all()}
    for role_code in RoleCode:
        role = existing_roles.get(role_code.value)
        if role is None:
            role = Role(
                code=role_code.value,
                name=ROLE_LABELS[role_code],
                description=ROLE_DESCRIPTIONS[role_code],
                rank=ROLE_RANK[role_code],
                is_system=True,
            )
            db.add(role)
            db.flush()
            existing_roles[role_code.value] = role
        else:
            role.name = ROLE_LABELS[role_code]
            role.description = ROLE_DESCRIPTIONS[role_code]
            role.rank = ROLE_RANK[role_code]

        desired = {existing_permissions[code].id for code in ROLE_PERMISSIONS[role_code]}
        current = set(
            db.scalars(select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role.id))
        )
        if desired - current:
            db.execute(
                role_permissions.insert(),
                [{"role_id": role.id, "permission_id": pid} for pid in desired - current],
            )
        if current - desired:
            db.execute(
                delete(role_permissions).where(
                    role_permissions.c.role_id == role.id,
                    role_permissions.c.permission_id.in_(current - desired),
                )
            )
    if created:
        logger.info("rbac_permissions_created", count=created)


def get_role(db: Session, code: RoleCode | str) -> Role:
    value = code.value if isinstance(code, RoleCode) else code
    role = db.scalar(select(Role).where(Role.code == value))
    if role is None:
        raise NotFoundError(f"Role '{value}' is not configured.", code="role_not_found")
    return role


def permissions_for_role(db: Session, role_id: uuid.UUID) -> frozenset[str]:
    rows = db.execute(
        select(Permission.code).join(role_permissions, role_permissions.c.permission_id == Permission.id).where(
            role_permissions.c.role_id == role_id
        )
    ).all()
    return frozenset(row[0] for row in rows)


# ----------------------------------------------------------------------- Registration


def _slug_exists(db: Session, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Organization).where(Organization.slug == slug)) > 0


def create_organization(
    db: Session,
    *,
    name: str,
    slug: str,
    default_currency: str = "USD",
    is_demo: bool = False,
    branding: dict[str, Any] | None = None,
) -> Organization:
    if _slug_exists(db, slug):
        raise ConflictError("An organization with this slug already exists.", code="slug_taken")
    organization = Organization(
        name=name,
        slug=slug,
        default_currency=default_currency,
        is_demo=is_demo,
        branding=branding or {"accent": "#146C4F", "initials": name[:2].upper()},
        settings={
            "duplicate_invoice": {"absolute_tolerance": "0.00", "percentage_tolerance": "0.50"},
            "amount_mismatch": {"absolute_tolerance": "1.00", "percentage_tolerance": "1.00"},
            "require_purchase_order": True,
            "allow_self_approval": settings.ALLOW_SELF_APPROVAL,
        },
    )
    db.add(organization)
    db.flush()
    return organization


def register_organization(db: Session, payload: RegisterRequest) -> tuple[LoginResponse, str]:
    if settings.is_production and not settings.DEMO_MODE:
        raise ForbiddenError(
            "Self-service registration is disabled in production. Ask an administrator for an invitation.",
            code="registration_disabled",
        )
    validate_password_strength(payload.password)
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("An account with this email already exists.", code="email_taken")

    organization = create_organization(
        db, name=payload.organization_name, slug=payload.organization_slug.lower()
    )
    user = User(
        email=email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        avatar_color=_color_for(email),
    )
    db.add(user)
    db.flush()
    admin_role = get_role(db, RoleCode.ORG_ADMIN)
    membership = Membership(org_id=organization.id, user_id=user.id, role_id=admin_role.id)
    db.add(membership)

    from app.modules.exceptions.rules import ensure_default_rules

    ensure_default_rules(db, organization.id, created_by_id=user.id)

    record_audit(
        db,
        org_id=organization.id,
        action="auth.register",
        entity_type="organization",
        entity_id=organization.id,
        summary=f"Organization '{organization.name}' registered by {user.email}",
        actor=user,
    )
    db.commit()
    return _login_response(db, user, organization, membership)


# ----------------------------------------------------------------------------- Login


def authenticate(db: Session, *, email: str, password: str, organization_slug: str | None) -> tuple[
    User, Organization, Membership
]:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    generic_failure = UnauthorizedError("Invalid email or password.", code="invalid_credentials")

    if user is None or user.deleted_at is not None:
        # Constant-ish work factor so timing does not reveal account existence.
        verify_password(password, hash_password("placeholder-do-not-use"))
        raise generic_failure

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise UnauthorizedError(
            "This account is temporarily locked after repeated failed sign-in attempts.",
            code="account_locked",
        )

    if not user.is_active:
        raise ForbiddenError("This account has been deactivated.", code="account_inactive")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        record_audit(
            db,
            org_id=None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            summary=f"Failed sign-in for {user.email}",
            actor_id=user.id,
            actor_email=user.email,
        )
        db.commit()
        raise generic_failure

    membership, organization = _select_membership(db, user, organization_slug)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    membership.last_active_at = now
    db.flush()
    return user, organization, membership


def _select_membership(
    db: Session, user: User, organization_slug: str | None
) -> tuple[Membership, Organization]:
    stmt = (
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id, Membership.is_active.is_(True), Organization.deleted_at.is_(None))
    )
    rows = db.execute(stmt).all()
    if not rows:
        raise ForbiddenError(
            "Your account is not an active member of any organization.", code="no_membership"
        )
    if organization_slug:
        for membership, organization in rows:
            if organization.slug == organization_slug.lower():
                return membership, organization
        raise ForbiddenError("You are not a member of that organization.", code="not_a_member")

    if len(rows) > 1:
        choices = [
            {"organization": org.slug, "role": db.get(Role, m.role_id).code}  # type: ignore[union-attr]
            for m, org in rows
        ]
        raise BadRequestError(
            "This account belongs to multiple organizations. Provide organization_slug.",
            code="organization_required",
            details={"organizations": choices},
        )
    return rows[0][0], rows[0][1]


def build_login_response(
    db: Session, user: User, organization: Organization, membership: Membership
) -> tuple[LoginResponse, str]:
    return _login_response(db, user, organization, membership)


def organization_choices(db: Session, user: User) -> list[OrganizationChoice]:
    rows = db.execute(
        select(Organization, Role)
        .join(Membership, Membership.org_id == Organization.id)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.user_id == user.id,
            Membership.is_active.is_(True),
            Organization.deleted_at.is_(None),
        )
        .order_by(Organization.name)
    ).all()
    choices: list[OrganizationChoice] = []
    for organization, role in rows:
        choices.append(
            OrganizationChoice(id=organization.id, name=organization.name, slug=organization.slug, role=RoleCode(role.code))
        )
    return choices


def _login_response(
    db: Session, user: User, organization: Organization, membership: Membership
) -> tuple[LoginResponse, str]:
    role = db.get(Role, membership.role_id)
    if role is None:
        raise ForbiddenError("Your role assignment is invalid.", code="invalid_role")
    permissions = permissions_for_role(db, role.id) | {"notification:read"}
    access_token, expires_at = create_access_token(
        user_id=user.id,
        organization_id=organization.id,
        role=role.code,
        is_superadmin=user.is_superadmin,
    )
    refresh_raw, refresh_row = _new_refresh_token(
        db, user=user, org_id=organization.id, family_id=uuid.uuid4(), parent_hash=None
    )
    record_audit(
        db,
        org_id=organization.id,
        action="auth.login",
        entity_type="session",
        entity_id=refresh_row.id,
        summary=f"{user.email} signed in to {organization.name}",
        actor=user,
    )
    db.commit()
    expires_in = int((expires_at - utcnow()).total_seconds())
    response = LoginResponse(
        access_token=access_token,
        expires_in=max(expires_in, 1),
        refresh_expires_in=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        user=UserProfile.model_validate(user),
        organization=OrganizationOut.model_validate(organization),
        role=RoleCode(role.code),
        permissions=sorted(permissions),
        organizations=organization_choices(db, user),
    )
    return response, refresh_raw


def _new_refresh_token(
    db: Session,
    *,
    user: User,
    org_id: uuid.UUID,
    family_id: uuid.UUID,
    parent_hash: str | None,
) -> tuple[str, RefreshToken]:
    raw = generate_opaque_token("rt_")
    now = utcnow()
    row = RefreshToken(
        user_id=user.id,
        org_id=org_id,
        token_hash=hash_token(raw),
        family_id=family_id,
        parent_hash=parent_hash,
        issued_at=now,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
    )
    db.add(row)
    db.flush()
    return raw, row


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[LoginResponse, str]:
    token_hash = hash_token(raw_token)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())
    if row is None:
        raise UnauthorizedError("Refresh token is invalid.", code="invalid_refresh_token")

    now = utcnow()
    if row.revoked_at is not None:
        # Reuse of a rotated token: revoke the whole family and fail closed.
        db.execute(
            select(RefreshToken).where(RefreshToken.family_id == row.family_id)
        )
        for sibling in db.scalars(select(RefreshToken).where(RefreshToken.family_id == row.family_id)):
            if sibling.revoked_at is None:
                sibling.revoked_at = now
                sibling.revoked_reason = "reuse_detected"
        record_audit(
            db,
            org_id=row.org_id,
            action="auth.refresh_reuse_detected",
            entity_type="session",
            entity_id=row.id,
            summary="Refresh token reuse detected; token family revoked.",
            actor_id=row.user_id,
        )
        db.commit()
        raise UnauthorizedError(
            "This session is no longer valid. Please sign in again.", code="refresh_token_reuse"
        )

    if _as_utc(row.expires_at) <= now:
        raise UnauthorizedError("Refresh token has expired.", code="refresh_token_expired")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise UnauthorizedError("Account is no longer active.", code="account_inactive")
    if row.org_id is None:
        raise UnauthorizedError("Refresh token is not bound to an organization.", code="invalid_refresh_token")
    organization = db.get(Organization, row.org_id)
    if organization is None or organization.deleted_at is not None:
        raise UnauthorizedError("Organization is no longer available.", code="organization_unavailable")
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.org_id == organization.id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        raise UnauthorizedError("Membership is no longer active.", code="membership_inactive")

    raw_new, new_row = _new_refresh_token(
        db, user=user, org_id=organization.id, family_id=row.family_id, parent_hash=row.token_hash
    )
    row.revoked_at = now
    row.revoked_reason = "rotated"
    db.flush()
    response = _login_response_no_commit(db, user, organization, membership)
    record_audit(
        db,
        org_id=organization.id,
        action="auth.token_refreshed",
        entity_type="session",
        entity_id=new_row.id,
        summary="Refresh token rotated.",
        actor=user,
    )
    db.commit()
    return response, raw_new


def _login_response_no_commit(
    db: Session, user: User, organization: Organization, membership: Membership
) -> LoginResponse:
    role = db.get(Role, membership.role_id)
    if role is None:
        raise ForbiddenError("Your role assignment is invalid.", code="invalid_role")
    permissions = permissions_for_role(db, role.id) | {"notification:read"}
    access_token, expires_at = create_access_token(
        user_id=user.id,
        organization_id=organization.id,
        role=role.code,
        is_superadmin=user.is_superadmin,
    )
    return LoginResponse(
        access_token=access_token,
        expires_in=max(int((expires_at - utcnow()).total_seconds()), 1),
        refresh_expires_in=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        user=UserProfile.model_validate(user),
        organization=OrganizationOut.model_validate(organization),
        role=RoleCode(role.code),
        permissions=sorted(permissions),
        organizations=organization_choices(db, user),
    )


def revoke_token(db: Session, raw_token: str, *, reason: str = "logout") -> uuid.UUID | None:
    token_hash = hash_token(raw_token)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        row.revoked_reason = reason
    return row.id


def revoke_all_sessions(db: Session, user_id: uuid.UUID, *, reason: str = "password_changed") -> int:
    now = utcnow()
    count = 0
    for row in db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    ):
        row.revoked_at = now
        row.revoked_reason = reason
        count += 1
    return count


def list_sessions(db: Session, user_id: uuid.UUID) -> list[RefreshToken]:
    now = utcnow()
    rows = db.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.issued_at.desc())
    ).all()
    latest_by_family: dict[uuid.UUID, RefreshToken] = {}
    for row in rows:
        latest_by_family.setdefault(row.family_id, row)
    return list(latest_by_family.values())


def revoke_session(db: Session, user: User, session_id: uuid.UUID) -> None:
    row = db.get(RefreshToken, session_id)
    if row is None or row.user_id != user.id:
        raise NotFoundError("Session not found.", code="session_not_found")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        row.revoked_reason = "revoked_by_user"


# --------------------------------------------------------------------- Password flows


def request_password_reset(db: Session, email: str) -> tuple[str | None, str]:
    """Always returns the same message to avoid account enumeration."""
    message = "If an account exists for that email, a reset link has been sent."
    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.deleted_at.is_(None)))
    if user is None or not user.is_active:
        return None, message

    raw = generate_opaque_token("pr_")
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES),
        )
    )
    record_audit(
        db,
        org_id=None,
        action="auth.password_reset_requested",
        entity_type="user",
        entity_id=user.id,
        summary=f"Password reset requested for {user.email}",
        actor_id=user.id,
        actor_email=user.email,
    )
    db.commit()
    link = f"{settings.FRONTEND_URL}/reset-password?token={raw}"
    try:
        send_email(
            to=user.email,
            subject="Reset your RESOLVE password",
            body=(
                f"Hello {user.full_name},\n\nUse the link below to reset your password. "
                f"It expires in {RESET_TOKEN_MINUTES} minutes.\n\n{link}\n"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - email failure must not leak account existence
        logger.warning("password_reset_email_failed", error=str(exc))
    return raw, message


def confirm_password_reset(db: Session, token: str, new_password: str) -> None:
    validate_password_strength(new_password)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    now = utcnow()
    if row is None or row.used_at is not None or _as_utc(row.expires_at) <= now:
        raise BadRequestError("This password reset link is invalid or has expired.", code="invalid_reset_token")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise BadRequestError("This password reset link is invalid or has expired.", code="invalid_reset_token")
    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.must_change_password = False
    row.used_at = now
    revoke_all_sessions(db, user.id, reason="password_reset")
    record_audit(
        db,
        org_id=None,
        action="auth.password_reset_completed",
        entity_type="user",
        entity_id=user.id,
        summary=f"Password reset completed for {user.email}",
        actor_id=user.id,
        actor_email=user.email,
    )
    db.commit()


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise BadRequestError("Current password is incorrect.", code="invalid_current_password")
    if current_password == new_password:
        raise BadRequestError("New password must differ from the current password.", code="password_reused")
    validate_password_strength(new_password)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    revoke_all_sessions(db, user.id, reason="password_changed")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _color_for(seed: str) -> str:
    palette = ["#146C4F", "#8A4B23", "#2F5D8A", "#6B4C8A", "#8A5A12", "#1F6B6B"]
    return palette[int(hash_token(seed)[:2], 16) % len(palette)]


__all__ = [
    "PermissionDef",
    "authenticate",
    "build_login_response",
    "change_password",
    "confirm_password_reset",
    "create_organization",
    "ensure_rbac",
    "get_role",
    "list_sessions",
    "permissions_for_role",
    "register_organization",
    "request_password_reset",
    "revoke_all_sessions",
    "revoke_session",
    "revoke_token",
    "rotate_refresh_token",
]
