"""
Audit chain verification command.

Usage:
    python3 -m mps_server.verify_audit

Walks the audit log oldest-to-newest and checks:
  1. each entry's stored hash matches a recomputation of its fields
  2. each entry's prev_hash matches the previous entry's hash

Exit code 0 = chain intact, 1 = tampering or corruption detected.
Run this before every MPS night and after any incident.
"""
import sys

from .database import AuditLog, SessionLocal, compute_audit_hash


def verify() -> int:
    db = SessionLocal()
    try:
        entries = db.query(AuditLog).order_by(AuditLog.timestamp.asc()).all()
        if not entries:
            print("Audit log is empty - nothing to verify.")
            return 0

        prev_hash = None
        bad = 0
        for i, e in enumerate(entries):
            recomputed = compute_audit_hash(e)
            if e.entry_hash != recomputed:
                # Legacy rows (before the id-before-hash fix) were hashed with
                # id=None; recompute that way before declaring tampering.
                saved_id = e.id
                e.id = None
                legacy = compute_audit_hash(e)
                e.id = saved_id
                if e.entry_hash != legacy:
                    print(f"TAMPERED? row {i} ({e.event_type} @ {e.timestamp}): "
                          f"stored hash does not match recomputation")
                    bad += 1
            if e.prev_hash != prev_hash:
                print(f"BROKEN CHAIN at row {i} ({e.event_type} @ {e.timestamp}): "
                      f"prev_hash mismatch")
                bad += 1
            prev_hash = e.entry_hash

        if bad:
            print(f"FAILED: {bad} integrity violation(s) across {len(entries)} entries.")
            return 1
        print(f"OK: audit chain intact ({len(entries)} entries).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(verify())
