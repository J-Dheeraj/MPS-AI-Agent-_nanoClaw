# Data Inventory

**Owner:** _<Data Owner — to be assigned>_
**Last reviewed:** 2026-06-11

Every store of personal or sensitive data in the MPS AI Agent, its
classification, retention, and the control that governs it.

| Data | Store | Classification | Retention | Control |
|---|---|---|---|---|
| Resident name | `residents.name` | Personal | Until retention sweep | Retention policy / erasure |
| Masked NRIC | `residents.nric_masked` | Personal identifier (masked) | Until retention sweep | Mask enforced at all entry points |
| Contact number | `residents.contact` | Personal | Until retention sweep | Retention policy / erasure |
| Case notes | `cases.notes` | Personal (circumstantial) | Until retention sweep | Retention policy; never stores full NRIC |
| Letter body | `letters.draft_content`, `letters.final_content` | Personal | Until retention sweep | Retention policy; factual-support + privacy validation |
| Generation provenance | `letters.generation_meta` | Operational metadata | With letter | Model/prompt/policy version trace |
| User accounts | `users` | Staff credentials | While account active | Access review; bcrypt hashing; lockout |
| Audit log | `audit_logs` | Operational, append-only | Full audit period | Hash chain + verification command |
| Anonymised feedback | `feedback_entries` | Anonymised corrections | Until promoted/expired | Structured redaction, fail-closed export |
| Approved policy | `policy/active/*.json` | Public (government source) | Versioned releases | Ed25519-signed manifest |
| Backups | `backups/` | Mirror of above | Last 14 snapshots | Encrypted; pruned on rotation |

## Data flows

- Constituent data is entered by a volunteer, stored locally, used to generate a
  draft via the **local** model, reviewed by a vetter, and frozen on approval.
- No constituent data leaves the LAN. Inference and embeddings are on-premises.
- Only **anonymised, PII-screened** feedback is exported to the policy-improvement
  workflow, and only after fail-closed redaction.

## Notes

- Full NRIC is never stored; masking is enforced at the client, API, and MCP
  tool boundary.
- Encryption at rest for the database is an outstanding control (tracker I8).
