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


def forward_url() -> str:
    return os.getenv("AUDIT_CHECKPOINT_FORWARD_URL", "").strip()


def _forward_host_allowed(url: str) -> bool:
    """v7: restrict the audit sink to an approved host set (SSRF/exfil guard).

    AUDIT_CHECKPOINT_FORWARD_ALLOWED_HOSTS is a comma-separated host[:port]
    allowlist. When unset the check is a no-op (back-compat); production should
    set it so a compromised config cannot redirect signed heads to an
    attacker-controlled destination."""
    raw = os.getenv("AUDIT_CHECKPOINT_FORWARD_ALLOWED_HOSTS", "").strip()
    if not raw:
        return True
    from urllib.parse import urlparse
    allowed = {h.strip().lower() for h in raw.split(",") if h.strip()}
    host = (urlparse(url).netloc or "").lower()
    return host in allowed


def assert_forward_configured(is_production: bool) -> None:
    """Fail fast if external audit anchoring is mandatory but unconfigured.

    In production a signed checkpoint head that is never forwarded to an
    independent append-only sink leaves a host admin able to tamper with the
    local mutable checkpoint volume undetected. Called from startup."""
    if is_production and not forward_url():
        raise RuntimeError(
            "AUDIT_CHECKPOINT_FORWARD_URL must be set in production: the signed "
            "audit checkpoint head must be forwarded to an external append-only "
            "sink. Refusing to start without a durable external anchor.")
    url = forward_url()
    if url and not _forward_host_allowed(url):
        raise RuntimeError(
            "AUDIT_CHECKPOINT_FORWARD_URL host is not in "
            "AUDIT_CHECKPOINT_FORWARD_ALLOWED_HOSTS. Refusing to forward signed "
            "audit heads to a non-allowlisted destination.")


def _checkpoint_line(entry) -> str:
    """Build the signed checkpoint head line for an audit entry (pure).

    Format: ISO-timestamp TAB entry-id TAB entry-hash [TAB base64-signature].
    Ed25519 signing is deterministic, so this is safe to call more than once."""
    ts = datetime.now(timezone.utc).isoformat()
    key = _checkpoint_signing_key()
    if key is not None:
        import base64
        sig = base64.b64encode(key.sign(
            _checkpoint_signed_content(entry.id, entry.entry_hash))).decode("ascii")
        return f"{ts}\t{entry.id}\t{entry.entry_hash}\t{sig}\n"
    return f"{ts}\t{entry.id}\t{entry.entry_hash}\n"


def _forward_post(line: str) -> None:
    """POST one line to the sink with authenticated transport. Raises on any
    failure so the caller records the error and retries."""
    import httpx
    url = forward_url()
    if not _forward_host_allowed(url):
        raise RuntimeError("audit sink host not in allowlist")
    headers = {"Content-Type": "text/plain"}
    token = os.getenv("AUDIT_CHECKPOINT_FORWARD_TOKEN", "").strip()
    if token:
        # Support a Docker-secret file path (preferred) or a literal token.
        tok_path = pathlib.Path(token)
        if tok_path.exists():
            token = tok_path.read_text(encoding="utf-8").strip()
        headers["Authorization"] = f"Bearer {token}"
    # Sink idempotency (v7 C2): a crash after a successful POST but before
    # delivered_at is set causes a retry; the sink dedupes on this key.
    parts = line.rstrip("\n").split("\t")
    if len(parts) >= 3:
        headers["Idempotency-Key"] = parts[2]
    kwargs = {"headers": headers, "timeout": 5.0,
              "content": line.encode("utf-8")}
    cert = os.getenv("AUDIT_CHECKPOINT_FORWARD_CLIENT_CERT", "").strip()
    key = os.getenv("AUDIT_CHECKPOINT_FORWARD_CLIENT_KEY", "").strip()
    if cert and key:
        kwargs["cert"] = (cert, key)
    elif cert:
        kwargs["cert"] = cert
    resp = httpx.post(url, **kwargs)
    resp.raise_for_status()


def deliver_outbox_once(db: Session, limit: int = 20) -> tuple[int, int]:
    """Deliver pending outbox rows to the external sink. Returns
    (delivered, failed). Each failure increments attempts and records the error
    so it is retried on the next pass; the inter-pass interval is the backoff."""
    from ..database import AuditCheckpointOutbox
    if not forward_url():
        return (0, 0)
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    q = (db.query(AuditCheckpointOutbox)
         .filter(AuditCheckpointOutbox.delivered_at.is_(None))
         .order_by(AuditCheckpointOutbox.created_at)
         .limit(limit))
    if dialect == "postgresql":
        # Lock claimed rows so multiple API replicas never select the same row.
        q = q.with_for_update(skip_locked=True)
    pending = q.all()
    delivered = failed = 0
    for row in pending:
        try:
            _forward_post(row.line)
            row.delivered_at = datetime.now(timezone.utc)
            row.last_error = None
            delivered += 1
        except Exception as exc:  # noqa: BLE001 - durable retry, record and move on
            row.attempts = (row.attempts or 0) + 1
            row.last_error = str(exc)[:500]
            failed += 1
    if pending:
        db.commit()
    return (delivered, failed)


def outbox_backlog(db: Session) -> dict:
    """Undelivered-count and oldest-undelivered age for /health/audit-chain."""
    from ..database import AuditCheckpointOutbox
    rows = (db.query(AuditCheckpointOutbox)
            .filter(AuditCheckpointOutbox.delivered_at.is_(None))
            .order_by(AuditCheckpointOutbox.created_at).all())
    if not rows:
        return {"undelivered": 0, "oldest_age_seconds": 0}
    oldest = rows[0].created_at
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - oldest).total_seconds()
    return {"undelivered": len(rows), "oldest_age_seconds": int(age)}


def _append_checkpoint_file(line: str) -> None:
    """Append a prebuilt signed line to the local anchor file (best-effort)."""
    try:
        path = _checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        import logging
        logging.getLogger("mps.audit").error(
            "AUDIT CHECKPOINT WRITE FAILED — external anchor not maintained; "
            "check AUDIT_CHECKPOINT_FILE volume")
        global _checkpoint_failures
        _checkpoint_failures += 1


def _write_checkpoint(db, entry) -> None:
    """Append a single-line checkpoint to the anchor file (V-H9).

    Format: ISO-timestamp TAB entry-id TAB entry-hash NEWLINE.
    The file is opened in append mode with O_APPEND so each write is atomic
    on POSIX. It should be stored on a different volume or sent to a remote
    syslog in production for the highest integrity assurance.
    """
    try:
        path = _checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = _checkpoint_line(entry)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
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
        # v7 C2: the audit entry and its forwarding-outbox row commit in ONE
        # transaction, so a crash can never leave an audited event without a
        # durable delivery record. The local file anchor is a separate medium
        # appended best-effort after the commit.
        line = _checkpoint_line(entry)
        if forward_url():
            from ..database import AuditCheckpointOutbox
            db.add(AuditCheckpointOutbox(line=line))
        db.commit()
        _append_checkpoint_file(line)
        return entry
