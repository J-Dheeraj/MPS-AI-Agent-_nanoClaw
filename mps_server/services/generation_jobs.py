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

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from ..database import GenerationJob


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
    db.commit()


def mark_completed(db: Session, job: "GenerationJob") -> None:
    job.status = "completed"
    job.finished_at = _now()
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
