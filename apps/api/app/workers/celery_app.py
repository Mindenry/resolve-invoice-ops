"""Celery application and beat schedule."""

from __future__ import annotations

import uuid

from celery import Celery
from celery.schedules import crontab

from app.config.settings import settings

celery_app = Celery(
    "resolve",
    broker=settings.CELERY_BROKER_URL or settings.REDIS_URL,
    backend=settings.CELERY_RESULT_BACKEND or settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=900,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=False,
)

celery_app.conf.beat_schedule = {
    "expire-approvals": {
        "task": "resolve.maintenance.expire_approvals",
        "schedule": crontab(minute="*/10"),
    },
    "publish-domain-events": {
        "task": "resolve.maintenance.publish_events",
        "schedule": crontab(minute="*"),
    },
    "deliver-notification-emails": {
        "task": "resolve.maintenance.deliver_notifications",
        "schedule": crontab(minute="*"),
    },
    "sync-integrations": {
        "task": "resolve.maintenance.sync_integrations",
        "schedule": crontab(hour="*/6"),
    },
}


@celery_app.task(name="resolve.run_job", bind=True)
def run_job_task(self, job_id: str) -> None:  # pragma: no cover - executed in a worker process
    from app.workers.dispatch import run_job

    run_job(uuid.UUID(job_id))


def _dispatch_maintenance(task_name: str) -> None:
    from app.db.session import session_scope
    from app.models.identity import Organization
    from app.workers.dispatch import dispatch_job

    with session_scope() as db:
        org_ids = [row[0] for row in db.query(Organization.id).filter(Organization.deleted_at.is_(None)).all()]
    for org_id in org_ids:
        dispatch_job(task_name, {}, org_id)


@celery_app.task(name="resolve.maintenance.expire_approvals")
def expire_approvals_task() -> None:  # pragma: no cover - worker process
    _dispatch_maintenance("expire_approvals")


@celery_app.task(name="resolve.maintenance.publish_events")
def publish_events_task() -> None:  # pragma: no cover - worker process
    _dispatch_maintenance("publish_domain_events")


@celery_app.task(name="resolve.maintenance.deliver_notifications")
def deliver_notifications_task() -> None:  # pragma: no cover - worker process
    _dispatch_maintenance("deliver_pending_notifications")


@celery_app.task(name="resolve.maintenance.sync_integrations")
def sync_integrations_task() -> None:  # pragma: no cover - worker process
    _dispatch_maintenance("sync_integrations")
