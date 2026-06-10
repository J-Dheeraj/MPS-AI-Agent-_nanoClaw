import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession
from ..database import Case, Letter, get_db, User
from ..auth import require_volunteer, decode_token, get_db as auth_get_db
from ..services.audit import log_event
from ..services.ollama_client import (llm_queue, Priority,
    build_draft_messages, build_qa_messages)
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/letters", tags=["letters"])

class LetterUpdate(BaseModel):
    content: str

class DraftRequest(BaseModel):
    case_id:         str
    notes:           str
    is_reappeal:     bool = False
    previous_letter_id: Optional[str] = None
    rejection_reason:   Optional[str] = None

@router.get("/{letter_id}")
def get_letter(
    letter_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    letter = db.query(Letter).filter(Letter.id == letter_id).first()
    if not letter:
        raise HTTPException(404, "Letter not found")
    return {
        "id": letter.id, "case_id": letter.case_id,
        "draft_content": letter.draft_content,
        "final_content": letter.final_content,
        "version": letter.version, "status": letter.status,
        "vetter_comment": letter.vetter_comment,
        "is_frozen": letter.is_frozen,
    }

@router.put("/{letter_id}")
def update_letter(
    letter_id: str,
    body: LetterUpdate,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    """
    Volunteer or vetter edits a draft letter.
    Vetters edit the final text directly before submitting to MP via POST /vetter-submit.
    Frozen letters (already submitted to MP) cannot be edited.
    """
    letter = db.query(Letter).filter(Letter.id == letter_id).first()
    if not letter:
        raise HTTPException(404, "Letter not found")
    if letter.is_frozen:
        raise HTTPException(403, "Letter has been submitted to MP — cannot be edited")
    # Volunteers update draft_content; vetters update both (their edit becomes the final)
    letter.draft_content = body.content
    db.commit()
    log_event(db, "letter_edited", user_id=current_user.id, role=current_user.role,
              letter_id=letter_id, letter_version=letter.version,
              client_ip=request.client.host if request.client else None)
    return {"id": letter.id, "status": "updated"}

@router.websocket("/ws/draft")
async def draft_letter_ws(websocket: WebSocket, token: str, db: DBSession = Depends(get_db)):
    """
    WebSocket endpoint for streaming letter draft.
    Client sends: {case_id, notes, is_reappeal, previous_letter_id, rejection_reason}
    Server streams: {type: chunk|done|error, text, letter_id, queue_position}
    """
    await websocket.accept()

    # Authenticate
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.send_json({"type": "error", "text": "Unauthorised"})
            await websocket.close()
            return
    except Exception:
        await websocket.send_json({"type": "error", "text": "Unauthorised"})
        await websocket.close()
        return

    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "text": "Timeout waiting for request"})
        await websocket.close()
        return

    case_id = data.get("case_id")
    notes   = data.get("notes", "")
    is_reappeal = data.get("is_reappeal", False)
    prev_letter_id = data.get("previous_letter_id")
    rejection_reason = data.get("rejection_reason")

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        await websocket.send_json({"type": "error", "text": "Case not found"})
        await websocket.close()
        return

    # Get previous letter content if re-appeal
    prev_content = None
    if prev_letter_id:
        prev_letter = db.query(Letter).filter(Letter.id == prev_letter_id).first()
        if prev_letter:
            prev_content = prev_letter.final_content or prev_letter.draft_content

    # Tell client queue position
    queue_pos = llm_queue.depth()
    if queue_pos > 0:
        await websocket.send_json({
            "type": "queue",
            "queue_position": queue_pos,
            "message": f"Position {queue_pos} in queue — drafting will begin shortly"
        })

    # Create or update letter record
    letter = (db.query(Letter).filter(Letter.case_id == case_id,
              Letter.status.in_(["draft", "returned"])).first())
    if not letter:
        letter = Letter(case_id=case_id, status="draft", version=1)
        db.add(letter)
    else:
        letter.version += 1
    letter.draft_content = ""
    case.status = "drafting"
    db.commit()

    # Build messages
    priority = Priority.URGENT if case.urgency == "urgent" else Priority.NORMAL
    messages = build_draft_messages(
        case_type=case.case_type,
        agency=case.agency,
        notes=notes,
        is_reappeal=is_reappeal,
        previous_letter=prev_content,
        rejection_reason=rejection_reason,
    )

    # Stream response
    full_text = ""
    try:
        async for chunk in llm_queue.run(messages, priority=priority):
            full_text += chunk
            await websocket.send_json({"type": "chunk", "text": chunk})

        # Save completed draft
        letter.draft_content = full_text
        case.status = "drafted"
        db.commit()

        log_event(db, "letter_drafted", user_id=user.id, role=user.role,
                  case_id=case_id, letter_id=letter.id, letter_version=letter.version)

        await websocket.send_json({
            "type": "done",
            "letter_id": letter.id,
            "version": letter.version,
            "text": full_text,
        })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})
    finally:
        await websocket.close()

@router.websocket("/ws/qa")
async def qa_ws(websocket: WebSocket, token: str, db: DBSession = Depends(get_db)):
    """
    WebSocket for streaming policy Q&A.
    Client sends: {question, case_id (optional)}
    Server streams: {type: chunk|done, text}
    """
    await websocket.accept()
    try:
        payload = decode_token(token)
        user = db.query(User).filter(User.id == payload.get("sub")).first()
        if not user:
            await websocket.send_json({"type": "error", "text": "Unauthorised"})
            await websocket.close()
            return
    except Exception:
        await websocket.send_json({"type": "error", "text": "Unauthorised"})
        await websocket.close()
        return

    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        question = data.get("question", "")
        messages = build_qa_messages(question)

        async for chunk in llm_queue.run(messages, priority=Priority.LOW):
            await websocket.send_json({"type": "chunk", "text": chunk})

        await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})
    finally:
        await websocket.close()
