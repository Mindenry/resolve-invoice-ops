"""Domain event emission (transactional outbox).

Services persist a DomainEvent in the same transaction as the business change. A
background task later fans the event out to webhook/n8n integrations. Consumers must be
idempotent: events carry a stable event id and may be retried.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.domain.enums import EventType
from app.models.audit import DomainEvent


def emit_event(
    db: Session,
    *,
    org_id: uuid.UUID,
    event_type: EventType | str,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> DomainEvent:
    event = DomainEvent(
        org_id=org_id,
        event_type=str(event_type),
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        payload=payload or {},
        status="PENDING",
    )
    db.add(event)
    return event
