"""User and organization membership schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.domain.enums import Locale, RoleCode
from app.schemas.common import ORMModel


class UserSummary(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_superadmin: bool
    job_title: str | None = None
    locale: Locale
    avatar_color: str | None = None
    created_at: datetime | None = None


class MembershipSummary(ORMModel):
    id: uuid.UUID
    role_code: RoleCode
    role_name: str
    is_active: bool
    created_at: datetime | None = None


class UserProfile(UserSummary):
    last_login_at: datetime | None = None


class UpdateProfileRequest(ORMModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    job_title: str | None = Field(default=None, max_length=120)
    locale: Locale | None = None


class ChangePasswordRequest(ORMModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class MemberOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role_code: RoleCode
    role_name: str
    is_active: bool
    job_title: str | None = None
    last_active_at: datetime | None = None
    created_at: datetime | None = None


class InviteMemberRequest(ORMModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    role: RoleCode
    job_title: str | None = Field(default=None, max_length=120)
    temporary_password: str | None = Field(default=None, min_length=10, max_length=200)


class UpdateMemberRequest(ORMModel):
    role: RoleCode | None = None
    is_active: bool | None = None
    job_title: str | None = Field(default=None, max_length=120)
