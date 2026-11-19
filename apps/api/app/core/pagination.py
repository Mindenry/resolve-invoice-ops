"""Pagination primitives shared by every list endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


@dataclass(slots=True)
class Pagination:
    page: int = 1
    page_size: int = 25
    sort: str | None = None
    order: str = "desc"

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination_params(
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(25, ge=1, le=200),
    sort: str | None = Query(None, max_length=60),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> Pagination:
    return Pagination(page=page, page_size=page_size, sort=sort, order=order)


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int
    has_next: bool


class Page(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, items: list[T], total: int, pagination: Pagination) -> Page[T]:
        pages = (total + pagination.page_size - 1) // pagination.page_size if total else 0
        return cls(
            items=items,
            meta=PageMeta(
                page=pagination.page,
                page_size=pagination.page_size,
                total=total,
                pages=pages,
                has_next=pagination.page < pages,
            ),
        )


class MessageResponse(BaseModel):
    message: str = Field(default="ok")
