"""Background job dispatch.

Celery is used whenever a broker is configured. Otherwise jobs run in a bounded local
thread pool (or inline in tests), so the product remains fully functional for local
development without Redis while still recording real job status in the database.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.config.settings import settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import SessionLocal, session_scope
from app.domain.enums import JobStatus
from app.models.automation import BackgroundJob
from app.workers.registry import get_task

logger = get_logger(__name__)

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.TASK_INLINE_MAX_CONCURRENCY), thread_name_prefix="resolve-job"
        )
    return _executor


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def dispatch_job(
    task_name: str,
    payload: dict[str, Any],
    org_id: uuid.UUID,
    *,
    max_attempts: int | None = None,
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """Persist a job and hand it to Celery or the local runner."""
    spec = get_task(task_name)
    with session_scope() as db:
        job = BackgroundJob(
            org_id=org_id,
            task_name=task_name,
            status=JobStatus.QUEUED,
            payload=payload,
            max_attempts=max_attempts or spec.max_attempts,
        )
        db.add(job)
        db.flush()
        job_id = job.id

    if settings.celery_enabled:
        try:
            from app.workers.celery_app import celery_app

            async_result = celery_app.send_task("resolve.run_job", args=[str(job_id)])
            with session_scope() as db:
                job_row = db.get(BackgroundJob, job_id)
                if job_row is not None:
                    job_row.celery_task_id = async_result.id
        except Exception as exc:  # noqa: BLE001 - broker may be unavailable
            logger.error("celery_dispatch_failed", task=task_name, job_id=str(job_id), error=str(exc))
            _mark_failed(job_id, f"Celery broker unavailable: {exc}")
        return job_id

    if settings.ENV == "test" or settings.TASK_RUNNER == "inline":
        run_job(job_id)
    else:
        _get_executor().submit(run_job, job_id)
    return job_id


def run_job(job_id: uuid.UUID) -> None:
    """Execute one job with its own database session and persist the outcome."""
    with session_scope() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            logger.warning("job_missing", job_id=str(job_id))
            return
        if job.status == JobStatus.SUCCEEDED:
            return
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or utcnow()
        job.attempts += 1
        task_name = job.task_name
        payload = dict(job.payload)
        org_id = job.org_id
        attempts = job.attempts
        max_attempts = job.max_attempts

    try:
        spec = get_task(task_name)
        result = spec.handler(payload, org_id)
    except Exception as exc:  # noqa: BLE001 - background failure is persisted
        logger.exception("job_failed", task=task_name, job_id=str(job_id))
        retry = attempts < max_attempts
        with session_scope() as db:
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                job.status = JobStatus.RETRYING if retry else JobStatus.FAILED
                job.error = f"{type(exc).__name__}: {exc}"[:4000]
                job.finished_at = utcnow() if not retry else None
        if retry:
            _schedule_local_retry(job_id, attempts)
        return

    with session_scope() as db:
        job = db.get(BackgroundJob, job_id)
        if job is not None:
            job.status = JobStatus.SUCCEEDED
            job.result = result or {}
            job.error = None
            job.finished_at = utcnow()
    logger.info("job_succeeded", task=task_name, job_id=str(job_id))


def _schedule_local_retry(job_id: uuid.UUID, attempts: int) -> None:
    if settings.celery_enabled:
        try:
            from app.workers.celery_app import celery_app

            celery_app.send_task("resolve.run_job", args=[str(job_id)], countdown=min(2**attempts, 60))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("celery_retry_dispatch_failed", job_id=str(job_id), error=str(exc))
    if settings.ENV != "test":
        _get_executor().submit(_retry_later, job_id, attempts)


def _retry_later(job_id: uuid.UUID, attempts: int) -> None:
    import time

    time.sleep(min(2**attempts, 10))
    run_job(job_id)


def retry_job(job_id: uuid.UUID, org_id: uuid.UUID) -> None:
    with session_scope() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.org_id != org_id:
            raise ValueError("Job not found")
        if job.status not in {JobStatus.FAILED, JobStatus.RETRYING, JobStatus.CANCELLED}:
            raise ValueError(f"Job in status {job.status.value} cannot be retried")
        job.status = JobStatus.QUEUED
        job.error = None
        job.finished_at = None
    if settings.celery_enabled:
        from app.workers.celery_app import celery_app

        celery_app.send_task("resolve.run_job", args=[str(job_id)])
    elif settings.ENV == "test" or settings.TASK_RUNNER == "inline":
        run_job(job_id)
    else:
        _get_executor().submit(run_job, job_id)


def _mark_failed(job_id: uuid.UUID, error: str) -> None:
    with session_scope() as db:
        job = db.get(BackgroundJob, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = error[:4000]
            job.finished_at = utcnow()


def purge_old_jobs(days: int = 30) -> int:
    cutoff = utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.created_at < cutoff,
                BackgroundJob.status.in_([JobStatus.SUCCEEDED, JobStatus.FAILED]),
            )
        ).all()
        for row in rows:
            db.delete(row)
        db.commit()
        return len(rows)
