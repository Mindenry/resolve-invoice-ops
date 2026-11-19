"""Defer background dispatch until the surrounding transaction commits."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger(__name__)


def queue_task_after_commit(
    db: Session,
    task_name: str,
    payload: dict[str, Any],
    org_id: uuid.UUID,
) -> None:
    """Register a task that must only run once the current transaction is durable."""
    pending: list[tuple[str, dict[str, Any], uuid.UUID]] = db.info.setdefault("pending_tasks", [])
    pending.append((task_name, payload, org_id))
    if db.info.get("pending_listener_attached"):
        return
    db.info["pending_listener_attached"] = True

    @event.listens_for(db, "after_commit")
    def _flush_tasks(session: Session) -> None:  # pragma: no cover - exercised via API tests
        while True:
            tasks = session.info.get("pending_tasks") or []
            if not tasks:
                return
            session.info["pending_tasks"] = []
            from app.workers.dispatch import dispatch_job

            for name, task_payload, task_org_id in tasks:
                try:
                    dispatch_job(name, task_payload, task_org_id)
                except Exception:  # noqa: BLE001 - never break the committed request
                    logger.exception("post_commit_dispatch_failed", task=name)

    @event.listens_for(db, "after_soft_rollback")
    def _drop_tasks(session: Session, _previous_transaction: object) -> None:  # pragma: no cover
        session.info["pending_tasks"] = []
