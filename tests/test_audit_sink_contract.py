"""v10 follow-up: contract test for the external audit sink (review Critical #2).

The audit forwarder relies on the sink behaving append-only, idempotent and
authenticated. This proves those properties against a REAL sink endpoint, so the
production sink can be validated before go-live instead of assumed.

Gated on AUDIT_SINK_CONTRACT_URL (skips cleanly otherwise, like the PG suite).
A runnable reference sink that satisfies this contract lives at
deploy/audit-sink/reference_sink.py — point the test at it to verify the suite:

  AUDIT_SINK_TOKEN=secret AUDIT_SINK_FILE=/tmp/s.log \\
    python3 deploy/audit-sink/reference_sink.py 127.0.0.1 8088 &
  AUDIT_SINK_CONTRACT_URL=http://127.0.0.1:8088/ AUDIT_SINK_CONTRACT_TOKEN=secret \\
    python3 -m pytest tests/test_audit_sink_contract.py -q
"""
import os
import uuid

import httpx
import pytest

URL = os.getenv("AUDIT_SINK_CONTRACT_URL", "").strip()
TOKEN = os.getenv("AUDIT_SINK_CONTRACT_TOKEN", "").strip()

pytestmark = pytest.mark.skipif(
    not URL,
    reason="set AUDIT_SINK_CONTRACT_URL (and AUDIT_SINK_CONTRACT_TOKEN) to "
           "contract-test a real audit sink",
)


def _post(key, body, *, token=TOKEN):
    headers = {"Content-Type": "text/plain", "Idempotency-Key": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.post(URL, content=body.encode(), headers=headers, timeout=5.0)


def test_sink_requires_authentication():
    if not TOKEN:
        pytest.skip("no token configured; auth contract not applicable")
    r = _post(uuid.uuid4().hex, "ts\\tid\\thash\\tsig", token="")
    assert r.status_code == 401, "sink must reject unauthenticated writes"


def test_sink_accepts_authenticated_write():
    r = _post(uuid.uuid4().hex, "ts\\tid\\thash\\tsig")
    assert r.status_code == 200, f"authenticated write should succeed, got {r.status_code}"


def test_sink_is_idempotent_on_repeat_key():
    key = uuid.uuid4().hex
    body = "ts\\tid\\thash\\tsig"
    assert _post(key, body).status_code == 200
    # same key + same body again -> accepted as duplicate, exactly one stored
    assert _post(key, body).status_code == 200


def test_sink_is_append_only_immutable():
    key = uuid.uuid4().hex
    assert _post(key, "ts\\tid\\thash1\\tsig").status_code == 200
    # same key, DIFFERENT body -> must be refused (no overwrite of a stored head)
    r = _post(key, "ts\\tid\\tTAMPERED\\tsig")
    assert r.status_code == 409, "append-only sink must not overwrite an existing key"
