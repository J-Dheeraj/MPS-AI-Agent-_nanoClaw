"""C4: durable generation worker — claim + execute pending jobs with no client.

Proves the executor finishes a pending job (e.g. one re-queued by the reaper
after a disconnect) to a persisted, completed draft, and that claim_pending_job
atomically leases the oldest pending job.
"""
import asyncio
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.database import Base, Case, Letter, GenerationJob
from mps_server.services import generation_executor
from mps_server.services.generation_jobs import create_job, claim_pending_job


@pytest.fixture
def db(tmp_path, monkeypatch):
    # keep the audit checkpoint write off the repo data dir during tests
    monkeypatch.setenv("AUDIT_CHECKPOINT_FILE", str(tmp_path / "ckpt.log"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _seed_case_letter(db):
    case = Case(id="c1", session_id="s1", resident_id="r1", case_type="appeal",
                agency="HDB", notes="Resident needs a rental review.",
                status="drafting", is_new_issue=True)
    letter = Letter(id="l1", case_id="c1", status="draft", version=1)
    db.add_all([case, letter])
    db.commit()
    return case, letter


def test_claim_pending_job_leases_oldest(db):
    j1, _ = create_job(db, letter_id="l1", idempotency_key="k1")
    j2, _ = create_job(db, letter_id="l2", idempotency_key="k2")
    claimed = claim_pending_job(db)
    assert claimed.id == j1.id
    assert claimed.status == "running"
    assert claimed.lease_expires_at is not None
    # second claim takes the next pending; third finds nothing
    assert claim_pending_job(db).id == j2.id
    assert claim_pending_job(db) is None


def test_worker_executes_pending_job_to_completion(db, monkeypatch):
    _seed_case_letter(db)
    job, _ = create_job(db, letter_id="l1", idempotency_key="letter-l1-v1")

    async def _fake_run(messages, priority=None):
        # a clean letter that passes the validator (no full NRIC, no figures)
        for chunk in ["Dear Sir,\n\n",
                      "We write to request a review of the resident's case.\n\n",
                      "Yours faithfully,\nThe Volunteer"]:
            yield chunk

    monkeypatch.setattr(generation_executor.llm_queue, "run", _fake_run)
    monkeypatch.setattr(generation_executor, "load_policy_context",
                        lambda agency, case_text="": ("", [], "test-v1"))

    # claim as the worker would, then execute with no actor (system)
    claimed = claim_pending_job(db)
    assert claimed.id == job.id
    result = asyncio.run(generation_executor.execute_job(db, claimed))

    assert result["status"] == "completed"
    db.refresh(job)
    assert job.status == "completed"
    letter = db.query(Letter).filter(Letter.id == "l1").first()
    assert letter.draft_content and "request a review" in letter.draft_content
    case = db.query(Case).filter(Case.id == "c1").first()
    assert case.status == "drafted"


def test_worker_marks_blocked_job_failed(db, monkeypatch):
    _seed_case_letter(db)
    job, _ = create_job(db, letter_id="l1", idempotency_key="letter-l1-v1")

    async def _leaky_run(messages, priority=None):
        # full NRIC -> validator block -> job must fail, draft not persisted
        yield "Dear Sir, resident S1234567A requests review."

    monkeypatch.setattr(generation_executor.llm_queue, "run", _leaky_run)
    monkeypatch.setattr(generation_executor, "load_policy_context",
                        lambda agency, case_text="": ("", [], "test-v1"))

    claimed = claim_pending_job(db)
    result = asyncio.run(generation_executor.execute_job(db, claimed))

    assert result["status"] == "blocked"
    db.refresh(job)
    assert job.status == "failed"
    letter = db.query(Letter).filter(Letter.id == "l1").first()
    assert letter.draft_content is None
