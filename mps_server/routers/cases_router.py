from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel as _BaseModel

class VetterReturnBody(_BaseModel):
    comment: str

class VetterSubmitBody(_BaseModel):
    final_content: str   # Vetter's edited final text — saved, frozen, sent to MP

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import joinedload
from ..database import Case, Session, Letter, Resident, get_db, User
from ..auth import require_volunteer, require_vetter, get_current_user
from ..services.audit import log_event
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/cases", tags=["cases"])

VALID_CASE_TYPES = {"grant", "appeal", "enquiry", "re-appeal"}
VALID_AGENCIES = {"HDB", "CPF", "MSF", "MOH", "MOM", "ICA", "GENERAL"}
VALID_URGENCIES = {"normal", "urgent", "critical"}

# ── Case status state machine ────────────────────────────────────────────────
# Every status change must go through transition(). Anything not listed here
# is rejected with 409 — no ad hoc status writes.
CASE_TRANSITIONS = {
    "assigned":   {"drafting", "drafted", "pending_mp"},  # pending_mp: vetter may submit a returned case directly
    "drafting":   {"drafted"},
    "drafted":    {"drafting", "drafted", "pending_mp", "assigned"},  # regenerate / resubmit / vetter-submit / vetter-return
    "pending_mp": {"approved"},
    "approved":   {"sent"},
    "sent":       set(),
}

def transition(case: "Case", new_status: str) -> None:
    allowed = CASE_TRANSITIONS.get(case.status, set())
    if new_status not in allowed:
        raise HTTPException(
            409, f"Invalid case status transition: {case.status} -> {new_status}"
        )
    case.status = new_status

class CaseCreateRequest(BaseModel):
    resident_id:    str
    case_type:      str
    agency:         str
    urgency:        str = "normal"
    session_id:     Optional[str] = None   # defaults to the active session
    is_new_issue:   bool = True
    is_reappeal:    bool = False           # client convenience flag (inverse of is_new_issue)
    notes:          Optional[str] = None   # volunteer's case notes
    parent_case_id: Optional[str] = None

@router.get("/mine")
def my_cases(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """Tonight's cases assigned to this volunteer."""
    # Get current active session
    session = (db.query(Session)
               .filter(Session.status.in_(["open", "active"]))
               .order_by(Session.opened_at.desc()).first())
    if not session:
        return {"cases": [], "message": "No active session"}

    cases = (db.query(Case)
             .filter(Case.session_id == session.id,
                     Case.volunteer_id == current_user.id)
             .order_by(Case.urgency.desc(), Case.created_at.asc())
             .all())
    return {"session_id": session.id, "cases": [_fmt(c) for c in cases]}

@router.get("/queue")
def vetter_queue(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
    """Letters ready for vetter review."""
    session = (db.query(Session)
               .filter(Session.status.in_(["open", "active"]))
               .order_by(Session.opened_at.desc()).first())
    if not session:
        return {"cases": []}

    cases = (db.query(Case)
             .filter(Case.session_id == session.id,
                     Case.status == "drafted")
             .all())
    return {"session_id": session.id, "pending_count": len(cases),
            "cases": [_fmt(c) for c in cases]}

@router.get("/")
def list_cases(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """Role-aware case list for the active session.
    Volunteers see their own cases; vetters and admins see all."""
    session = (db.query(Session)
               .filter(Session.status.in_(["open", "active"]))
               .order_by(Session.opened_at.desc()).first())
    if not session:
        return {"session_id": None, "cases": []}
    q = db.query(Case).filter(Case.session_id == session.id)
    if current_user.role == "volunteer":
        q = q.filter(Case.volunteer_id == current_user.id)
    cases = q.order_by(Case.urgency.desc(), Case.created_at.asc()).all()
    return {"session_id": session.id, "cases": [_fmt(c) for c in cases]}

@router.post("/")
def create_case(
    req: CaseCreateRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    case_type = req.case_type.strip().lower()
    agency = req.agency.strip().upper()
    urgency = req.urgency.strip().lower()
    if case_type not in VALID_CASE_TYPES:
        raise HTTPException(422, f"Unsupported case_type: {req.case_type}")
    if agency not in VALID_AGENCIES:
        raise HTTPException(422, f"Unsupported agency: {req.agency}")
    if urgency not in VALID_URGENCIES:
        raise HTTPException(422, f"Unsupported urgency: {req.urgency}")
    if req.notes and len(req.notes) > 20_000:
        raise HTTPException(422, "Case notes must not exceed 20000 characters")
    if req.notes:
        from ..services.redaction import scan
        if any(kind == "nric_full" for kind, _ in scan(req.notes)):
            raise HTTPException(422, "Case notes must not contain a full NRIC")

    resident = db.query(Resident).filter(Resident.id == req.resident_id).first()
    if not resident:
        raise HTTPException(404, "Resident not found")
    if req.session_id:
        session = db.query(Session).filter(Session.id == req.session_id).first()
    else:
        session = (db.query(Session)
                   .filter(Session.status.in_(["open", "active"]))
                   .order_by(Session.opened_at.desc()).first())
    if not session or session.status not in ("open", "active"):
        raise HTTPException(400, "No active session found")

    parent_case = None
    if req.parent_case_id:
        parent_case = db.query(Case).filter(Case.id == req.parent_case_id).first()
        if not parent_case or parent_case.resident_id != resident.id:
            raise HTTPException(422, "Parent case must belong to the same resident")
    if (req.is_reappeal or case_type == "re-appeal") and not parent_case:
        raise HTTPException(422, "A re-appeal requires a parent_case_id")

    case = Case(
        session_id=session.id,
        resident_id=req.resident_id,
        case_type=case_type,
        agency=agency,
        urgency=urgency,
        is_new_issue=req.is_new_issue and not req.is_reappeal,
        notes=req.notes,
        parent_case_id=req.parent_case_id,
        volunteer_id=current_user.id,
        status="assigned",
    )
    db.add(case)
    session.total_cases = (session.total_cases or 0) + 1
    db.commit()
    log_event(db, "case_created", user_id=current_user.id, role=current_user.role,
              session_id=session.id, case_id=case.id,
              client_ip=request.client.host if request.client else None,
        details={"case_type": case_type, "agency": agency})
    return _fmt(case)

@router.post("/{case_id}/submit")
def submit_for_vetting(
    case_id: str,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    case = _get_own_case(case_id, current_user.id, db)
    transition(case, "drafted")
    db.commit()
    log_event(db, "case_submitted", user_id=current_user.id, role=current_user.role,
              case_id=case_id, client_ip=request.client.host if request.client else None)
    return {"case_id": case_id, "status": case.status}

@router.post("/{case_id}/vetter-submit")
def vetter_submit(
    case_id: str,
    body: VetterSubmitBody,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
    """
    Vetter has edited the draft directly and submits it for MP's final check.
    Saves final_content, freezes the letter, and moves case to pending_mp.
    This is the primary vetter action — the vetter owns the final letter text.
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    letter = _latest_letter(case)
    if not letter:
        raise HTTPException(400, "No draft letter found for this case")
    if not body.final_content.strip() or len(body.final_content) > 20_000:
        raise HTTPException(422, "Final letter must be between 1 and 20000 characters")
    from ..services.validator import validate_letter
    blocking = [
        finding
        for finding in validate_letter(body.final_content)
        if finding.severity == "block"
    ]
    if blocking:
        raise HTTPException(
            422,
            detail={
                "message": "Final letter failed mandatory safety checks",
                "findings": [
                    {"code": finding.code, "message": finding.message}
                    for finding in blocking
                ],
            },
        )
    transition(case, "pending_mp")    # 409 if not in a vettable state
    # Save vetter's final edited text and freeze
    letter.final_content = body.final_content
    letter.status = "vetted"
    letter.vetted_at = datetime.now(timezone.utc)
    letter.is_frozen = True           # no further edits allowed
    db.commit()
    log_event(db, "vetter_submitted", user_id=current_user.id, role=current_user.role,
              case_id=case_id, letter_id=letter.id, letter_version=letter.version,
              client_ip=request.client.host if request.client else None)
    return {"case_id": case_id, "status": "pending_mp", "letter_id": letter.id}

@router.post("/{case_id}/vetter-return")
def vetter_return(
    case_id: str,
    body: VetterReturnBody,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_vetter),
):
    if not body.comment.strip() or len(body.comment) > 4_000:
        raise HTTPException(422, "Return comment must be between 1 and 4000 characters")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    transition(case, "assigned")      # 409 unless case is in the review queue
    letter = _latest_letter(case)
    if letter:
        letter.status = "returned"
        letter.vetter_comment = body.comment
    db.commit()
    log_event(db, "vetter_returned", user_id=current_user.id, role=current_user.role,
              case_id=case_id, details={"comment": body.comment},
              client_ip=request.client.host if request.client else None)
    return {"case_id": case_id, "status": "returned", "comment": body.comment}

def _get_own_case(case_id: str, user_id: str, db: DBSession) -> Case:
    case = db.query(Case).filter(Case.id == case_id,
                                  Case.volunteer_id == user_id).first()
    if not case:
        raise HTTPException(404, "Case not found or not assigned to you")
    return case

def _latest_letter(case: Case):
    if not case.letters:
        return None
    return sorted(case.letters, key=lambda l: l.version, reverse=True)[0]

def _fmt(c: Case) -> dict:
    letter = _latest_letter(c)
    # Include resident inline so GTK4 client can display name/NRIC without extra call
    res = None
    if hasattr(c, "resident") and c.resident:
        r = c.resident
        res = {"id": r.id, "name": r.name, "nric_masked": r.nric_masked,
               "contact": r.contact or ""}
    return {
        "id": c.id, "case_type": c.case_type, "agency": c.agency,
        "status": c.status, "urgency": c.urgency,
        "is_new_issue": c.is_new_issue, "is_reappeal": not c.is_new_issue,
        "parent_case_id": c.parent_case_id,
        "resident_id": c.resident_id, "session_id": c.session_id,
        "notes": c.notes,
        "resident": res,
        "vetter_comment": letter.vetter_comment if letter else None,
        # GTK4 client uses "letter_id"
        "letter_id": letter.id if letter else None,
        "latest_letter_id": letter.id if letter else None,
        "letter_status": letter.status if letter else None,
        "draft_content": letter.draft_content if letter else None,
        "final_content": letter.final_content if letter else None,
    }


@router.get("/{case_id}")
def get_case(
    case_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """Case detail. Volunteers may only read their own cases."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    if current_user.role == "volunteer" and case.volunteer_id != current_user.id:
        raise HTTPException(403, "Not your case")
    return _fmt(case)
