"""Verify real Celery dispatch through Redis with a running worker.

Usage (from apps/api, worker already running):

    set DATABASE_URL=postgresql+psycopg://resolve@127.0.0.1:55432/resolve_e2e
    set CELERY_BROKER_URL=redis://127.0.0.1:6379/0
    set TASK_RUNNER=celery
    python scripts/verify_celery.py
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.domain.enums import InvestigationStatus, JobStatus  # noqa: E402
from app.models.ai import Investigation  # noqa: E402
from app.models.automation import BackgroundJob  # noqa: E402
from app.models.cases import Case  # noqa: E402
from app.models.identity import Organization  # noqa: E402
from app.modules.investigation.service import create_investigation  # noqa: E402
from app.workers.dispatch import dispatch_job  # noqa: E402


def wait_for_job(job_id: uuid.UUID, timeout: float = 120.0) -> BackgroundJob:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                db.expunge(job)
            if job and job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                return job
        time.sleep(1)
    raise TimeoutError(f"job {job_id} did not finish within {timeout}s")


def main() -> int:
    print(f"task_runner={settings.TASK_RUNNER} celery_enabled={settings.celery_enabled}")
    if not settings.celery_enabled:
        print("Celery is not enabled; set TASK_RUNNER=celery and CELERY_BROKER_URL.")
        return 1

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == "northwind"))
        if org is None:
            print("Seeded organization 'northwind' not found.")
            return 1
        org_id = org.id

    job_id = dispatch_job("deliver_pending_notifications", {}, org_id)
    print(f"dispatched deliver_pending_notifications job={job_id}")
    job = wait_for_job(job_id)
    print(f"  result: status={job.status.value} attempts={job.attempts} error={job.error}")
    if job.status != JobStatus.SUCCEEDED:
        return 1

    with SessionLocal() as db:
        case = db.scalar(
            select(Case)
            .where(Case.org_id == org_id, Case.status.in_(["OPEN", "INVESTIGATING"]))
            .order_by(Case.created_at.desc())
            .limit(1)
        )
        if case is None:
            print("No case available for the investigation test.")
            return 1
        case_id = case.id
        investigation = create_investigation(db, case=case, actor_id=None)
        investigation_id = investigation.id
        db.commit()
    print(f"queued investigation {investigation_id} for case {case_id}")

    deadline = time.time() + 180
    status = None
    while time.time() < deadline:
        with SessionLocal() as db:
            investigation = db.get(Investigation, investigation_id)
            status = investigation.status.value if investigation else None
            error = investigation.error if investigation else None
            if investigation and investigation.status in {
                InvestigationStatus.COMPLETED,
                InvestigationStatus.FAILED,
            }:
                break
        time.sleep(2)
    print(f"  investigation status={status} error={error}")
    if status != "COMPLETED":
        return 1

    with SessionLocal() as db:
        jobs = (
            db.scalars(
                select(BackgroundJob)
                .where(BackgroundJob.task_name == "run_investigation")
                .order_by(BackgroundJob.created_at.desc())
                .limit(1)
            ).all()
        )
        print(f"  worker job status={jobs[0].status.value if jobs else None}")
    print("CELERY VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
