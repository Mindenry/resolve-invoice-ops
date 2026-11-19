"""Authentication request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.domain.enums import RoleCode
from app.modules.organizations.schemas import OrganizationOut
from app.modules.users.schemas import UserProfile
from app.schemas.common import ORMModel


class OrganizationChoice(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    role: RoleCode


class LoginRequest(ORMModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    organization_slug: str | None = Field(default=None, max_length=80)
    remember: bool = False


class RegisterRequest(ORMModel):
    organization_name: str = Field(min_length=1, max_length=160)
    organization_slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    full_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class TokenPair(ORMModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


class LoginResponse(ORMModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    user: UserProfile
    organization: OrganizationOut
    role: RoleCode
    permissions: list[str]
    organizations: list[OrganizationChoice]


class RefreshRequest(ORMModel):
    refresh_token: str | None = Field(default=None, max_length=400)


class SessionOut(ORMModel):
    id: uuid.UUID
    user_agent: str | None = None
    ip_address: str | None = None
    issued_at: datetime
    expires_at: datetime
    is_current: bool = False


class PasswordResetRequest(ORMModel):
    email: EmailStr


class PasswordResetConfirm(ORMModel):
    token: str = Field(min_length=10, max_length=400)
    new_password: str = Field(min_length=10, max_length=200)


class PasswordResetResponse(ORMModel):
    message: str
    dev_token: str | None = None


class PasswordChangeResponse(ORMModel):
    message: str


class MeResponse(ORMModel):
    user: UserProfile
    organization: OrganizationOut
    role: RoleCode
    permissions: list[str]
    organizations: list[OrganizationChoice]
    is_superadmin: bool
    demo_mode: bool
