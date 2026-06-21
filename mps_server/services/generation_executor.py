"""Request-independent generation executor (v6 Critical #4).

The draft-generation body used to live inline in the WebSocket handler, so a
job could only be executed by a connected client. This module extracts that
body into `execute_job`, shared by:

  - the live WS path (streams the returned text for UX), and
  - the background worker (main.py lifespan) which claims `pending` jobs and
    runs them to completion with no client attached.

A crashed or disconnected job re-queued by the reaper is therefore finished by
the worker instead of being stranded until a human retries.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..correlation import new_correlation_id
from ..database import Letter
from ..services.audit import log_event
from ..services.generation_jobs import mark_completed, mark_failed
from ..services.ollama_client import (
    Priority,
    build_draft_messages,
    llm_queue,
    OLLAMA_MODEL,
    PROMPT_VERSION,
    PROMPT_SHA256,
)
from ..services.policy_store import load_policy_context
from ..services.validator import validate_letter_grounded, VALIDATOR_VERSION


def _derive_reappeal(db: Session, case):
    """Re-derive re-appeal context from the server-side parent relationship."""
    is_reappeal = not case.is_new_issue
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
    return is_reappeal, previous_content


async def execute_job(
    db: Session,
    job,
    *,
    actor_user=None,
    cid: str | None = None,
    is_reappeal: bool | None = None,
    previous_content: str | None = None,
    policy_bundle=None,
) -> dict:
    """Run a generation job to completion and persist the result.

    The live WS handler passes the already-derived context (actor user,
    correlation id, re-appeal flag, policy bundle) so behaviour is identical to
    the previous inline path. The background worker passes nothing and the
    executor re-resolves everything from `job.letter_id`, acting as a system
    actor in the audit log.

    Returns a result dict: {status, full_text, findings, letter_id, version,
    policy_sources, policy_version}. status is "completed", "blocked" or
    "error".
    """
    cid = cid or new_correlation_id()

    letter = db.query(Letter).filter(Letter.id == job.letter_id).first()
    if letter is None:
        mark_failed(db, job, "letter missing for job")
        return {"status": "error", "reason": "letter missing"}
    case = letter.case

    if is_reappeal is None:
        is_reappeal, previous_content = _derive_reappeal(db, case)

    if policy_bundle is None:
        policy_context, policy_sources, policy_version = load_policy_context(
            case.agency, case_text=case.notes or ""
        )
    else:
        policy_context, policy_sources, policy_version = policy_bundle

    messages = build_draft_messages(
        case_type=case.case_type,
        agency=case.agency,
        notes=case.notes or "",
        is_reappeal=is_reappeal,
        previous_letter=previous_content,
        rejection_reason=None,
        policy_context=policy_context,
    )
    priority = Priority.URGENT if case.urgency == "urgent" else Priority.NORMAL

    # Local import to avoid a circular import at module load (cases_router
    # imports from the letters layer); matches the prior inline pattern.
    from ..routers.cases_router import transition

    actor_id = actor_user.id if actor_user else None
    actor_role = actor_user.role if actor_user else "system"

    full_text = ""
    async for chunk in llm_queue.run(messages, priority=priority):
        full_text += chunk

    findings = validate_letter_grounded(full_text, policy_context)
    blocking = [finding for finding in findings if finding.severity == "block"]

    if blocking:
        transition(case, "drafted")
        letter.draft_content = None
        db.commit()
        log_event(
            db,
            "letter_blocked",
            user_id=actor_id,
            role=actor_role,
            case_id=case.id,
            letter_id=letter.id,
            letter_version=letter.version,
            details={"codes": [finding.code for finding in blocking]},
        )
        mark_failed(db, job, "blocked by validator")
        return {
            "status": "blocked",
            "full_text": full_text,
            "findings": findings,
            "letter_id": letter.id,
            "version": letter.version,
            "policy_sources": policy_sources,
            "policy_version": policy_version,
        }

    letter.draft_content = full_text
    letter.generation_meta = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
        "policy_version": policy_version,
        "policy_rule_ids": [src.get("rule_id") for src in policy_sources],
        "validator_version": VALIDATOR_VERSION,
        "warning_codes": [finding.code for finding in findings],
        "correlation_id": cid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    transition(case, "drafted")
    db.commit()
    mark_completed(db, job)
    log_event(
        db,
        "letter_drafted",
        user_id=actor_id,
        role=actor_role,
        case_id=case.id,
        letter_id=letter.id,
        letter_version=letter.version,
    )
    return {
        "status": "completed",
        "full_text": full_text,
        "findings": findings,
        "letter_id": letter.id,
        "version": letter.version,
        "policy_sources": policy_sources,
        "policy_version": policy_version,
    }
