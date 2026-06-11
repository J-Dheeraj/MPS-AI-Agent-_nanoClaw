"""
V-M13: Additional test coverage for policy store (expiry/supersession/budget),
       generation jobs (idempotency/recovery), and rate limiter edge cases.
"""
import json
import os
import pathlib
import pytest
from datetime import date, timedelta


# ── Policy store: effective_to, supersession, budget ─────────────────────────

@pytest.fixture
def policy_dir(tmp_path, monkeypatch):
    """Set up a minimal signed (dev-mode) policy directory."""
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    monkeypatch.delenv("POLICY_PUBLIC_KEY", raising=False)
    return tmp_path


def _write_rule(policy_dir, rule_id, agency, effective_date,
                statement, effective_to=None, supersedes=None):
    rule = {
        "schema_version": 1,
        "rule_id": rule_id,
        "agency": agency,
        "statement": statement,
        "source": {
            "title": f"Test Rule {rule_id}",
            "url": "https://www.hdb.gov.sg/test",
            "effective_date": effective_date,
            **({"effective_to": effective_to} if effective_to else {}),
        },
        **({"supersedes": supersedes} if supersedes else {}),
    }
    import hashlib, json as _json
    raw = _json.dumps(rule, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    (policy_dir / f"{rule_id}.json").write_bytes(raw)
    return sha


def _write_manifest(policy_dir, entries):
    from datetime import timezone
    manifest = {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "rules": entries,
    }
    import json as _json
    (policy_dir / "manifest.json").write_text(_json.dumps(manifest))


def test_expired_rule_excluded(policy_dir):
    """A rule with effective_to in the past must be excluded from context."""
    from mps_server.services.policy_store import load_policy_context

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    sha = _write_rule(policy_dir, "R1", "HDB", "2024-01-01",
                      "CPF grant applies.", effective_to=yesterday)
    _write_manifest(policy_dir, [{"file": "R1.json", "sha256": sha}])

    context, sources, _ = load_policy_context("HDB")
    assert "R1" not in context
    assert len(sources) == 0


def test_future_effective_rule_included_before_expiry(policy_dir):
    """A rule with an effective_to in the future must appear in context."""
    from mps_server.services.policy_store import load_policy_context

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    sha = _write_rule(policy_dir, "R2", "HDB", "2024-01-01",
                      "Subsidy threshold $14k.", effective_to=tomorrow)
    _write_manifest(policy_dir, [{"file": "R2.json", "sha256": sha}])

    context, sources, _ = load_policy_context("HDB")
    assert "R2" in context
    assert len(sources) == 1


def test_superseded_rule_excluded(policy_dir):
    """A rule explicitly superseded by another must be excluded."""
    from mps_server.services.policy_store import load_policy_context

    sha1 = _write_rule(policy_dir, "R_OLD", "HDB", "2023-01-01", "Old threshold $10k.")
    sha2 = _write_rule(policy_dir, "R_NEW", "HDB", "2024-01-01",
                       "New threshold $14k.", supersedes=["R_OLD"])
    _write_manifest(policy_dir, [
        {"file": "R_OLD.json", "sha256": sha1},
        {"file": "R_NEW.json", "sha256": sha2},
    ])

    context, sources, _ = load_policy_context("HDB")
    assert "R_OLD" not in context
    assert "R_NEW" in context
    assert len(sources) == 1


def test_token_budget_enforced(policy_dir, monkeypatch):
    """Rules that would exceed the token budget must be dropped."""
    from mps_server.services import policy_store
    from mps_server.services.policy_store import load_policy_context
    monkeypatch.setattr(policy_store, "MAX_CONTEXT_CHARS", 100)

    sha1 = _write_rule(policy_dir, "R1", "HDB", "2025-01-01", "A" * 50)
    sha2 = _write_rule(policy_dir, "R2", "HDB", "2024-01-01", "B" * 50)
    _write_manifest(policy_dir, [
        {"file": "R1.json", "sha256": sha1},
        {"file": "R2.json", "sha256": sha2},
    ])

    context, sources, _ = load_policy_context("HDB")
    # Only one rule should fit within 100 chars budget
    assert len(sources) <= 1


# ── Generation jobs: idempotency and stale recovery ──────────────────────────

@pytest.fixture
def jobs_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from mps_server.database import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_idempotent_job_creation(jobs_db):
    from mps_server.services.generation_jobs import create_job
    job1, created1 = create_job(jobs_db, letter_id="L1", idempotency_key="key1")
    job2, created2 = create_job(jobs_db, letter_id="L1", idempotency_key="key1")
    assert created1 is True
    assert created2 is False
    assert job1.id == job2.id


def test_stale_job_recovery(jobs_db):
    from datetime import datetime, timezone, timedelta
    from mps_server.services.generation_jobs import create_job, mark_running, recover_stale_jobs
    job, _ = create_job(jobs_db, letter_id="L2")
    mark_running(jobs_db, job)
    # Backdate started_at to simulate a crash 20 minutes ago
    job.started_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    jobs_db.commit()

    recovered = recover_stale_jobs(jobs_db, stale_minutes=15)
    assert recovered == 1
    jobs_db.refresh(job)
    assert job.status == "pending"
    assert job.started_at is None


def test_fresh_running_job_not_recovered(jobs_db):
    from mps_server.services.generation_jobs import create_job, mark_running, recover_stale_jobs
    job, _ = create_job(jobs_db, letter_id="L3")
    mark_running(jobs_db, job)
    # started_at is now — not stale
    recovered = recover_stale_jobs(jobs_db, stale_minutes=15)
    assert recovered == 0
    jobs_db.refresh(job)
    assert job.status == "running"


# ── V4-I4: deterministic packing and relevance ranking ───────────────────────

def test_oversized_rule_skipped_not_terminal(policy_dir, monkeypatch):
    """An over-budget rule must be skipped, not end packing: a smaller,
    lower-ranked rule that still fits must be included."""
    from mps_server.services import policy_store
    from mps_server.services.policy_store import load_policy_context
    monkeypatch.setattr(policy_store, "MAX_CONTEXT_CHARS", 200)

    sha1 = _write_rule(policy_dir, "R_BIG", "HDB", "2025-01-01", "A" * 500)
    sha2 = _write_rule(policy_dir, "R_SMALL", "HDB", "2024-01-01", "Small rule.")
    _write_manifest(policy_dir, [
        {"file": "R_BIG.json", "sha256": sha1},
        {"file": "R_SMALL.json", "sha256": sha2},
    ])

    context, sources, _ = load_policy_context("HDB")
    assert [s["rule_id"] for s in sources] == ["R_SMALL"]


def test_case_relevance_outranks_recency(policy_dir, monkeypatch):
    """With case_text supplied, a rule matching the case outranks a newer
    unrelated rule when the budget only fits one."""
    from mps_server.services import policy_store
    from mps_server.services.policy_store import load_policy_context
    monkeypatch.setattr(policy_store, "MAX_CONTEXT_CHARS", 150)

    sha1 = _write_rule(policy_dir, "R_NEW_OTHER", "HDB", "2026-01-01",
                       "Carpark season parking renewal terms.")
    sha2 = _write_rule(policy_dir, "R_OLD_MATCH", "HDB", "2024-01-01",
                       "Public rental subsidy income ceiling rules.")
    _write_manifest(policy_dir, [
        {"file": "R_NEW_OTHER.json", "sha256": sha1},
        {"file": "R_OLD_MATCH.json", "sha256": sha2},
    ])

    _, sources, _ = load_policy_context(
        "HDB", case_text="Resident appealing rejected rental subsidy income assessment")
    assert [s["rule_id"] for s in sources] == ["R_OLD_MATCH"]


def test_no_case_text_keeps_recency_order(policy_dir):
    """Without case_text the existing recency ordering is preserved."""
    from mps_server.services.policy_store import load_policy_context

    sha1 = _write_rule(policy_dir, "R_2026", "HDB", "2026-01-01", "Newer rule.")
    sha2 = _write_rule(policy_dir, "R_2024", "HDB", "2024-01-01", "Older rule.")
    _write_manifest(policy_dir, [
        {"file": "R_2026.json", "sha256": sha1},
        {"file": "R_2024.json", "sha256": sha2},
    ])

    _, sources, _ = load_policy_context("HDB")
    assert [s["rule_id"] for s in sources] == ["R_2026", "R_2024"]
