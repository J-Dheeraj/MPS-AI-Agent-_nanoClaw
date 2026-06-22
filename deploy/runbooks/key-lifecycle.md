# Runbook — Signing-key lifecycle & break-glass

Status: procedure (v10 follow-up). The system uses Ed25519 keys for three
purposes; the code is in place but the review notes enrolment, rotation,
revocation, recovery and separation-of-duties are not *documented*. This runbook
closes the documentation gap; the organisation must operate it.

## Keys in use
| Key | Used by | Public-key consumer |
|-----|---------|--------------------|
| Policy signing | `policy_keys.py` (Hermes signs policy releases) | NanoClaw verifies via `POLICY_PUBLIC_KEY` |
| Reviewer decision signing | `sign_decision.py` (Hermes reviewers) | `promote_approved.py` via `REVIEWER_REGISTRY` |
| Audit checkpoint signing | `AUDIT_CHECKPOINT_SIGNING_KEY` (NanoClaw) | `/health/audit-chain` via `AUDIT_CHECKPOINT_PUBLIC_KEY` |

## Storage & separation of duties
- Private keys live in a managed store (OS keychain / smart card / KMS / Docker
  secret), **never** in the repo or images. Compose mounts them as secrets.
- The person who *generates/holds* a private key must differ from the person who
  *deploys* the corresponding public key (two-person control for production).

## Enrolment (new reviewer / new signing key)
```
# generate an Ed25519 keypair (reviewer example)
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; \
from cryptography.hazmat.primitives import serialization as s; k=Ed25519PrivateKey.generate(); \
open('reviewer.key','wb').write(k.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.NoEncryption())); \
open('reviewer.pub','wb').write(k.public_key().public_bytes(s.Encoding.PEM,s.PublicFormat.SubjectPublicKeyInfo))"
```
Add the **public** key to the relevant registry (`REVIEWER_REGISTRY`,
`POLICY_PUBLIC_KEY`, or `AUDIT_CHECKPOINT_PUBLIC_KEY`) under change control.

## Rotation (scheduled, e.g. annually)
1. Generate the new keypair; distribute the new public key to verifiers first.
2. Begin signing new artefacts with the new key; keep the old public key in the
   verifier set until all in-flight artefacts signed with the old key are retired.
3. Remove the old public key once no valid artefact depends on it.

## Revocation (compromise)
1. Remove the compromised public key from the verifier registry immediately —
   verification then fails closed for anything it signed.
2. Re-sign still-valid artefacts with a fresh key.
3. For audit keys: a revoked audit-signing key means checkpoint signatures from
   it no longer verify; investigate the window for tampering using the external
   sink copy.

## Break-glass (lost key / unable to sign)
- Policy/reviewer: promotion is blocked by design (fail-closed). Generate and
  enrol a new key under two-person control; do not bypass signature checks.
- Audit: if the signing key is lost, generate a new one and roll the public key;
  the chain remains verifiable for entries signed before the loss.

## Evidence to capture
Key IDs, enrolment/rotation/revocation dates, approver pairs, and the change
tickets — attach to the security record.
