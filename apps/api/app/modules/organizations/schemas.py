"""Organization schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ORMModel


class OrganizationOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    legal_name: str | None = None
    tax_id: str | None = None
    default_currency: str
    timezone: str
    settings: dict[str, Any] = Field(default_factory=dict)
    branding: dict[str, Any] = Field(default_factory=dict)
    is_demo: bool
    created_at: datetime | None = None


class OrganizationUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, max_length=64)
    branding: dict[str, Any] | None = None


class OrganizationSettingsOut(ORMModel):
    settings: dict[str, Any]
    branding: dict[str, Any]


class OrganizationSettingsUpdate(ORMModel):
    settings: dict[str, Any] | None = None
    branding: dict[str, Any] | None = None


class RoleOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    rank: int


class PermissionOut(ORMModel):
    id: uuid.UUID
    code: str
    description: str
    group: str


class RolePermissionMatrix(ORMModel):
    roles: list[RoleOut]
    permissions: list[PermissionOut]
    matrix: dict[str, list[str]]
