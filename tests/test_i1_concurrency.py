"""I1: concurrency / idempotency-race tests for generation jobs."""
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

def test_forced_insert_race_recovers(monkeypatch):
    """Deterministically force the race: make the pre-check miss an existing
    row so create_job attempts a duplicate insert and must recover via the
    IntegrityError path (no threads, no timing)."""
    engine = _engine()
    Session = sessionmaker(bind=engine)
    s = Session()
    winner, _ = create_job(s, letter_id="L9", idempotency_key="k-race")

    import mps_server.services.generation_jobs as gj

    class _BlindFirst:
        def filter(self, *a, **k): return self
        def first(self): return None  # pretend the row does not exist yet

    s2 = Session()
    real_query = s2.query
    state = {"blinded": False}

    def fake_query(model):
        # Blind only the pre-check (first call); recovery re-query is real.
        if model is gj.GenerationJob and not state["blinded"]:
            state["blinded"] = True
            return _BlindFirst()
        return real_query(model)

    monkeypatch.setattr(s2, "query", fake_query)
    job, created = create_job(s2, letter_id="L9", idempotency_key="k-race")
    # Pre-check was blinded, insert hit the unique constraint, recovery path ran.
    # Recovery re-queries with the real session query (restored after rollback).
    assert created is False
    assert job.id == winner.id
    assert Session().query(GenerationJob).filter(
        GenerationJob.idempotency_key == "k-race").count() == 1
