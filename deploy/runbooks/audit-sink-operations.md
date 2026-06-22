# Runbook — External audit sink operations & validation

Status: procedure (v10 follow-up). The audit forwarder is implemented and
fail-safe (durable outbox, HTTPS-only, host allowlist, owner-token CAS,
Idempotency-Key), but the review notes the **sink itself** is assumed, not
proven. This runbook + the contract test close that.

## The contract the production sink MUST satisfy
The forwarder (`mps_server/services/audit.py`) POSTs `text/plain` bodies
(`ts\tentry_id\tentry_hash[\tsig]`) with a bearer token (and/or mTLS) and an
`Idempotency-Key` header (the audit entry hash). The sink must:
1. **Authenticate** — reject unauthenticated/invalid-token writes (401).
2. **Be idempotent** — a repeated Idempotency-Key stores exactly one record.
3. **Be append-only / immutable** — never overwrite or delete a stored head;
   reject a reused key with a different body (409).
4. **Be durable & retained** — persist to WORM/object-lock storage with a
   documented retention period; survive restarts.

## Validate a candidate sink before go-live
A runnable reference that satisfies the contract is at
`deploy/audit-sink/reference_sink.py`. Contract-test ANY sink:
```
AUDIT_SINK_CONTRACT_URL=https://your-sink/endpoint \
AUDIT_SINK_CONTRACT_TOKEN=... \
python3 -m pytest tests/test_audit_sink_contract.py -q
```
The suite (`tests/test_audit_sink_contract.py`) asserts properties 1–3 above.
Property 4 (WORM/retention) is infrastructure — verify it via the storage
backend's object-lock/retention configuration and record the evidence.

## Wiring NanoClaw to the sink (production)
Set in the server environment / Compose secrets:
- `AUDIT_CHECKPOINT_FORWARD_URL` = https URL of the sink (HTTPS enforced in prod).
- `AUDIT_CHECKPOINT_FORWARD_ALLOWED_HOSTS` = the sink host (SSRF guard).
- `AUDIT_CHECKPOINT_FORWARD_TOKEN` (secret) and/or client cert/key for mTLS.

## Outage handling
The outbox is durable: if the sink is down, heads queue and retry. Watch
`/health/audit-chain` → `forward_outbox.undelivered` and `oldest_age_seconds`
(alert `AuditForwardingStalled`). No data is lost; delivery resumes when the
sink returns. Owner-token CAS prevents a stale retry from clobbering a reclaim.

## Evidence to capture
Sink contract-test result, storage object-lock/retention config, auth method,
and an outage drill (stop the sink, confirm backlog grows then drains).
