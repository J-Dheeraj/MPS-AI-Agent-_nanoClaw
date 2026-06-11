"""
Audit service - append-only hash-chained log
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
import pathlib
from datetime import datetime, timezone
from ..database import AuditLog, compute_audit_hash


_AUDIT_LOCK = threading.Lock()


# Path to the append-only audit checkpoint file. Lives outside the database so
# a DBA who tampers with audit rows must also forge this file to avoid detection.
# Set AUDIT_CHECKPOINT_FILE to override (default: same dir as the DB file).
def _checkpoint_path() -> pathlib.Path:
    default = pathlib.Path(__file__).resolve().parents[2] / "data" / "audit_checkpoint.log"
    return pathlib.Path(os.getenv("AUDIT_CHECKPOINT_FILE", str(default)))


def _write_checkpoint(entry) -> None:
    """Append a single-line checkpoint to the anchor file (V-H9).

    Format: ISO-timestamp TAB entry-id TAB entry-hash NEWLINE.
    The file is opened in append mode with O_APPEND so each write is atomic
    on POSIX. It should be stored on a different volume or sent to a remote
    syslog in production for the highest integrity assurance.
    """
    try:
        path = _checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"{datetime.now(timezone.utc).isoformat()}\t{entry.id}\t{entry.entry_hash}\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # never let checkpoint failure break the audit log itself


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
    with _AUDIT_LOCK:
        # PostgreSQL advisory locking serialises the chain across processes.
        # SQLite is development-only and is protected within this process.
        if db.bind and db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(684773921)"))

        last = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).first()
        prev_hash = last.entry_hash if last else None

        entry = AuditLog(
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
            details=json.dumps(details, sort_keys=True) if details else None,
            prev_hash=prev_hash,
            hash_version=2,
        )
        entry.entry_hash = compute_audit_hash(entry)
        db.add(entry)
        db.commit()
        _write_checkpoint(entry)
        return entry
