# MPS AI Agent — Governance Pack

Operational privacy and records-governance controls for the MPS AI Agent.
Each policy below is paired with an **implemented** control, not an intention.

| Document | Paired control |
|---|---|
| [Data Retention and Erasure Policy](data-retention-and-erasure-policy.md) | `mps_server/retention.py` (`--sweep`, `--delete-resident`) |
| [Data Protection Impact Assessment](data-protection-impact-assessment.md) | Whole-system control inventory; sign-off gate before real data |
| [Access Review Procedure](access-review-procedure.md) | `mps_server/access_review.py` |
| [Incident Response Runbook](incident-response-runbook.md) | `verify_audit`, `backup.sh --restore`, account deactivation |
| [Data Inventory](data-inventory.md) | Schema map of personal data + classification |

## Before real constituent data

The DPIA section 4 lists the controls that must be accepted or closed, and the
sign-off table that must be completed, before the system processes real data.
Named owners (Data Owner, Data Protection lead, Operations lead, Account
Administrator, Approving Authority) must be assigned — they are placeholders in
these documents today.
