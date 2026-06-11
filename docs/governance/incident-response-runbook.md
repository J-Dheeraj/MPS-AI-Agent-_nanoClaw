# Incident Response Runbook

**Owner:** _<Operations lead — to be assigned>_
**Last reviewed:** 2026-06-11

Covers a suspected breach, data-integrity event, or availability incident for
the MPS AI Agent. Keep a printed copy; the system is LAN-only.

## Roles

- **Incident Lead:** coordinates response, owns the decision log.
- **Data Owner:** assesses constituent-data impact, owns notification decisions.
- **Operator:** executes containment and recovery steps below.

## Severity

| Sev | Definition | Examples |
|---|---|---|
| 1 | Confirmed constituent-data exposure or integrity loss | DB exfiltrated, audit chain broken, forged policy release |
| 2 | Credible threat, no confirmed exposure | Stolen laptop with client, suspicious auth pattern |
| 3 | Availability / degradation | Server down, model unavailable, queue saturated |

## First 30 minutes

1. **Record** the time, reporter, and first symptom in the decision log.
2. **Contain.** For Sev 1/2: take the server off the network (it is LAN-only —
   disconnect the host or stop the service). Do not wipe; preserve evidence.
3. **Verify audit integrity:** `python3 -m mps_server.verify_audit`. A failure
   is itself a Sev 1 finding — record the first broken row.
4. **Notify** the Incident Lead and Data Owner.

## Investigation

- Review `audit_logs` for the actor, time window, and affected case/letter ids.
- Review server logs and `/metrics` for the anomaly window.
- For a suspected forged policy release: re-run policy load — fail-closed
  verification (`POLICY_PUBLIC_KEY`) will reject an unsigned/forged manifest;
  compare `manifest.json.sig` `key_id` against the trusted key.
- For suspected token theft: revoke the affected user (deactivate account →
  existing tokens fail revocation check) and rotate `SECRET_KEY` if broad.

## Recovery

1. Restore from a verified backup if integrity is compromised:
   `bash backup.sh --restore <backup-dir>`.
2. Re-run `verify_audit` and a smoke test (`tests/e2e_api_test.sh`) before
   returning the service to the network.
3. If personal data was exposed, the Data Owner decides on data-subject and
   regulator notification per the office's obligations.

## Post-incident

- Complete a lessons-learned within 5 working days.
- File any new control as a tracker item; update this runbook.

## Contacts

_<Fill in: Incident Lead, Data Owner, MP's office contact, IT support.>_
