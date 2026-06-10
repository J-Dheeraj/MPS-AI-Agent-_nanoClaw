"""
Audit service - append-only hash-chained log
"""
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ..database import AuditLog, compute_audit_hash

def log_event(
    db: Session,
    event_type: str,
    user_id: str = None,
    role: str = None,
    session_id: str = None,
    case_id: str = None,
    letter_id: str = None,
    letter_version: int = None,
    client_ip: str = None,
    details: dict = None,
):
    # Get hash of last entry for chain
    last = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).first()
    prev_hash = last.entry_hash if last else None

    entry = AuditLog(
        # id must be set BEFORE hashing: compute_audit_hash includes it, and
        # the column default only fires at flush (after the hash is computed).
        id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
        role=role,
        event_type=event_type,
        session_id=session_id,
        case_id=case_id,
        letter_id=letter_id,
        letter_version=letter_version,
        client_ip=client_ip,
        details=json.dumps(details) if details else None,
        prev_hash=prev_hash,
    )
    entry.entry_hash = compute_audit_hash(entry)
    db.add(entry)
    db.commit()
    return entry
