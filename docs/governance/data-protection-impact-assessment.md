# Data Protection Impact Assessment (DPIA)

**Status:** Draft for completion before real-data pilot
**Owner:** _<Data Protection lead — to be assigned>_
**Last reviewed:** 2026-06-11

This DPIA must be completed and signed off by the accountable authority before
any real constituent data is processed. The sections below are pre-filled from
the system as built; the assessor confirms, amends, and signs.

## 1. Processing overview

- **Purpose:** Assist MPS volunteers and vetters in drafting appeal letters to
  government agencies on behalf of constituents, with mandatory human approval.
- **Data subjects:** Constituents attending Meet-the-People Sessions.
- **Personal data:** Name, masked NRIC, contact number, case circumstances,
  letter text. Full NRIC is never stored (masked at every entry point).
- **Processing location:** On-premises only. Inference runs on a local Ollama
  model; no constituent data leaves the LAN. No cloud model is used.

## 2. Necessity and proportionality

- The data collected is limited to what is required to draft and track an appeal.
- NRIC is masked; only the masked form is stored.
- Conversational memory is disabled for constituent-facing profiles.
- Feedback used to improve policy skills is anonymised and PII-screened before
  it leaves the case store (structured redactor, fail-closed export).

## 3. Risks and mitigations (as built)

| Risk | Mitigation | Status |
|---|---|---|
| Unauthorised cross-case access | Object-level authorisation on REST + WebSocket; role checks; token revocation | Implemented |
| Token theft from disk | JWT held in memory only; not persisted | Implemented |
| Credentials in transit | TLS mandatory (client enforces HTTPS/WSS); token in WS message body, not URL | Implemented |
| Hallucinated / stale policy advice | Approved policy retrieval + deterministic factual-support check blocks ungrounded thresholds | Implemented |
| Forged policy release | Ed25519-signed manifest; fail-closed verification | Implemented |
| Personal data kept too long | Retention sweep + erasure command | Implemented |
| Tampered audit trail | Hash-chained, advisory-locked, ORM-immutable audit; verification command | Implemented (DB-role revoke + external anchor outstanding) |
| Data egress via messaging | Telegram disabled on constituent profiles | Implemented |

## 4. Residual risk and outstanding controls

- Database encryption at rest (SQLite/PostgreSQL) — outstanding (I8).
- External, independent audit anchoring — outstanding (V-H9).
- Endpoint rate limiting / MFA — outstanding (V-H5).
- Named owners and approval authority — to be assigned.

## 5. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Data Owner | | | |
| Data Protection lead | | | |
| Approving Authority (MP / office) | | | |

The system must not process real constituent data until this DPIA is signed and
the outstanding controls in section 4 are accepted or closed.
