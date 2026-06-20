"""I1: concurrency / idempotency-race tests for generation jobs."""
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.database import Base, GenerationJob
from mps_server.services.generation_jobs import create_job


def _engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    return e


def test_duplicate_insert_race_yields_one_job():
    """Simulate the race: a job with the key already exists (committed by the
    'winner'); a second create_job with the same key must not duplicate."""
    engine = _engine()
    Session = sessionmaker(bind=engine)
    s1 = Session()
    job_a, created_a = create_job(s1, letter_id="L1", idempotency_key="dup-key")
    assert created_a is True

    # Second caller, separate session, same key -> returns the existing job.
    s2 = Session()
    job_b, created_b = create_job(s2, letter_id="L1", idempotency_key="dup-key")
    assert created_b is False
    assert job_b.id == job_a.id

    total = Session().query(GenerationJob).filter(
        GenerationJob.idempotency_key == "dup-key").count()
    assert total == 1
    s1.close(); s2.close()


def test_parallel_create_job_threads_one_winner():
    """Two threads creating the same idempotency_key concurrently must leave
    exactly one row; both calls return a job, exactly one marked created."""
    engine = _engine()
    Session = sessionmaker(bind=engine)
    results = []
    barrier = threading.Barrier(2)

    def worker():
        s = Session()
        try:
            barrier.wait()
            job, created = create_job(s, letter_id="L9", idempotency_key="k-par")
            results.append((job.id, created))
        finally:
            s.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()

    assert len(results) == 2
    ids = {r[0] for r in results}
    assert len(ids) == 1                      # same single job row
    assert sum(1 for _, c in results if c) <= 1   # at most one "created"
    total = Session().query(GenerationJob).filter(
        GenerationJob.idempotency_key == "k-par").count()
    assert total == 1
