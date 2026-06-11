"""Retention sweep and data-subject erasure (V-C3)."""

from datetime import datetime, timedelta, timezone

import pytest

from mps_server.database import Base, Case, Letter, Resident, Session
from mps_server import retention


@pytest.fixture
def db(tmp_path, monkeypatch):
    # Isolated SQLite DB per test.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'ret.db'}")
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine)
    session = Local()
    monkeypatch.setattr(retention, "SessionLocal", Local)
    yield session
    session.close()


def _seed(db, *, sent_days_ago):
    sent_at = datetime.now(timezone.utc) - timedelta(days=sent_days_ago)
    sess = Session(id="s1", date="2025-01-01", status="sent", sent_at=sent_at)
    res = Resident(id="r1", name="Jane Tan", nric_masked="S****567A", contact="91234567")
    case = Case(id="c1", session_id="s1", resident_id="r1", case_type="appeal",
                agency="HDB", notes="Resident is a widow facing rental arrears.")
    letter = Letter(id="l1", case_id="c1", draft_content="Dear Sir, re: Jane Tan ...",
                    final_content="Final letter naming Jane Tan.")
    db.add_all([sess, res, case, letter])
    db.commit()


def test_sweep_purges_old_residents(db):
    _seed(db, sent_days_ago=400)
    result = retention.sweep(db, retention_days=365)
    assert result["purged_count"] == 1
    res = db.query(Resident).filter(Resident.id == "r1").first()
    assert res.name == retention.TOMBSTONE
    assert res.nric_masked == retention.TOMBSTONE
    assert res.contact is None
    case = db.query(Case).filter(Case.id == "c1").first()
    assert case.notes == retention.TOMBSTONE
    assert case.agency == "HDB"  # structural field retained
    letter = db.query(Letter).filter(Letter.id == "l1").first()
    assert letter.draft_content == retention.TOMBSTONE
    assert letter.final_content == retention.TOMBSTONE


def test_sweep_keeps_recent_residents(db):
    _seed(db, sent_days_ago=10)
    result = retention.sweep(db, retention_days=365)
    assert result["purged_count"] == 0
    assert result["skipped"] == 1
    res = db.query(Resident).filter(Resident.id == "r1").first()
    assert res.name == "Jane Tan"


def test_dry_run_changes_nothing(db):
    _seed(db, sent_days_ago=400)
    result = retention.sweep(db, retention_days=365, dry_run=True)
    assert result["purged_count"] == 1
    res = db.query(Resident).filter(Resident.id == "r1").first()
    assert res.name == "Jane Tan"  # untouched


def test_delete_resident_erases_on_request(db):
    _seed(db, sent_days_ago=1)  # recent, but erasure ignores the window
    result = retention.delete_resident(db, "r1")
    assert result["deleted"] is True
    res = db.query(Resident).filter(Resident.id == "r1").first()
    assert res.name == retention.TOMBSTONE
    letter = db.query(Letter).filter(Letter.id == "l1").first()
    assert letter.final_content == retention.TOMBSTONE


def test_delete_missing_resident(db):
    result = retention.delete_resident(db, "nope")
    assert result["deleted"] is False
