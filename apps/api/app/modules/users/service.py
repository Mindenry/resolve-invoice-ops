"""Organization member management."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import Pagination
from app.core.permissions import ROLE_RANK
from app.core.security import generate_opaque_token, hash_password, validate_password_strength
from app.domain.enums import RoleCode
from app.models.identity import Membership, Role, User
from app.modules.auth.schemas import OrganizationChoice
from app.modules.users.schemas import InviteMemberRequest, MemberOut, UpdateMemberRequest
from app.services.audit import record_audit
from app.services.email import send_email


def _member_row(membership: Membership, user: User, role: Role) -> MemberOut:
    return MemberOut(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role_code=RoleCode(role.code),
        role_name=role.name,
        is_active=membership.is_active and user.is_active,
        job_title=user.job_title,
        last_active_at=membership.last_active_at,
        created_at=membership.created_at,
    )


def list_members(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    search: str | None = None,
    role: RoleCode | None = None,
    active_only: bool = False,
) -> tuple[list[MemberOut], int]:
    stmt = (
        select(Membership, User, Role)
        .join(User, User.id == Membership.user_id)
        .join(Role, Role.id == Membership.role_id)
        .where(Membership.org_id == org_id, User.deleted_at.is_(None))
    )
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(pattern), func.lower(User.full_name).like(pattern)))
    if role:
        stmt = stmt.where(Role.code == role.value)
    if active_only:
        stmt = stmt.where(Membership.is_active.is_(True), User.is_active.is_(True))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(User.full_name).offset(pagination.offset).limit(pagination.page_size)).all()
    return [_member_row(m, u, r) for m, u, r in rows], total


def invite_member(
    db: Session, *, org_id: uuid.UUID, actor: User, actor_role: RoleCode, payload: InviteMemberRequest
) -> tuple[MemberOut, bool]:
    if payload.role == RoleCode.SUPER_ADMIN:
        raise ForbiddenError("The super admin role cannot be granted through invitations.", code="role_not_grantable")
    if ROLE_RANK[payload.role] > ROLE_RANK[actor_role] and actor_role != RoleCode.SUPER_ADMIN:
        raise ForbiddenError(
            "You cannot grant a role with more privileges than your own.", code="role_escalation_denied"
        )

    role = db.scalar(select(Role).where(Role.code == payload.role.value))
    if role is None:
        raise NotFoundError("Role not found.", code="role_not_found")

    email = payload.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    created_user = False
    if user is None:
        temp_password = payload.temporary_password
        if temp_password:
            validate_password_strength(temp_password)
        else:
            temp_password = generate_opaque_token("Tmp1") + "aA1"
        user = User(
            email=email,
            full_name=payload.full_name,
            password_hash=hash_password(temp_password),
            job_title=payload.job_title,
            must_change_password=True,
            is_active=True,
        )
        db.add(user)
        db.flush()
        created_user = True
    else:
        if user.deleted_at is not None:
            raise ConflictError("This user account has been deleted.", code="user_deleted")
        existing = db.scalar(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id))
        if existing and existing.is_active:
            raise ConflictError("This user is already a member of the organization.", code="already_member")
        if existing:
            existing.is_active = True
            existing.role_id = role.id
            membership = existing
        else:
            membership = Membership(org_id=org_id, user_id=user.id, role_id=role.id)
            db.add(membership)
            db.flush()
        record_audit(
            db,
            org_id=org_id,
            action="user.member_reactivated",
            entity_type="membership",
            entity_id=membership.id,
            summary=f"{user.email} was re-added as {role.name}",
            actor=actor,
        )
        db.commit()
        return _member_row(membership, user, role), False

    membership = Membership(org_id=org_id, user_id=user.id, role_id=role.id, invited_by_id=actor.id)
    db.add(membership)
    db.flush()
    record_audit(
        db,
        org_id=org_id,
        action="user.member_invited",
        entity_type="membership",
        entity_id=membership.id,
        summary=f"{user.email} invited as {role.name}",
        actor=actor,
        after={"email": user.email, "role": role.code},
    )
    db.commit()

    invitation_sent = False
    if created_user and not payload.temporary_password:
        token, _ = _issue_reset(db, user)
        link = f"{_frontend_url()}/reset-password?token={token}"
        try:
            send_email(
                to=user.email,
                subject="You have been invited to RESOLVE",
                body=(
                    f"Hello {user.full_name},\n\nYou were invited to RESOLVE as {role.name}. "
                    f"Choose a password using this link (valid for 30 minutes):\n\n{link}\n"
                ),
            )
            invitation_sent = True
        except Exception:  # noqa: BLE001 - invitation email failure is reported, not hidden
            invitation_sent = False
    return _member_row(membership, user, role), invitation_sent


def _issue_reset(db: Session, user: User) -> tuple[str, str]:
    from app.modules.auth.service import request_password_reset

    return request_password_reset(db, user.email)


def _frontend_url() -> str:
    from app.config.settings import settings

    return settings.FRONTEND_URL


def update_member(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor: User,
    actor_role: RoleCode,
    membership_id: uuid.UUID,
    payload: UpdateMemberRequest,
) -> MemberOut:
    row = db.execute(
        select(Membership, User, Role)
        .join(User, User.id == Membership.user_id)
        .join(Role, Role.id == Membership.role_id)
        .where(Membership.id == membership_id, Membership.org_id == org_id)
    ).first()
    if row is None:
        raise NotFoundError("Member not found.", code="member_not_found")
    membership, user, role = row

    if actor.id == user.id and payload.is_active is False:
        raise BadRequestError("You cannot deactivate your own membership.", code="cannot_deactivate_self")

    if payload.role is not None and payload.role != RoleCode(role.code):
        if payload.role == RoleCode.SUPER_ADMIN:
            raise ForbiddenError("The super admin role cannot be granted.", code="role_not_grantable")
        if actor_role != RoleCode.SUPER_ADMIN and ROLE_RANK[payload.role] > ROLE_RANK[actor_role]:
            raise ForbiddenError("You cannot grant a role with more privileges than your own.", code="role_escalation_denied")
        if actor_role != RoleCode.SUPER_ADMIN and ROLE_RANK[RoleCode(role.code)] > ROLE_RANK[actor_role]:
            raise ForbiddenError("You cannot modify a member with more privileges than your own.", code="role_escalation_denied")
        new_role = db.scalar(select(Role).where(Role.code == payload.role.value))
        if new_role is None:
            raise NotFoundError("Role not found.", code="role_not_found")
        _ensure_not_last_admin(db, org_id, membership, RoleCode(role.code))
        before_role = role.code
        membership.role_id = new_role.id
        role = new_role
        record_audit(
            db,
            org_id=org_id,
            action="user.role_changed",
            entity_type="membership",
            entity_id=membership.id,
            summary=f"{user.email} role changed from {before_role} to {role.code}",
            actor=actor,
            before={"role": before_role},
            after={"role": role.code},
        )

    if payload.is_active is not None and payload.is_active != membership.is_active:
        if not payload.is_active:
            _ensure_not_last_admin(db, org_id, membership, RoleCode(role.code))
        membership.is_active = payload.is_active
        record_audit(
            db,
            org_id=org_id,
            action="user.member_updated",
            entity_type="membership",
            entity_id=membership.id,
            summary=f"{user.email} {'activated' if payload.is_active else 'deactivated'}",
            actor=actor,
        )

    if payload.job_title is not None:
        user.job_title = payload.job_title

    db.commit()
    return _member_row(membership, user, role)


def _ensure_not_last_admin(
    db: Session, org_id: uuid.UUID, membership: Membership, role_code: RoleCode
) -> None:
    if role_code != RoleCode.ORG_ADMIN:
        return
    admin_role = db.scalar(select(Role).where(Role.code == RoleCode.ORG_ADMIN.value))
    if admin_role is None:
        return
    count = db.scalar(
        select(func.count())
        .select_from(Membership)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.org_id == org_id,
            Membership.is_active.is_(True),
            Role.code == RoleCode.ORG_ADMIN.value,
            Membership.id != membership.id,
        )
    )
    if not count:
        raise BadRequestError(
            "The organization must keep at least one active organization administrator.",
            code="last_admin_protected",
        )


def update_profile(
    db: Session, *, user: User, full_name: str | None, job_title: str | None, locale: Any
) -> User:
    if full_name is not None:
        user.full_name = full_name
    if job_title is not None:
        user.job_title = job_title
    if locale is not None:
        user.locale = locale
    record_audit(
        db,
        org_id=None,
        action="user.profile_updated",
        entity_type="user",
        entity_id=user.id,
        summary="Profile updated",
        actor=user,
    )
    db.commit()
    return user


def list_roles(db: Session) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.rank)).all())


def organization_choices(db: Session, user: User) -> list[OrganizationChoice]:
    from app.modules.auth.service import organization_choices as _choices

    return _choices(db, user)
