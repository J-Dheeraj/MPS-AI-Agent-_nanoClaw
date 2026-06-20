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


_checkpoint_failures = 0  # read by /health/audit-chain (V4-C2)

# C5: sign each checkpoint head so a host admin who can write the mutable local
# volume still cannot forge a consistent anchor without the signing key. The key
# is held outside the server (Docker secret / external KMS). Unsigned mode
# remains valid for dev.
_signing_key_cache = {"loaded": False, "key": None}


def _checkpoint_signing_key():
    if not _signing_key_cache["loaded"]:
        _signing_key_cache["loaded"] = True
        path = os.getenv("AUDIT_CHECKPOINT_SIGNING_KEY", "").strip()
        if path:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey)
            key = serialization.load_pem_private_key(
                pathlib.Path(path).read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise RuntimeError("AUDIT_CHECKPOINT_SIGNING_KEY must be Ed25519")
            _signing_key_cache["key"] = key
    return _signing_key_cache["key"]


def _checkpoint_public_key():
    path = os.getenv("AUDIT_CHECKPOINT_PUBLIC_KEY", "").strip()
    if not path:
        return None
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_public_key(pathlib.Path(path).read_bytes())


def _checkpoint_signed_content(entry_id: str, entry_hash: str) -> bytes:
    return f"{entry_id}\t{entry_hash}".encode("utf-8")


def verify_checkpoint_line(line: str) -> bool:
    """Verify a checkpoint line's signature against AUDIT_CHECKPOINT_PUBLIC_KEY.
    Returns True if unsigned-mode (no key configured) or the signature verifies;
    False if a signature is present/required but does not verify (C5)."""
    pub = _checkpoint_public_key()
    if pub is None:
        return True
    import base64
    from cryptography.exceptions import InvalidSignature
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 4:
        return False  # public key configured but line is unsigned
    _ts, entry_id, entry_hash, sig_b64 = parts[0], parts[1], parts[2], parts[3]
    try:
        pub.verify(base64.b64decode(sig_b64),
                   _checkpoint_signed_content(entry_id, entry_hash))
        return True
    except (InvalidSignature, ValueError):
        return False


def _forward_checkpoint(line: str) -> None:
    """Best-effort POST of a signed head line to an external append-only sink
    (AUDIT_CHECKPOINT_FORWARD_URL). Fire-and-forget; never blocks the audit
    write or raises. The true WORM/immutable destination is infrastructure."""
    url = os.getenv("AUDIT_CHECKPOINT_FORWARD_URL", "").strip()
    if not url:
        return

    def _post():
        try:
            import httpx
            httpx.post(url, content=line.encode("utf-8"), timeout=2.0)
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


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
        ts = datetime.now(timezone.utc).isoformat()
        key = _checkpoint_signing_key()
        if key is not None:
            import base64
            sig = base64.b64encode(key.sign(
                _checkpoint_signed_content(entry.id, entry.entry_hash))).decode("ascii")
            line = f"{ts}\t{entry.id}\t{entry.entry_hash}\t{sig}\n"
        else:
            line = f"{ts}\t{entry.id}\t{entry.entry_hash}\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
        _forward_checkpoint(line)
    except OSError:
        # Never let checkpoint failure break the audit log itself, but it must
        # not be silent either (V4-C2): without the anchor a tampered DB is
        # undetectable, so log loudly and count failures for alerting.
        import logging
        logging.getLogger("mps.audit").error(
            "AUDIT CHECKPOINT WRITE FAILED for entry %s — external anchor is "
            "not being maintained; check AUDIT_CHECKPOINT_FILE volume",
            entry.id)
        global _checkpoint_failures
        _checkpoint_failures += 1


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
