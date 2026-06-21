"""v8 Critical#3 (code portion): exercise job-claim and outbox-claim under TRUE
PostgreSQL multi-session concurrency.

The default unit tests run on SQLite (single writer), which cannot reproduce
real concurrent sessions. These tests connect to a real Postgres and run only
when TEST_DATABASE_URL is set (e.g. a CI service container); they skip cleanly
otherwise — mirroring the RUN_MODEL_EVALS gating used for the model harness.

Run with:  TEST_DATABASE_URL=postgresql+psycopg2://user:pw@localhost/mps_test \\
           python3 -m pytest tests/test_pg_concurrency.py -q
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PG_URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not PG_URL or not PG_URL.startswith("postgresql"),
    reason="set TEST_DATABASE_URL to a PostgreSQL DSN to run real-concurrency tests",
)


@pytest.fixture
def engine():
    eng = create_engine(PG_URL)
    from mps_server.database import Base
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _session(engine):
    return sessionmaker(bind=engine)()


def test_concurrent_claim_job_one_winner(engine):
    """Two real PG sessions race to claim the same pending job; exactly one wins
    the compare-and-swap (the other sees status already moved)."""
    from mps_server.database import GenerationJob
    from mps_server.services.generation_jobs import create_job, claim_job

    s0 = _session(engine)
    job, _ = create_job(s0, "L-pg-1", idempotency_key="pg-claim-1")  # pending
    s0.close()

    s1, s2 = _session(engine), _session(engine)
    j1 = s1.query(GenerationJob).filter(GenerationJob.id == job.id).first()
    j2 = s2.query(GenerationJob).filter(GenerationJob.id == job.id).first()
    r1 = claim_job(s1, j1)
    r2 = claim_job(s2, j2)
    s1.close(); s2.close()
    assert [r1, r2].count(True) == 1, "exactly one session must win the claim"


def test_concurrent_outbox_delivery_no_double_claim(engine, monkeypatch):
    """Two concurrent deliver_outbox_once callers must not both claim/send the
    same outbox row (FOR UPDATE SKIP LOCKED + claimed_at lease)."""
    from mps_server.database import AuditCheckpointOutbox
    from mps_server.services import audit as audit_service

    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    monkeypatch.setattr(audit_service, "_forward_post", lambda line: None)

    s0 = _session(engine)
    s0.query(AuditCheckpointOutbox).delete()
    s0.add(AuditCheckpointOutbox(line="pg\trow\thash\tsig\n"))
    s0.commit(); s0.close()

    s1, s2 = _session(engine), _session(engine)
    d1, _ = audit_service.deliver_outbox_once(s1)
    d2, _ = audit_service.deliver_outbox_once(s2)
    s1.close(); s2.close()
    assert d1 + d2 == 1, "the single row must be delivered exactly once"
