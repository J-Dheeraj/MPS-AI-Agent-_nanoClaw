"""v6 Important #1: durable audit checkpoint forwarding outbox.

Replaces fire-and-forget forwarding with an outbox + delivery worker. Tests
cover enqueue-on-write, successful delivery, failure recording, backlog
reporting, and the production startup guard.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.database import Base, AuditCheckpointOutbox
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


def test_log_event_enqueues_to_outbox_when_url_set(db, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    audit_service.log_event(db, "test_event", user_id="u1", role="admin")
    rows = db.query(AuditCheckpointOutbox).all()
    assert len(rows) == 1
    assert rows[0].delivered_at is None
    assert rows[0].line.strip()


def test_no_outbox_row_without_url(db, monkeypatch):
    monkeypatch.delenv("AUDIT_CHECKPOINT_FORWARD_URL", raising=False)
    audit_service.log_event(db, "test_event", user_id="u1", role="admin")
    assert db.query(AuditCheckpointOutbox).count() == 0


def test_delivery_marks_row_delivered(db, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")
    monkeypatch.setattr(audit_service, "_forward_post", lambda line: None)
    db.add(AuditCheckpointOutbox(line="2026\tid\thash\tsig\n"))
    db.commit()
    delivered, failed = audit_service.deliver_outbox_once(db)
    assert (delivered, failed) == (1, 0)
    row = db.query(AuditCheckpointOutbox).first()
    assert row.delivered_at is not None


def test_delivery_failure_increments_attempts(db, monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_FORWARD_URL", "https://sink.internal/audit")

    def _boom(line):
        raise RuntimeError("sink unreachable")

    monkeypatch.setattr(audit_service, "_forward_post", _boom)
    db.add(AuditCheckpointOutbox(line="2026\tid\thash\tsig\n"))
    db.commit()
    delivered, failed = audit_service.deliver_outbox_once(db)
    assert (delivered, failed) == (0, 1)
    row = db.query(AuditCheckpointOutbox).first()
    assert row.delivered_at is None
    assert row.attempts == 1
    assert "unreachable" in (row.last_error or "")
    backlog = audit_service.outbox_backlog(db)
    assert backlog["undelivered"] == 1


def test_production_without_forward_url_aborts(monkeypatch):
    monkeypatch.delenv("AUDIT_CHECKPOINT_FORWARD_URL", raising=False)
    with pytest.raises(RuntimeError, match="AUDIT_CHECKPOINT_FORWARD_URL"):
        audit_service.assert_forward_configured(is_production=True)


def test_dev_without_forward_url_is_fine(monkeypatch):
    monkeypatch.delenv("AUDIT_CHECKPOINT_FORWARD_URL", raising=False)
    audit_service.assert_forward_configured(is_production=False)  # no raise
