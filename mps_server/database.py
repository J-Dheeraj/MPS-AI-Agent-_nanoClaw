"""
MPS Server - Database models and connection
SQLite for dev, swap DATABASE_URL for PostgreSQL in production
"""
import hashlib, json, uuid
from datetime import datetime, timezone
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, create_engine)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

import os as _os
import pathlib as _pathlib
# DB lives next to this file (mps_server/mps.db) regardless of the cwd the
# server was launched from. Override with DATABASE_URL for PostgreSQL etc.
_default_db = _pathlib.Path(__file__).parent / "mps.db"
DATABASE_URL = _os.environ.get("DATABASE_URL", f"sqlite:///{_default_db}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    totp_secret   = Column(String, nullable=True)
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
    case = relationship("Case", back_populates="letters")

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
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    validated_at    = Column(DateTime, nullable=True)

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)

def compute_audit_hash(entry) -> str:
    payload = json.dumps({
        "id": entry.id, "timestamp": str(entry.timestamp),
        "user_id": entry.user_id, "event_type": entry.event_type,
        "session_id": entry.session_id, "case_id": entry.case_id,
        "letter_id": entry.letter_id, "details": entry.details,
        "prev_hash": entry.prev_hash,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
