from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import or_
from ..database import Resident, Case, Letter, get_db, User
from ..auth import require_volunteer
from typing import Optional

router = APIRouter(prefix="/residents", tags=["residents"])

def _serialize_case(c: Case) -> dict:
    latest_letter = (sorted(c.letters, key=lambda l: l.version, reverse=True)[0]
                     if c.letters else None)
    return {
        "id": c.id,
        "session_id": c.session_id,
        "case_type": c.case_type,
        "agency": c.agency,
        "status": c.status,
        "is_new_issue": c.is_new_issue,
        "urgency": c.urgency,
        "created_at": str(c.created_at),
        "parent_case_id": c.parent_case_id,
        "latest_letter": {
            "id": latest_letter.id,
            "status": latest_letter.status,
            "version": latest_letter.version,
            "draft_content": latest_letter.draft_content,
        } if latest_letter else None,
    }

@router.get("/search")
def search_residents(
    q: str,  # name fragment or last 4 chars of masked NRIC
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    results = (db.query(Resident)
               .filter(or_(
                   Resident.name.ilike(f"%{q}%"),
                   Resident.nric_masked.ilike(f"%{q}%"),
               ))
               .limit(20).all())
    return [{
        "id": r.id,
        "name": r.name,
        "nric_masked": r.nric_masked,
        "contact": r.contact,
        "total_cases": len(r.cases),
    } for r in results]

@router.get("/{resident_id}/history")
def resident_history(
    resident_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        raise HTTPException(404, "Resident not found")
    cases = (db.query(Case)
             .filter(Case.resident_id == resident_id)
             .order_by(Case.created_at.desc())
             .all())
    return {
        "resident": {
            "id": resident.id,
            "name": resident.name,
            "nric_masked": resident.nric_masked,
            "contact": resident.contact,
        },
        "cases": [_serialize_case(c) for c in cases],
    }

import re as _re
from pydantic import BaseModel as _BM

_MASKED_NRIC = _re.compile(r"^[STFGM]\*{4}\d{3}[A-Z]$")

class ResidentCreate(_BM):
    name: str
    nric_masked: str
    contact: Optional[str] = None

@router.post("/")
def create_resident(
    body: ResidentCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """Register a new resident. NRIC must already be masked before calling.
    Strict format check: S****567A (first letter + 4 asterisks + last 3 digits + checksum letter).
    A full NRIC is never accepted and never stored."""
    nric = body.nric_masked.strip().upper()
    if not _MASKED_NRIC.match(nric):
        raise HTTPException(
            400,
            "NRIC must be masked in the form S****567A. Full NRIC is not accepted.",
        )
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    r = Resident(name=body.name.strip(), nric_masked=nric, contact=body.contact)
    db.add(r)
    db.commit()
    return {"id": r.id, "name": r.name, "nric_masked": r.nric_masked}
