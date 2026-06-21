import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session as DBSession

from ..auth import require_volunteer, resolve_user_from_token
from ..database import Case, Letter, User, get_db
from ..services.audit import log_event
from ..services.ollama_client import (
    Priority,
    build_draft_messages,
    build_qa_messages,
    llm_queue,
    OLLAMA_MODEL,
    PROMPT_VERSION,
    PROMPT_SHA256,
)
from ..services.policy_store import PolicyStoreError, load_policy_context
from ..correlation import new_correlation_id
from ..services.validator import (
    validate_letter,
    validate_letter_grounded,
    VALIDATOR_VERSION,
)

router = APIRouter(prefix="/letters", tags=["letters"])


class LetterUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class DraftRequest(BaseModel):
    case_id: str
    is_reappeal: bool = False


def _can_access_case(user: User, case: Case) -> bool:
    return user.role in {"vetter", "admin"} or case.volunteer_id == user.id


def _accessible_letter(db: DBSession, letter_id: str, user: User) -> Letter:
    letter = db.query(Letter).filter(Letter.id == letter_id).first()
    if not letter or not _can_access_case(user, letter.case):
        # Do not reveal whether an inaccessible object exists.
        raise HTTPException(404, "Letter not found")
    return letter


async def _authenticate_websocket(
    websocket: WebSocket,
    db: DBSession,
    allowed_roles: set[str],
) -> User | None:
    """Authenticate from the first message so bearer tokens never enter URLs."""
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if message.get("type") != "auth" or not isinstance(message.get("token"), str):
            raise ValueError("missing authentication message")
        user = resolve_user_from_token(message["token"], db)
        if user.role not in allowed_roles:
            raise ValueError("role not permitted")
        await websocket.send_json({"type": "authenticated"})
        return user
    except Exception:
        await _safe_ws_error(websocket, "Unauthorised")
        await _safe_ws_close(websocket, 1008)
        return None


async def _safe_ws_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "text": message})
    except Exception:
        pass


async def _safe_ws_close(websocket: WebSocket, code: int = 1000) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


def _blocking_findings(content: str, policy_context: str = ""):
    return [
        finding
        for finding in validate_letter_grounded(content, policy_context)
        if finding.severity == "block"
    ]


@router.get("/{letter_id}")
def get_letter(
    letter_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(require_volunteer),
):
    letter = _accessible_letter(db, letter_id, current_user)
    return {
        "id": letter.id,
        "case_id": letter.case_id,
        "draft_content": letter.draft_content,
        "final_content": letter.final_content,
        "version": letter.version,
        "status": letter.status,
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
    letter = _accessible_letter(db, letter_id, current_user)
    if letter.is_frozen:
        raise HTTPException(403, "Letter has been submitted to MP and cannot be edited")

    blocking = _blocking_findings(body.content)
    if blocking:
        raise HTTPException(
            422,
            detail={
                "message": "Letter failed mandatory safety checks",
                "findings": [
                    {"code": finding.code, "message": finding.message}
                    for finding in blocking
                ],
            },
        )

    letter.draft_content = body.content
    db.commit()
    log_event(
        db,
        "letter_edited",
        user_id=current_user.id,
        role=current_user.role,
        case_id=letter.case_id,
        letter_id=letter_id,
        letter_version=letter.version,
        client_ip=request.client.host if request.client else None,
    )
    return {"id": letter.id, "status": "updated"}


@router.websocket("/ws/draft")
async def draft_letter_ws(websocket: WebSocket, db: DBSession = Depends(get_db)):
    """Generate a draft using authenticated, server-owned case context."""
    _cid = new_correlation_id()
    await websocket.accept()
    user = await _authenticate_websocket(
        websocket, db, {"volunteer", "vetter", "admin"}
    )
    if not user:
        return

    try:
        request_data = DraftRequest(
            **await asyncio.wait_for(websocket.receive_json(), timeout=30)
        )
    except (asyncio.TimeoutError, ValidationError, TypeError):
        await _safe_ws_error(websocket, "Invalid or timed-out draft request")
        await _safe_ws_close(websocket, 1008)
        return

    case = db.query(Case).filter(Case.id == request_data.case_id).first()
    if not case or not _can_access_case(user, case):
        await _safe_ws_error(websocket, "Case not found")
        await _safe_ws_close(websocket, 1008)
        return
    if case.status not in {"assigned", "drafted"}:
        await _safe_ws_error(websocket, "Case is not in a draftable state")
        await _safe_ws_close(websocket, 1008)
        return

    # Re-appeal context is derived from the server-side parent relationship.
    # The client cannot nominate an arbitrary letter from another case.
    is_reappeal = bool(request_data.is_reappeal or not case.is_new_issue)
    previous_content = None
    if is_reappeal and case.parent_case_id:
        previous_letter = (
            db.query(Letter)
            .filter(Letter.case_id == case.parent_case_id)
            .order_by(Letter.version.desc())
            .first()
        )
        if previous_letter:
            previous_content = (
                previous_letter.final_content or previous_letter.draft_content
            )

    try:
        policy_context, policy_sources, policy_version = load_policy_context(case.agency, case_text=case.notes or "")
    except PolicyStoreError:
        await _safe_ws_error(websocket, "Approved policy store failed integrity checks")
        await _safe_ws_close(websocket, 1011)
        return

    queue_position = llm_queue.depth()
    if queue_position > 0:
        await websocket.send_json(
            {
                "type": "queue",
                "queue_position": queue_position,
                "message": f"Position {queue_position} in queue",
            }
        )

    letter = (
        db.query(Letter)
        .filter(
            Letter.case_id == case.id,
            Letter.status.in_(["draft", "returned"]),
        )
        .first()
    )
    if not letter:
        letter = Letter(case_id=case.id, status="draft", version=1)
        db.add(letter)
    else:
        letter.version += 1
    letter.draft_content = None

    from .cases_router import transition

    transition(case, "drafting")
    db.commit()

    # Durable job tracking (V4-C1): one job per letter version. A concurrent
    # duplicate request for the same version is rejected; a failed or stale
    # job for the version is re-leased and re-run.
    from ..services.generation_jobs import (
        create_job, mark_running, mark_completed, mark_failed,
    )
    job, job_created = create_job(
        db, letter_id=letter.id,
        idempotency_key=f"letter-{letter.id}-v{letter.version}",
    )
    if not job_created and job.status == "running":
        await _safe_ws_error(websocket, "Generation already in progress for this letter")
        await _safe_ws_close(websocket, 1008)
        return
    mark_running(db, job)

    from ..services.generation_executor import execute_job

    try:
        # Single source of truth: the same executor the background worker runs.
        # The WS path passes the already-derived context so behaviour is
        # identical to the previous inline generation; it then streams the
        # returned text for UX. A disconnected/crashed job is finished by the
        # worker instead (main.py lifespan), no client reconnect required.
        result = await execute_job(
            db, job,
            actor_user=user,
            cid=_cid,
            is_reappeal=is_reappeal,
            previous_content=previous_content,
            policy_bundle=(policy_context, policy_sources, policy_version),
        )
        if result["status"] == "blocked":
            await _safe_ws_error(
                websocket, "Generated draft failed mandatory safety checks"
            )
            return
        if result["status"] != "completed":
            await _safe_ws_error(websocket, "Draft generation failed")
            return

        full_text = result["full_text"]
        findings = result["findings"]
        for offset in range(0, len(full_text), 256):
            await websocket.send_json(
                {"type": "chunk", "text": full_text[offset : offset + 256]}
            )
        await websocket.send_json(
            {
                "type": "done",
                "letter_id": letter.id,
                "version": letter.version,
                "text": full_text,
                "warnings": [
                    {
                        "severity": finding.severity,
                        "code": finding.code,
                        "message": finding.message,
                    }
                    for finding in findings
                ],
                "policy_sources": result["policy_sources"],
                "policy_version": result["policy_version"],
            }
        )
    except WebSocketDisconnect:
        if job.status == "running":
            mark_failed(db, job, "client disconnected")
    except Exception:
        if job.status == "running":
            mark_failed(db, job, "generation error")
        if case.status == "drafting":
            transition(case, "drafted")
            db.commit()
        await _safe_ws_error(websocket, "Draft generation failed")
    finally:
        await _safe_ws_close(websocket)


@router.websocket("/ws/qa")
async def qa_ws(websocket: WebSocket, db: DBSession = Depends(get_db)):
    """Answer only from manifested, reviewed policy rules."""
    await websocket.accept()
    user = await _authenticate_websocket(
        websocket, db, {"volunteer", "vetter", "admin"}
    )
    if not user:
        return

    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        question = str(data.get("question", "")).strip()
        if not question or len(question) > 2_000:
            await _safe_ws_error(
                websocket, "Question must be between 1 and 2000 characters"
            )
            return
        agency = str(data.get("agency", "")).strip().upper()
        try:
            policy_context, policy_sources, policy_version = load_policy_context(agency)
        except PolicyStoreError:
            await _safe_ws_error(websocket, "Approved policy store failed integrity checks")
            return
        if not policy_context:
            await _safe_ws_error(
                websocket, "No approved policy sources are available for this agency"
            )
            return

        messages = build_qa_messages(question, context=policy_context)
        async for chunk in llm_queue.run(messages, priority=Priority.LOW):
            await websocket.send_json({"type": "chunk", "text": chunk})
        await websocket.send_json(
            {
                "type": "done",
                "policy_sources": policy_sources,
                "policy_version": policy_version,
            }
        )
    except WebSocketDisconnect:
        pass
    except Exception:
        await _safe_ws_error(websocket, "Policy Q&A failed")
    finally:
        await _safe_ws_close(websocket)
