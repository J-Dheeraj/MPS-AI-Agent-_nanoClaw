"""v7 C2: audit entry and forwarding-outbox row are one atomic transaction, and
delivery sends a sink idempotency key derived from the audit entry hash."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.database import Base, AuditLog, AuditCheckpointOutbox
from mps_server.services import audit as audit_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FILE", str(tmp_path / "ckpt.log"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_audit_and_outbox_commit_atomically(db, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    audit_service.log_event(db, "evt", user_id="u1", role="admin")
    # both rows exist after the single commit
    assert db.query(AuditLog).count() == 1
    assert db.query(AuditCheckpointOutbox).count() == 1
    # the outbox line carries the same entry hash as the audit row
    entry = db.query(AuditLog).first()
    row = db.query(AuditCheckpointOutbox).first()
    assert entry.entry_hash in row.line


def test_rollback_leaves_neither_row(db, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    # simulate a crash before commit by rolling back inside the same session:
    # add entry + outbox via log_event internals up to commit, then rollback.
    from mps_server.database import compute_audit_hash
    import uuid, datetime
    entry = AuditLog(id=str(uuid.uuid4()),
                     timestamp=datetime.datetime.now(datetime.timezone.utc),
                     event_type="evt", hash_version=2)
    entry.entry_hash = compute_audit_hash(entry)
    db.add(entry)
    db.add(AuditCheckpointOutbox(line=audit_service._checkpoint_line(entry)))
    db.rollback()  # crash window: nothing committed
    assert db.query(AuditLog).count() == 0
    assert db.query(AuditCheckpointOutbox).count() == 0


def test_delivery_sends_idempotency_key(db, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def _fake_post(url, **kwargs):
        seen.update(kwargs.get("headers", {}))
        return _Resp()

    # _forward_post does a lazy import then httpx.post(...); patch the global.
    import httpx
    monkeypatch.setattr(httpx, "post", _fake_post)

    db.add(AuditCheckpointOutbox(line="2026-06-21T00:00:00\tid-1\tHASHVALUE123\tsig\n"))
    db.commit()
    delivered, failed = audit_service.deliver_outbox_once(db)
    assert (delivered, failed) == (1, 0)
    assert seen.get("Idempotency-Key") == "HASHVALUE123"
