"""Per-request correlation IDs (I5).

A single ID is generated at the HTTP/WebSocket entry point and made available
through a contextvar so logs, the generation job, Ollama call logs and audit
events can all be tied to one request without threading an argument through
every function.
"""
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex
    _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> str:
    cid = (cid or "").strip() or uuid.uuid4().hex
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()
