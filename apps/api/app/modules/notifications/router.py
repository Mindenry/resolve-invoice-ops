"""Notification center endpoints and preferences."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, get_principal
from app.domain.enums import NotificationChannel, NotificationStatus, NotificationType
from app.models.automation import Notification, NotificationPreference
from app.schemas.common import APIMessage, ORMModel
from app.services.notifications import mark_read

router = APIRouter(prefix="/notifications", tags=["Notifications"])

NotificationReader = Annotated[Principal, Depends(get_principal)]


class NotificationOut(ORMModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    entity_type: str | None = None
    entity_id: str | None = None
    channel: NotificationChannel
    status: NotificationStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime


class NotificationPreferenceOut(ORMModel):
    event_type: str
    label: str
    in_app: bool
    email: bool


class NotificationPreferenceUpdate(ORMModel):
    event_type: str = Field(min_length=2, max_length=60)
    in_app: bool = True
    email: bool = True


@router.get("", response_model=Page[NotificationOut], summary="Your notifications")
def list_notifications(
    principal: NotificationReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    unread_only: bool = Query(False),
) -> Page[NotificationOut]:
    stmt = select(Notification).where(
        Notification.org_id == principal.org_id, Notification.user_id == principal.user_id
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Notification.created_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return Page.build([NotificationOut.model_validate(row) for row in rows], total, pagination)


@router.get("/unread-count", summary="Unread notification count")
def unread_count(principal: NotificationReader, db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.org_id == principal.org_id,
            Notification.user_id == principal.user_id,
            Notification.read_at.is_(None),
        )
    ) or 0
    return {"unread": int(count)}


@router.post("/read-all", response_model=APIMessage, summary="Mark all notifications as read")
def read_all(principal: NotificationReader, db: Annotated[Session, Depends(get_db)]) -> APIMessage:
    rows = db.scalars(
        select(Notification).where(
            Notification.org_id == principal.org_id,
            Notification.user_id == principal.user_id,
            Notification.read_at.is_(None),
        )
    ).all()
    for row in rows:
        mark_read(db, notification=row)
    db.commit()
    return APIMessage(message=f"{len(rows)} notification(s) marked as read.")


@router.post("/{notification_id}/read", response_model=NotificationOut, summary="Mark a notification as read")
def read_notification(
    notification_id: uuid.UUID,
    principal: NotificationReader,
    db: Annotated[Session, Depends(get_db)],
) -> NotificationOut:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.org_id == principal.org_id,
            Notification.user_id == principal.user_id,
        )
    )
    if notification is None:
        raise NotFoundError("Notification not found.", code="notification_not_found")
    mark_read(db, notification=notification)
    db.commit()
    return NotificationOut.model_validate(notification)


@router.get(
    "/preferences",
    response_model=list[NotificationPreferenceOut],
    summary="Notification preferences",
)
def get_preferences(
    principal: NotificationReader, db: Annotated[Session, Depends(get_db)]
) -> list[NotificationPreferenceOut]:
    saved = {
        pref.event_type: pref
        for pref in db.scalars(
            select(NotificationPreference).where(
                NotificationPreference.user_id == principal.user_id,
                NotificationPreference.org_id == principal.org_id,
            )
        ).all()
    }
    result = []
    for event_type in NotificationType:
        preference = saved.get(event_type.value)
        result.append(
            NotificationPreferenceOut(
                event_type=event_type.value,
                label=event_type.value.replace("_", " ").title(),
                in_app=preference.in_app if preference else True,
                email=preference.email if preference else event_type
                in {NotificationType.HIGH_PRIORITY_CASE, NotificationType.APPROVAL_REQUIRED, NotificationType.CASE_ASSIGNED},
            )
        )
    return result


@router.put("/preferences", response_model=NotificationPreferenceOut, summary="Update a preference")
def update_preference(
    payload: NotificationPreferenceUpdate,
    principal: NotificationReader,
    db: Annotated[Session, Depends(get_db)],
) -> NotificationPreferenceOut:
    try:
        NotificationType(payload.event_type)
    except ValueError as exc:
        from app.core.errors import BadRequestError

        raise BadRequestError("Unknown notification event type.", code="invalid_event_type") from exc
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == principal.user_id,
            NotificationPreference.org_id == principal.org_id,
            NotificationPreference.event_type == payload.event_type,
        )
    )
    if preference is None:
        preference = NotificationPreference(
            user_id=principal.user_id,
            org_id=principal.org_id,
            event_type=payload.event_type,
        )
        db.add(preference)
    preference.in_app = payload.in_app
    preference.email = payload.email
    db.commit()
    return NotificationPreferenceOut(
        event_type=payload.event_type,
        label=payload.event_type.replace("_", " ").title(),
        in_app=payload.in_app,
        email=payload.email,
    )
