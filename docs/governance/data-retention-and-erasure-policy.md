# Data Retention and Erasure Policy

**Status:** Active control (paired with implemented tooling)
**Owner:** _<MPS Data Owner — name to be assigned before pilot>_
**Last reviewed:** 2026-06-11
**Review cadence:** Quarterly

## Scope

Personal data held by the MPS AI Agent (NanoClaw):

| Field | Location | Classification |
|---|---|---|
| Resident name | `residents.name` | Personal data |
| Masked NRIC | `residents.nric_masked` | Personal data (identifier) |
| Contact number | `residents.contact` | Personal data |
| Case notes | `cases.notes` | Personal data (circumstantial) |
| Letter body | `letters.draft_content`, `letters.final_content` | Personal data |

Audit records (`audit_logs`) contain actor ids and event metadata but **not**
constituent free text; they are retained for the full audit-retention period and
are append-only (see the audit verification command).

## Retention rule

Constituent personal data is retained only while operationally required. Once
every case for a resident sits in a session that was **sent more than
`RETENTION_DAYS` ago** (default 365), the resident's personal data is purged.

Purge overwrites the personal fields above with `[REDACTED]`. The structural
shell of each case (id, case type, agency, status, timestamps) is retained for
reporting; personal data is not.

## Implemented controls

- **Retention sweep:** `python3 -m mps_server.retention --sweep`
  (`--dry-run` to report only). Run on a schedule (e.g. weekly cron). Every
  purge is audit-logged as `resident_pii_purged`.
- **Right to erasure (data-subject request):**
  `python3 -m mps_server.retention --delete-resident <resident_id>` purges one
  resident immediately, regardless of the retention window. Audit-logged as
  `data_subject_erasure`.
- **Backups:** `backup.sh` retains the last 14 encrypted snapshots; older
  snapshots are pruned, so purged data ages out of backups within the backup
  window. Verify backup age as part of the quarterly review.

## Operational checklist

1. Schedule the retention sweep (weekly) and capture its JSON output as evidence.
2. On a verified data-subject erasure request, run `--delete-resident` and file
   the audit event id with the request record.
3. Each quarter: confirm the sweep has run, confirm backup pruning, and record a
   signed-off review against this document.

## Open items before real-data use

- Assign the named Data Owner and Approving Authority.
- Confirm the lawful retention period with the MP's office (the 365-day default
  is a placeholder).
- Add legal-hold handling (suspend purge for a flagged resident) if required by
  the office's records policy.
