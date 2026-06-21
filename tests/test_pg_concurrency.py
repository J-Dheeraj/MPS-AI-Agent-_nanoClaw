"""v9 Critical#1 (code): exercise job-claim and outbox-delivery under TRUE
PostgreSQL multi-session concurrency.

SQLite (single writer) cannot reproduce real concurrent sessions or enforce
foreign keys, so these tests connect to a real Postgres and run only when
TEST_DATABASE_URL is set; they skip cleanly otherwise. The CI `pg-concurrency`
job provisions a postgres:16 service and fails the build if this suite skips.

Two threads synchronised by a barrier genuinely contend for the same row, and
the schema is built by running the real Alembic migration chain (not
create_all), so the production migrations are exercised on Postgres.

Run with:  TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/mps_test \\
           python3 -m pytest tests/test_pg_concurrency.py -q
"""
import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PG_URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not PG_URL.startswith("postgresql"),
    reason="set TEST_DATABASE_URL to a PostgreSQL DSN to run real-concurrency tests",
)


@pytest.fixture
def engine():
    # Build the schema via the real Alembic chain against the test database,
    # so CI exercises the production migrations on Postgres (not create_all).
    os.environ["DATABASE_URL"] = PG_URL
    from alembic.config import Config
    from alembic import command
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo_root, "migrations"))
    command.upgrade(cfg, "head")

    eng = create_engine(PG_URL)
    # clean slate between tests (FK-safe order)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE audit_checkpoint_outbox, generation_jobs, "
                          "letters, cases, residents, sessions "
                          "RESTART IDENTITY CASCADE"))
    yield eng
    eng.dispose()


def _Session(engine):
    return sessionmaker(bind=engine)()


def _seed_case_letter(engine):
    # Postgres enforces every FK SQLite ignored: Case -> Session + Resident.
    from mps_server.database import Session as SessionRow, Resident, Case, Letter
    s = _Session(engine)
    s.add(SessionRow(id="s1", date="2026-06-21", status="open"))
    s.add(Resident(id="r1", name="Test Resident", nric_masked="S****567A"))
    s.flush()
    s.add(Case(id="c1", session_id="s1", resident_id="r1", case_type="appeal",
               agency="HDB", notes="x", status="drafting", is_new_issue=True))
    s.add(Letter(id="l1", case_id="c1", status="draft", version=1))
    s.commit(); s.close()


def test_concurrent_claim_job_one_winner(engine):
    """Two real PG sessions hit claim_job on the same pending job simultaneously
    (barrier); the conditional UPDATE lets exactly one win."""
    from mps_server.database import GenerationJob
    from mps_server.services.generation_jobs import create_job, claim_job

    _seed_case_letter(engine)
    s0 = _Session(engine)
    job, _ = create_job(s0, "l1", idempotency_key="pg-claim-1")  # FK-valid, pending
    job_id = job.id
    s0.close()

    barrier = threading.Barrier(2)
    results = {}

    def worker(idx):
        s = _Session(engine)
        j = s.query(GenerationJob).filter(GenerationJob.id == job_id).first()
        barrier.wait()
        results[idx] = claim_job(s, j)
        s.close()

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert list(results.values()).count(True) == 1, "exactly one session wins"


def test_concurrent_outbox_delivery_no_double_send(engine, monkeypatch):
    """Two concurrent deliver_outbox_once callers must deliver the single row
    exactly once (FOR UPDATE SKIP LOCKED + claim token)."""
    from mps_server.database import AuditCheckpointOutbox
    from mps_server.services import audit as audit_service

    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    monkeypatch.setattr(audit_service, "_forward_post", lambda line: None)

    s0 = _Session(engine)
    s0.add(AuditCheckpointOutbox(line="pg\\trow\\thash\\tsig\\n"))
    s0.commit(); s0.close()

    barrier = threading.Barrier(2)
    results = {}

    def worker(idx):
        s = _Session(engine)
        barrier.wait()
        d, _f = audit_service.deliver_outbox_once(s)
        results[idx] = d
        s.close()

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert sum(results.values()) == 1, "the row is delivered exactly once"
