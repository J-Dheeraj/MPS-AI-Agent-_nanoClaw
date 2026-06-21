from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession
from ..database import Session, Case, get_db, User
from ..auth import require_volunteer, require_admin, get_current_user
from ..services.audit import log_event
from pydantic import BaseModel, ConfigDict
from typing import Optional

router = APIRouter(prefix="/sessions", tags=["sessions"])

class SessionOut(BaseModel):
    id: str; date: str; status: str
    total_cases: int; completed_cases: int; carried_over: int
    opened_at: Optional[str]; closed_at: Optional[str]
    model_config = ConfigDict(from_attributes=True)

@router.get("/current")
def get_current_session(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = (db.query(Session)
               .filter(Session.status.in_(["open", "active", "pending_mp"]))
               .order_by(Session.opened_at.desc())
               .first())
    if not session:
        return {"session": None, "message": "No active session"}
    return {
        "id": session.id, "date": session.date, "status": session.status,
        "total_cases": session.total_cases,
        "completed_cases": session.completed_cases,
        "carried_over": session.carried_over,
        "opened_at": str(session.opened_at),
    }

@router.post("/open")
def open_session(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = db.query(Session).filter(
        Session.date == today,
        Session.status.in_(["open", "active"])
    ).first()
    if existing:
        raise HTTPException(400, f"Session already open for {today}")
    session = Session(date=today, status="active", opened_by=current_user.id)
    db.add(session)
    db.commit()
    log_event(db, "session_open", user_id=current_user.id, role=current_user.role,
              session_id=session.id, client_ip=request.client.host if request.client else None)
    return {"session_id": session.id, "date": session.date, "status": session.status}

@router.post("/{session_id}/close")
def close_session(
    session_id: str,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status not in ("open", "active"):
        raise HTTPException(400, f"Cannot close session with status '{session.status}'")
    session.status = "pending_mp"
    session.closed_at = datetime.now(timezone.utc)
    db.commit()
    log_event(db, "session_close", user_id=current_user.id, role=current_user.role,
              session_id=session.id, client_ip=request.client.host if request.client else None)
    return {"session_id": session.id, "status": session.status,
            "message": "Session closed. MP will be notified."}

@router.get("/history")
def session_history(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    sessions = db.query(Session).order_by(Session.opened_at.desc()).limit(20).all()
    return [{"id": s.id, "date": s.date, "status": s.status,
             "total_cases": s.total_cases, "completed_cases": s.completed_cases}
            for s in sessions]
