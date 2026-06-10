from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from ..database import get_db, FeedbackEntry, User
from ..auth import require_volunteer, require_vetter
from ..services.audit import log_event

router = APIRouter(prefix="/feedback", tags=["feedback"])

VALID_AGENCIES = {"HDB", "CPF", "MSF", "MOH", "MOM", "ICA", "GENERAL"}

# ── Schemas ──────────────────────────────────────────────────────────────────
# Feedback is anonymised by design: corrections carry NO case reference, so an
# exported correction can never be linked back to a resident or a letter.

class FeedbackCreate(BaseModel):
    agency_code: str               # HDB, CPF, MSF, MOH, MOM, ICA, GENERAL
    incorrect_claim: str           # what the agent said that was wrong
    correct_answer: str            # the correct information
    session_id: Optional[str] = None

class FeedbackValidate(BaseModel):
    action: str                    # "approve" or "reject"
    reject_reason: Optional[str] = None

class FeedbackOut(BaseModel):
    id: str
    session_id: Optional[str]
    agency_code: Optional[str]
    incorrect_claim: str
    correct_answer: str
    status: str                    # pending, approved, rejected
    logged_by: str
    validated_by: Optional[str]
    reject_reason: Optional[str]
    created_at: datetime
    validated_at: Optional[datetime]

    class Config:
        from_attributes = True

# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/", response_model=FeedbackOut)
async def log_feedback(
    body: FeedbackCreate,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """
    Volunteer or vetter logs a policy correction (the LLM said something wrong).
    Status starts as 'pending' — a vetter must validate before it reaches Hermes.
    Corrections are anonymised: no case or resident reference is stored.
    """
    agency = body.agency_code.strip().upper()
    if agency not in VALID_AGENCIES:
        raise HTTPException(400, f"agency_code must be one of {sorted(VALID_AGENCIES)}")
    if not body.incorrect_claim.strip() or not body.correct_answer.strip():
        raise HTTPException(400, "incorrect_claim and correct_answer are required")

    entry = FeedbackEntry(
        session_id=body.session_id,
        agency_code=agency,
        incorrect_claim=body.incorrect_claim.strip(),
        correct_answer=body.correct_answer.strip(),
        logged_by=current_user.id,
        status="pending",
    )
    db.add(entry)
    db.flush()

    log_event(
        db,
        "FEEDBACK_LOGGED",
        user_id=current_user.id,
        role=current_user.role,
        session_id=body.session_id,
        client_ip=request.client.host if request.client else None,
        details={"agency": agency, "feedback_id": entry.id},
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/pending", response_model=List[FeedbackOut])
async def list_pending_feedback(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
    """Vetter sees all feedback entries awaiting validation."""
    return (
        db.query(FeedbackEntry)
        .filter(FeedbackEntry.status == "pending")
        .order_by(FeedbackEntry.created_at.asc())
        .all()
    )


@router.get("/approved", response_model=List[FeedbackOut])
async def list_approved_feedback(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
    """
    Hermes GEPA reads approved feedback to improve SKILL files.
    Only approved, anonymised entries — no constituent data passes through.
    """
    return (
        db.query(FeedbackEntry)
        .filter(FeedbackEntry.status == "approved")
        .order_by(FeedbackEntry.validated_at.asc())
        .all()
    )


@router.post("/{feedback_id}/validate", response_model=FeedbackOut)
async def validate_feedback(
    feedback_id: str,
    body: FeedbackValidate,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
    """
    Vetter approves or rejects a feedback entry.
    Only approved entries are forwarded to Hermes GEPA.
    """
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    entry = db.query(FeedbackEntry).filter(FeedbackEntry.id == feedback_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Feedback entry not found")
    if entry.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Entry is already '{entry.status}' — cannot re-validate",
        )
    if body.action == "reject" and not body.reject_reason:
        raise HTTPException(
            status_code=422,
            detail="reject_reason is required when rejecting feedback",
        )

    entry.status = "approved" if body.action == "approve" else "rejected"
    entry.validated_by = current_user.id
    entry.validated_at = datetime.now(timezone.utc)
    if body.reject_reason:
        entry.reject_reason = body.reject_reason

    log_event(
        db,
        f"FEEDBACK_{entry.status.upper()}",
        user_id=current_user.id,
        role=current_user.role,
        session_id=entry.session_id,
        client_ip=request.client.host if request.client else None,
        details={"feedback_id": feedback_id, "action": body.action},
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/my", response_model=List[FeedbackOut])
async def my_feedback(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """Returns feedback entries logged by the current user."""
    return (
        db.query(FeedbackEntry)
        .filter(FeedbackEntry.logged_by == current_user.id)
        .order_by(FeedbackEntry.created_at.desc())
        .limit(50)
        .all()
    )
