"""
MPS Server - Database models and connection
SQLite for dev, swap DATABASE_URL for PostgreSQL in production
"""
import hashlib, json, uuid
from urllib.parse import quote_plus
from datetime import datetime, timezone
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

import os as _os
import pathlib as _pathlib
from .config import read_secret
# DB lives next to this file (mps_server/mps.db) regardless of the cwd the
# server was launched from. Override with DATABASE_URL for PostgreSQL etc.
_default_db = _pathlib.Path(__file__).parent / "mps.db"


def _database_url() -> str:
    configured = _os.environ.get("DATABASE_URL")
    if configured:
        return configured
    host = _os.environ.get("DB_HOST")
    if not host:
        return f"sqlite:///{_default_db}"
    user = _os.environ.get("DB_USER", "mps")
    database = _os.environ.get("DB_NAME", "mps")
    port = _os.environ.get("DB_PORT", "5432")
    password = read_secret("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD or DB_PASSWORD_FILE is required with DB_HOST")
    return (
        "postgresql+psycopg://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"
    )


DATABASE_URL = _database_url()
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username      = Column(String, unique=True, nullable=False, index=True)
    hashed_pw     = Column(String, nullable=False)
    role          = Column(String, nullable=False)
    full_name     = Column(String, nullable=False)
    totp_secret          = Column(String, nullable=True)
    pending_totp_secret  = Column(String, nullable=True)
    mfa_enabled          = Column(Boolean, default=False)
    recovery_codes       = Column(Text, nullable=True)   # JSON list of bcrypt hashes
    is_active     = Column(Boolean, default=True)
    failed_logins = Column(Integer, default=0)
    locked_until  = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Session(Base):
    __tablename__ = "sessions"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    date            = Column(String, nullable=False)
    status          = Column(String, default="open")
    opened_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at       = Column(DateTime, nullable=True)
    mp_approved_at  = Column(DateTime, nullable=True)
    sent_at         = Column(DateTime, nullable=True)
    total_cases     = Column(Integer, default=0)
    completed_cases = Column(Integer, default=0)
    carried_over    = Column(Integer, default=0)
    opened_by       = Column(String, ForeignKey("users.id"), nullable=True)
    cases = relationship("Case", back_populates="session")

class Resident(Base):
    __tablename__ = "residents"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = Column(String, nullable=False)
    nric_masked = Column(String, nullable=False)
    contact     = Column(String, nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    cases = relationship("Case", back_populates="resident")

class Case(Base):
    __tablename__ = "cases"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id     = Column(String, ForeignKey("sessions.id"), nullable=False)
    resident_id    = Column(String, ForeignKey("residents.id"), nullable=False)
    case_type      = Column(String, nullable=False)
    agency         = Column(String, nullable=False)
    status         = Column(String, default="assigned")
    parent_case_id = Column(String, ForeignKey("cases.id"), nullable=True)
    is_new_issue   = Column(Boolean, default=True)
    urgency        = Column(String, default="normal")
    notes          = Column(Text, nullable=True)   # volunteer's case notes (never full NRIC)
    volunteer_id   = Column(String, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    session  = relationship("Session", back_populates="cases")
    resident = relationship("Resident", back_populates="cases")
    letters  = relationship("Letter", back_populates="case")
    parent   = relationship("Case", remote_side="Case.id")

class Letter(Base):
    __tablename__ = "letters"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id        = Column(String, ForeignKey("cases.id"), nullable=False)
    draft_content  = Column(Text, nullable=True)
    final_content  = Column(Text, nullable=True)
    version        = Column(Integer, default=1)
    status         = Column(String, default="draft")
    vetter_comment = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    vetted_at      = Column(DateTime, nullable=True)
    approved_at    = Column(DateTime, nullable=True)
    is_frozen      = Column(Boolean, default=False)
    # Generation provenance (JSON): model, prompt_version, policy_version,
    # validator_version, policy_rule_ids, grounding result. Persisted before a
    # draft reaches a vetter so every letter is traceable (V-C2).
    generation_meta = Column(Text, nullable=True)
    case = relationship("Case", back_populates="letters")


class GenerationJob(Base):
    """Tracks letter draft generation requests for idempotency and recovery (V-H8).

    When a draft request arrives, a GenerationJob row is created in 'pending'.
    The in-memory LLM queue promotes it to 'running' when work starts and
    'completed' or 'failed' on finish. On server restart, any job still in
    'running' state is reset to 'pending' so it can be retried.
    """
    __tablename__ = "generation_jobs"

    id          = Column(String, primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    letter_id   = Column(String, ForeignKey("letters.id"), nullable=False, index=True)
    status      = Column(String, default="pending", nullable=False)  # pending|running|completed|failed|cancelled
    idempotency_key = Column(String, nullable=True, unique=True)  # hash of (letter_id, prompt_version, policy_version)
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    # C3: durable execution — a running job holds a lease; the reaper re-queues
    # jobs whose lease expired (crash/hang) until MAX_RETRIES, then fails them.
    retry_count      = Column(Integer, nullable=False, default=0, server_default="0")
    lease_expires_at = Column(DateTime, nullable=True)
    last_error       = Column(Text, nullable=True)

class FeedbackEntry(Base):
    __tablename__ = "feedback_entries"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id      = Column(String, ForeignKey("sessions.id"), nullable=True)
    logged_by       = Column(String, ForeignKey("users.id"), nullable=False)
    validated_by    = Column(String, ForeignKey("users.id"), nullable=True)
    incorrect_claim = Column(Text, nullable=False)
    correct_answer  = Column(Text, nullable=False)
    agency_code     = Column(String, nullable=True)
    status          = Column(String, default="pending")
    reject_reason   = Column(Text, nullable=True)
    source_title    = Column(String, nullable=True)
    source_url      = Column(Text, nullable=True)
    effective_date  = Column(String, nullable=True)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    validated_at    = Column(DateTime, nullable=True)
    exported_at     = Column(DateTime, nullable=True)
    export_batch_id = Column(String, nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_log"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_id        = Column(String, nullable=True)
    role           = Column(String, nullable=True)
    event_type     = Column(String, nullable=False)
    session_id     = Column(String, nullable=True)
    case_id        = Column(String, nullable=True)
    letter_id      = Column(String, nullable=True)
    letter_version = Column(Integer, nullable=True)
    client_ip      = Column(String, nullable=True)
    details        = Column(Text, nullable=True)
    prev_hash      = Column(String, nullable=True)
    entry_hash     = Column(String, nullable=True)
    hash_version   = Column(Integer, nullable=False, default=2)

class RevokedToken(Base):
    """JWT denylist. A logged-out token's jti is stored here and rejected by
    get_current_user until it would have expired anyway."""
    __tablename__ = "revoked_tokens"
    jti        = Column(String, primary_key=True)
    revoked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_id    = Column(String, nullable=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)

def _canonical_ts(ts) -> str:
    """Timestamps must hash identically before and after the SQLite round
    trip. SQLite drops tzinfo, so we canonicalise to naive-UTC ISO format."""
    if ts is None:
        return ""
    if ts.tzinfo is not None:
        from datetime import timezone as _tz
        ts = ts.astimezone(_tz.utc).replace(tzinfo=None)
    return ts.isoformat()

def compute_audit_hash(entry) -> str:
    fields = {
        "id": entry.id, "timestamp": _canonical_ts(entry.timestamp),
        "user_id": entry.user_id, "event_type": entry.event_type,
        "session_id": entry.session_id, "case_id": entry.case_id,
        "letter_id": entry.letter_id, "details": entry.details,
        "prev_hash": entry.prev_hash,
    }
    if (entry.hash_version or 1) >= 2:
        fields.update({
            "hash_version": entry.hash_version,
            "role": entry.role,
            "letter_version": entry.letter_version,
            "client_ip": entry.client_ip,
        })
    payload = json.dumps(fields, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


@event.listens_for(SessionLocal, "before_flush")
def prevent_audit_mutation(session, flush_context, instances):
    """Audit rows are immutable through the application ORM."""
    if any(isinstance(row, AuditLog) for row in session.dirty):
        raise RuntimeError("AuditLog rows cannot be updated")
    if any(isinstance(row, AuditLog) for row in session.deleted):
        raise RuntimeError("AuditLog rows cannot be deleted")
