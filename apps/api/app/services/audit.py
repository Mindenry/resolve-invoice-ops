"""Audit trail writer.

Audit rows are append-only: the application exposes read endpoints only. Callers pass
sanitized before/after snapshots; secrets and document contents must never be included.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.context import get_http_context, request_id_var
from app.models.audit import AuditLog
from app.models.identity import User


def record_download(db: Session, *, principal: Any, document: Any) -> None:
    """Audit a document download (kept in the audit service so all callers share it)."""
    record_audit(
        db,
        org_id=principal.org_id,
        action="document.downloaded",
        entity_type="document",
        entity_id=document.id,
        summary=f"Document {document.original_filename} downloaded",
        actor=principal.user,
    )


def record_audit(
    db: Session,
    *,
    org_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    summary: str = "",
    actor: User | None = None,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    http_ctx = get_http_context()
    resolved_email = actor.email if actor else actor_email
    resolved_actor_id = actor.id if actor else actor_id
    if resolved_email is None and resolved_actor_id is not None:
        resolved_actor = db.get(User, resolved_actor_id)
        if resolved_actor is not None:
            resolved_email = resolved_actor.email
    log = AuditLog(
        org_id=org_id,
        actor_user_id=resolved_actor_id,
        actor_email=resolved_email,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        summary=summary[:400],
        before=before,
        after=after,
        context=context or {},
        ip_address=http_ctx.ip_address if http_ctx else None,
        user_agent=(http_ctx.user_agent[:255] if http_ctx and http_ctx.user_agent else None),
        request_id=request_id_var.get(),
    )
    db.add(log)
    return log
