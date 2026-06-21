"""C1 (v7): atomic job ownership — the interactive WS path and the background
worker can never execute the same generation job."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.database import Base, GenerationJob
from mps_server.services.generation_jobs import (
    create_job, claim_job, claim_pending_job,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_claim_job_is_exclusive(db):
    job, created = create_job(db, "L1", idempotency_key="k1")  # pending
    assert created and job.status == "pending"
    # two claimers race; exactly one wins the compare-and-swap
    first = claim_job(db, job)
    second = claim_job(db, job)
    assert first is True
    assert second is False
    db.refresh(job)
    assert job.status == "running"


def test_interactive_claimed_job_invisible_to_worker(db):
    # claim=True -> born running with a lease, no pending window
    job, created = create_job(db, "L2", idempotency_key="letter-L2-v1", claim=True)
    assert created and job.status == "running"
    assert job.lease_expires_at is not None
    # the worker only claims pending jobs; this one must not be claimable
    assert claim_pending_job(db) is None


def test_claim_pending_job_uses_cas(db):
    job, _ = create_job(db, "L3", idempotency_key="k3")  # pending (reaper-style)
    claimed = claim_pending_job(db)
    assert claimed is not None and claimed.id == job.id
    assert claimed.status == "running"
    # nothing left pending
    assert claim_pending_job(db) is None
