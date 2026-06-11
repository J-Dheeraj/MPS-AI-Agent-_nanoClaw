"""V4 critical-finding regression tests: job wiring (C1) and audit-chain
content verification (C3)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mps_server.auth import create_token
from mps_server.database import (
    Base, Case, GenerationJob, Resident, Session, User, get_db,
)
from mps_server.routers import letters_router
from mps_server.routers.letters_router import router


def build_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id="vol-1", username="vol-1", hashed_pw="x", role="volunteer",
             full_name="Vol", is_active=True),
        Session(id="s1", date="2026-06-12", status="open"),
        Resident(id="r1", name="Resident", nric_masked="S****567A"),
        Case(id="case-1", session_id="s1", resident_id="r1",
             case_type="appeal", agency="HDB", status="assigned",
             volunteer_id="vol-1", notes="A housing appeal."),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(router)
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), db


GOOD_LETTER = (
    "Dear Sir/Madam, I write on behalf of my resident to request a review "
    "of the housing decision. The resident faces genuine hardship. We would "
    "be grateful for your kind consideration. Yours faithfully, MP."
)


class FakeQueue:
    def depth(self):
        return 0

    async def run(self, messages, priority=None):
        yield GOOD_LETTER


def test_ws_draft_creates_and_completes_generation_job(monkeypatch):
    """V4-C1: a live generation run must leave a completed job row."""
    client, db = build_app()
    monkeypatch.setattr(letters_router, "llm_queue", FakeQueue())
    monkeypatch.setattr(letters_router, "load_policy_context",
                        lambda agency, **kw: ("", [], None))
    token = create_token({"sub": "vol-1", "role": "volunteer"})
    with client.websocket_connect("/letters/ws/draft") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "authenticated"
        ws.send_json({"case_id": "case-1", "is_reappeal": False})
        msg = ws.receive_json()
        while msg["type"] in ("queue", "chunk"):
            msg = ws.receive_json()
        assert msg["type"] == "done"
    jobs = db.query(GenerationJob).all()
    assert len(jobs) == 1
    assert jobs[0].status == "completed"
    assert jobs[0].idempotency_key.startswith("letter-")


def test_ws_draft_blocked_output_marks_job_failed(monkeypatch):
    """V4-C1: validator-blocked output leaves a failed job row."""
    client, db = build_app()

    class BadQueue(FakeQueue):
        async def run(self, messages, priority=None):
            yield "Resident S1234567A must be helped immediately."

    monkeypatch.setattr(letters_router, "llm_queue", BadQueue())
    monkeypatch.setattr(letters_router, "load_policy_context",
                        lambda agency, **kw: ("", [], None))
    token = create_token({"sub": "vol-1", "role": "volunteer"})
    with client.websocket_connect("/letters/ws/draft") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "authenticated"
        ws.send_json({"case_id": "case-1", "is_reappeal": False})
        msg = ws.receive_json()
        while msg["type"] == "queue":
            msg = ws.receive_json()
        assert msg["type"] == "error"
    jobs = db.query(GenerationJob).all()
    assert len(jobs) == 1
    assert jobs[0].status == "failed"


# ── V4-C3: audit content-hash and checkpoint verification ────────────────────

def _audit_app(tmp_path, monkeypatch):
    import os
    from fastapi.testclient import TestClient as TC
    monkeypatch.setenv("METRICS_TOKEN", "test-metrics-token")
    monkeypatch.setenv("AUDIT_CHECKPOINT_FILE", str(tmp_path / "cp.log"))
    from mps_server import main as main_mod
    from mps_server.database import Base as B
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    B.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def override_db():
        yield db

    main_mod.app.dependency_overrides[main_mod.get_db] = override_db
    return TC(main_mod.app, base_url="http://localhost"), db


def test_audit_chain_detects_content_tampering(tmp_path, monkeypatch):
    """V4-C3: editing entry fields while keeping the stored chain intact
    must be detected by content-hash recomputation."""
    from sqlalchemy import text
    from mps_server.services.audit import log_event
    client, db = _audit_app(tmp_path, monkeypatch)
    log_event(db, "test_event", user_id="u1")
    log_event(db, "test_event_2", user_id="u1")
    # Tamper with a field via raw SQL (bypassing the ORM immutability guard)
    # without recomputing the stored hash.
    db.execute(text("UPDATE audit_log SET event_type='forged'"))
    db.commit()
    r = client.get("/health/audit-chain",
                   headers={"Authorization": "Bearer test-metrics-token"})
    assert r.status_code == 500
    assert "modified" in r.json()["detail"]


def test_audit_chain_verifies_head_against_checkpoint(tmp_path, monkeypatch):
    """V4-C3: an intact chain whose head is anchored in the checkpoint file
    reports head_anchored."""
    from mps_server.services.audit import log_event
    client, db = _audit_app(tmp_path, monkeypatch)
    log_event(db, "test_event", user_id="u1")
    r = client.get("/health/audit-chain",
                   headers={"Authorization": "Bearer test-metrics-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["checkpoint"] == "head_anchored"
    assert body["checkpoint_write_failures"] == 0
