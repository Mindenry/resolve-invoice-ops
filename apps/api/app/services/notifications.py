"""In-app and email notifications."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import NotificationChannel, NotificationStatus, NotificationType
from app.models.automation import Notification, NotificationPreference
from app.models.identity import User
from app.services.email import send_email


def notify(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    type: NotificationType,
    title: str,
    body: str = "",
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    send_mail: bool = False,
) -> Notification:
    """Create an in-app notification. Email is queued via the notification delivery task."""
    notification = Notification(
        org_id=org_id,
        user_id=user_id,
        type=type,
        title=title[:200],
        body=body,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        channel=NotificationChannel.IN_APP,
        status=NotificationStatus.SENT,
        payload=payload or {},
        email_requested=send_mail,
    )
    db.add(notification)
    db.flush()
    if send_mail and user_id is not None:
        from app.services.deferred import queue_task_after_commit

        queue_task_after_commit(
            db,
            "deliver_pending_notifications",
            {"notification_id": str(notification.id)},
            org_id,
        )
    return notification


def notify_many(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    type: NotificationType,
    title: str,
    body: str = "",
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    send_mail: bool = False,
) -> list[Notification]:
    return [
        notify(
            db,
            org_id=org_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            send_mail=send_mail,
        )
        for user_id in dict.fromkeys(user_ids)
    ]


def deliver_email(db: Session, notification_id: uuid.UUID) -> dict[str, str]:
    notification = db.get(Notification, notification_id)
    if notification is None:
        return {"status": "skipped", "reason": "notification_missing"}
    user = db.get(User, notification.user_id) if notification.user_id else None
    if user is None or not user.email:
        notification.status = NotificationStatus.FAILED
        notification.error = "Recipient has no email address."
        return {"status": "failed", "reason": "no_recipient"}
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user.id,
            NotificationPreference.event_type == notification.type.value,
        )
    )
    if preference is not None and not preference.email:
        return {"status": "skipped", "reason": "user_opted_out"}
    try:
        result = send_email(to=user.email, subject=f"[RESOLVE] {notification.title}", body=notification.body)
    except Exception as exc:  # noqa: BLE001 - delivery failure must be recorded, not raised
        notification.status = NotificationStatus.FAILED
        notification.error = str(exc)[:400]
        return {"status": "failed", "reason": str(exc)[:200]}
    notification.channel = NotificationChannel.EMAIL
    notification.status = NotificationStatus.SENT
    notification.sent_at = notification.created_at
    notification.error = None
    return {"status": "sent", **result}


def mark_read(db: Session, *, notification: Notification) -> None:
    from app.core.security import utcnow

    notification.read_at = utcnow()
    if notification.status == NotificationStatus.SENT:
        notification.status = NotificationStatus.READ


def deliver_pending_emails(db: Session, *, org_id: uuid.UUID, limit: int = 50) -> int:
    """Deliver queued notification emails. Returns the number of messages processed."""
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.org_id == org_id,
            Notification.sent_at.is_(None),
            Notification.payload["email_requested"].as_boolean().is_(True),
        )
        .order_by(Notification.created_at)
        .limit(limit)
    ).all()
    delivered = 0
    for row in rows:
        deliver_email(db, row.id)
        delivered += 1
    return delivered


def user_ids_with_permission(db: Session, *, org_id: uuid.UUID, permission: str) -> list[uuid.UUID]:
    from app.models.identity import Membership, Permission, Role, role_permissions

    rows = db.execute(
        select(Membership.user_id)
        .join(Role, Role.id == Membership.role_id)
        .join(role_permissions, role_permissions.c.role_id == Role.id)
        .join(Permission, Permission.id == role_permissions.c.permission_id)
        .where(
            Membership.org_id == org_id,
            Membership.is_active.is_(True),
            Permission.code == permission,
        )
        .distinct()
    ).all()
    return [row[0] for row in rows]
