"""Shared Pydantic schema helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class APIMessage(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class TimeRange(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class CountedItem(BaseModel):
    key: str
    label: str
    count: int
    percentage: float = 0.0


class TimeSeriesPoint(BaseModel):
    bucket: str
    value: float
    secondary: float | None = None


class NamedCount(BaseModel):
    name: str
    value: int


class Option(BaseModel, Generic[T]):
    value: T
    label: str


class IdResponse(BaseModel):
    id: str


class BulkIds(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
