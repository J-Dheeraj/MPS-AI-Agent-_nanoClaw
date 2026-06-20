"""
Generation job tracking for idempotency and restart recovery (V-H8).

Public API
----------
create_job(db, letter_id, idempotency_key) -> GenerationJob
  Creates a job in 'pending' state. If a job with the same idempotency_key
  already exists, returns the existing job (idempotent POST behaviour).

mark_running(db, job) -> None
mark_completed(db, job) -> None
mark_failed(db, job, error) -> None
cancel_job(db, job) -> None

recover_stale_jobs(db, stale_minutes) -> int
  Resets 'running' jobs older than stale_minutes back to 'pending'.
  Call on server startup.
"""

import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from ..database import GenerationJob

# C3: a running job's lease; the reaper re-queues jobs past this deadline.
LEASE_SECONDS = int(os.getenv('GENERATION_LEASE_SECONDS', '180'))
MAX_RETRIES = int(os.getenv('GENERATION_MAX_RETRIES', '3'))


def _now():
    return datetime.now(timezone.utc)


def create_job(db: Session, letter_id: str,
               idempotency_key: str | None = None) -> tuple["GenerationJob", bool]:
    """Create or return an existing job. Returns (job, created)."""
    if idempotency_key:
        existing = (
            db.query(GenerationJob)
            .filter(GenerationJob.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return existing, False
    job = GenerationJob(
        letter_id=letter_id,
        idempotency_key=idempotency_key,
        status="pending",
        created_at=_now(),
    )
    db.add(job)
    db.commit()
    return job, True


def mark_running(db: Session, job: "GenerationJob") -> None:
    job.status = "running"
    job.started_at = _now()
    job.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
    db.commit()


def mark_completed(db: Session, job: "GenerationJob") -> None:
    job.status = "completed"
    job.finished_at = _now()
    job.lease_expires_at = None
    db.commit()


def mark_failed(db: Session, job: "GenerationJob", error: str) -> None:
    job.status = "failed"
    job.finished_at = _now()
    job.error = str(error)[:2000]
    db.commit()


def cancel_job(db: Session, job: "GenerationJob") -> None:
    if job.status in ("pending", "running"):
        job.status = "cancelled"
        job.finished_at = _now()
        db.commit()


def recover_stale_jobs(db: Session, stale_minutes: int = 15) -> int:
    """Reset running jobs that started more than stale_minutes ago.
    Call on server startup to recover from a previous crash."""
    cutoff = _now() - timedelta(minutes=stale_minutes)
    stale = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.status == "running",
            GenerationJob.started_at < cutoff,
        )
        .all()
    )
    for job in stale:
        job.status = "pending"
        job.started_at = None
        job.error = "reset: server restarted while job was running"
    if stale:
        db.commit()
    return len(stale)


def reap_expired_jobs(db: Session, max_retries: int = MAX_RETRIES) -> int:
    """Re-queue running jobs whose lease has expired (crash or hang). Jobs that
    have already been retried max_retries times are marked failed instead, so a
    permanently failing job cannot loop forever. Returns the number acted on.

    This is the durable-execution piece (C3): recovery is no longer a one-shot
    startup reset but a continuous lease reaper. A reconnecting client re-leases
    a re-queued job via the same idempotency key."""
    now = _now()
    expired = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.status == "running",
            GenerationJob.lease_expires_at.isnot(None),
            GenerationJob.lease_expires_at < now,
        )
        .all()
    )
    for job in expired:
        job.retry_count = (job.retry_count or 0) + 1
        job.started_at = None
        job.lease_expires_at = None
        if job.retry_count > max_retries:
            job.status = "failed"
            job.finished_at = now
            job.last_error = f"lease expired and exceeded {max_retries} retries"
            job.error = job.last_error
        else:
            job.status = "pending"
            job.last_error = "lease expired; re-queued for retry"
    if expired:
        db.commit()
    return len(expired)
