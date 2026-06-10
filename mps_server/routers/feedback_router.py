import os
from datetime import date, datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..auth import require_vetter, require_volunteer
from ..database import FeedbackEntry, User, get_db
from ..services.audit import log_event
from ..services.redaction import scan

router = APIRouter(prefix="/feedback", tags=["feedback"])

VALID_AGENCIES = {"HDB", "CPF", "MSF", "MOH", "MOM", "ICA", "GENERAL"}
SOURCE_HOST_SUFFIXES = tuple(
    suffix.strip().lower()
    for suffix in os.getenv("POLICY_SOURCE_HOST_SUFFIXES", ".gov.sg").split(",")
    if suffix.strip()
)


class FeedbackCreate(BaseModel):
    agency_code: str
    incorrect_claim: str = Field(min_length=1, max_length=4_000)
    correct_answer: str = Field(min_length=1, max_length=4_000)

    class Config:
        extra = "forbid"


class FeedbackValidate(BaseModel):
    action: str
    reject_reason: Optional[str] = Field(default=None, max_length=2_000)
    source_title: Optional[str] = Field(default=None, max_length=300)
    source_url: Optional[str] = Field(default=None, max_length=2_000)
    effective_date: Optional[str] = None

    class Config:
        extra = "forbid"


class FeedbackOut(BaseModel):
    id: str
    agency_code: Optional[str]
    incorrect_claim: str
    correct_answer: str
    status: str
    logged_by: str
    validated_by: Optional[str]
    reject_reason: Optional[str]
    source_title: Optional[str]
    source_url: Optional[str]
    effective_date: Optional[str]
    created_at: datetime
    validated_at: Optional[datetime]

    class Config:
        from_attributes = True


def _validate_source(source_title: str, source_url: str, effective_date: str) -> None:
    if not source_title.strip():
        raise HTTPException(422, "source_title is required for approval")
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise HTTPException(422, "source_url must be an HTTPS URL")
    if not any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in SOURCE_HOST_SUFFIXES):
        raise HTTPException(422, "source_url host is not on the approved government allowlist")
    try:
        effective = date.fromisoformat(effective_date)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "effective_date must use YYYY-MM-DD format") from exc
    if effective.year < 2000 or effective.year > date.today().year + 2:
        raise HTTPException(422, "effective_date is outside the accepted range")


@router.post("/", response_model=FeedbackOut)
async def log_feedback(
    body: FeedbackCreate,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    agency = body.agency_code.strip().upper()
    if agency not in VALID_AGENCIES:
        raise HTTPException(400, f"agency_code must be one of {sorted(VALID_AGENCIES)}")

    findings = scan(body.incorrect_claim) + scan(body.correct_answer)
    if findings:
        raise HTTPException(
            422,
            detail={
                "message": "Feedback must contain policy information only, not personal data",
                "finding_types": sorted({kind for kind, _ in findings}),
            },
        )

    entry = FeedbackEntry(
        session_id=None,
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
        "feedback_logged",
        user_id=current_user.id,
        role=current_user.role,
        client_ip=request.client.host if request.client else None,
        details={"agency": agency, "feedback_id": entry.id},
    )
    db.refresh(entry)
    return entry


@router.get("/pending", response_model=List[FeedbackOut])
async def list_pending_feedback(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
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
    action = body.action.strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(400, "action must be approve or reject")

    entry = db.query(FeedbackEntry).filter(FeedbackEntry.id == feedback_id).first()
    if not entry:
        raise HTTPException(404, "Feedback entry not found")
    if entry.status != "pending":
        raise HTTPException(409, f"Entry is already {entry.status}")
    if entry.logged_by == current_user.id:
        raise HTTPException(409, "A second person must validate this correction")

    if action == "approve":
        _validate_source(body.source_title or "", body.source_url or "", body.effective_date or "")
        entry.status = "approved"
        entry.source_title = body.source_title.strip()
        entry.source_url = body.source_url.strip()
        entry.effective_date = body.effective_date
    else:
        if not body.reject_reason or not body.reject_reason.strip():
            raise HTTPException(422, "reject_reason is required when rejecting feedback")
        entry.status = "rejected"
        entry.reject_reason = body.reject_reason.strip()

    entry.validated_by = current_user.id
    entry.validated_at = datetime.now(timezone.utc)
    log_event(
        db,
        f"feedback_{entry.status}",
        user_id=current_user.id,
        role=current_user.role,
        client_ip=request.client.host if request.client else None,
        details={"feedback_id": feedback_id, "action": action},
    )
    db.refresh(entry)
    return entry


@router.get("/my", response_model=List[FeedbackOut])
async def my_feedback(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    return (
        db.query(FeedbackEntry)
        .filter(FeedbackEntry.logged_by == current_user.id)
        .order_by(FeedbackEntry.created_at.desc())
        .limit(50)
        .all()
    )
