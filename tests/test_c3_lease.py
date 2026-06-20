"""C3: generation job lease + reaper durability."""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.database import Base, GenerationJob
from mps_server.services.generation_jobs import (
    create_job, mark_running, mark_completed, reap_expired_jobs,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_running_job_gets_lease(db):
    job, _ = create_job(db, letter_id="L1")
    mark_running(db, job)
    assert job.lease_expires_at is not None


def test_expired_lease_requeues(db):
    job, _ = create_job(db, letter_id="L2")
    mark_running(db, job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert reap_expired_jobs(db) == 1
    db.refresh(job)
    assert job.status == "pending"
    assert job.retry_count == 1
    assert job.started_at is None


def test_fresh_lease_not_reaped(db):
    job, _ = create_job(db, letter_id="L3")
    mark_running(db, job)  # lease is in the future
    assert reap_expired_jobs(db) == 0
    db.refresh(job)
    assert job.status == "running"


def test_retry_cap_marks_failed(db):
    job, _ = create_job(db, letter_id="L4")
    mark_running(db, job)
    job.retry_count = 3  # already at MAX_RETRIES
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert reap_expired_jobs(db, max_retries=3) == 1
    db.refresh(job)
    assert job.status == "failed"
    assert "exceeded" in (job.last_error or "")


def test_completed_job_clears_lease(db):
    job, _ = create_job(db, letter_id="L5")
    mark_running(db, job)
    mark_completed(db, job)
    assert job.lease_expires_at is None
    assert reap_expired_jobs(db) == 0
