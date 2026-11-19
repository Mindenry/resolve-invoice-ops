"""Analytics endpoints for the command centre and reports."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import ExceptionType, Priority
from app.modules.analytics import service
from app.modules.analytics.schemas import CommandCenter

router = APIRouter(prefix="/analytics", tags=["Analytics"])

AnalyticsReader = Annotated[Principal, Depends(require_permission("analytics:read"))]


@router.get("/overview", response_model=CommandCenter, summary="Command centre metrics")
def overview(
    principal: AnalyticsReader,
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
    exception_type: list[ExceptionType] | None = Query(None),
    priority: list[Priority] | None = Query(None),
) -> CommandCenter:
    return service.overview(
        db,
        org_id=principal.org_id,
        days=days,
        exception_types=exception_type,
        priorities=priority,
    )


@router.get("/resolution-time", summary="Average resolution time by day")
def resolution_time(
    principal: AnalyticsReader,
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
) -> list[dict[str, object]]:
    return service.resolution_time_series(db, org_id=principal.org_id, days=days)


@router.get("/ai-usage", summary="AI usage, tokens and cost")
def ai_usage(
    principal: AnalyticsReader,
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
) -> dict[str, object]:
    return service.ai_usage(db, org_id=principal.org_id, days=days)
