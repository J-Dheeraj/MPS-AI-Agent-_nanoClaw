"""Data retention and erasure controls (V-C3).

Implements the operational privacy controls the review found documented but
unimplemented: a retention sweep that purges constituent personal data after a
configured window, and a data-subject erasure command for a specific resident.
Both are deterministic, audit-logged, and preserve the append-only audit chain
and the anonymised statistical shell of each case (case type, agency, status)
so reporting survives while personal data does not.

Personal data in scope:
  - Resident.name, Resident.nric_masked, Resident.contact
  - Case.notes (volunteer notes describing the resident's circumstances)
  - Letter.draft_content, Letter.final_content (letter body naming the resident)

What is retained after purge: the structural records (ids, case_type, agency,
status, timestamps) and the audit log. What is removed: every field above,
overwritten with a tombstone marker.

CLI:
    python3 -m mps_server.retention --sweep            # purge past the window
    python3 -m mps_server.retention --sweep --dry-run  # report only
    python3 -m mps_server.retention --delete-resident <resident_id>
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from .database import Case, Letter, Resident, Session, SessionLocal
from .services.audit import log_event

TOMBSTONE = "[REDACTED]"
DEFAULT_RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "365"))


def _purge_resident_pii(db: DBSession, resident: Resident, *, reason: str) -> None:
    """Overwrite a resident's personal data and the PII-bearing free text of
    all their cases and letters with a tombstone. Structural fields are kept."""
    resident.name = TOMBSTONE
    resident.nric_masked = TOMBSTONE
    resident.contact = None
    for case in resident.cases:
        if case.notes:
            case.notes = TOMBSTONE
        for letter in case.letters:
            if letter.draft_content:
                letter.draft_content = TOMBSTONE
            if letter.final_content:
                letter.final_content = TOMBSTONE
    log_event(
        db,
        "resident_pii_purged",
        details={"resident_id": resident.id, "reason": reason},
    )


def sweep(db: DBSession, retention_days: int | None = None, dry_run: bool = False) -> dict:
    """Purge personal data for residents whose every case sits in a session that
    completed (sent_at) more than retention_days ago. A resident with any case
    still in an active/recent session is left untouched."""
    days = DEFAULT_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    purged, skipped = [], 0
    for resident in db.query(Resident).all():
        if resident.name == TOMBSTONE:
            continue  # already purged
        cases = resident.cases
        if not cases:
            continue
        # Every case must belong to a session sent before the cutoff.
        eligible = True
        for case in cases:
            session = db.query(Session).filter(Session.id == case.session_id).first()
            sent_at = session.sent_at if session else None
            if sent_at is None:
                eligible = False
                break
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at > cutoff:
                eligible = False
                break
        if not eligible:
            skipped += 1
            continue
        if not dry_run:
            _purge_resident_pii(db, resident, reason=f"retention>{days}d")
        purged.append(resident.id)

    if not dry_run:
        db.commit()
    return {"purged": purged, "purged_count": len(purged), "skipped": skipped,
            "retention_days": days, "dry_run": dry_run}


def delete_resident(db: DBSession, resident_id: str) -> dict:
    """Right-to-erasure: purge one resident's personal data on request,
    regardless of retention window. Audit-logged."""
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        return {"deleted": False, "reason": "not found", "resident_id": resident_id}
    _purge_resident_pii(db, resident, reason="data_subject_erasure")
    db.commit()
    return {"deleted": True, "resident_id": resident_id}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true", help="purge past the retention window")
    parser.add_argument("--retention-days", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delete-resident", metavar="RESIDENT_ID", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.delete_resident:
            print(delete_resident(db, args.delete_resident))
        elif args.sweep:
            print(sweep(db, retention_days=args.retention_days, dry_run=args.dry_run))
        else:
            parser.error("choose --sweep or --delete-resident")
    finally:
        db.close()


if __name__ == "__main__":
    main()
