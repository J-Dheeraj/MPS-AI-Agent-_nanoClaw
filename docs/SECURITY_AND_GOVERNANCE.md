# Security and Governance

## Accountabilities

- Service owner: accepts availability, support, and release risk.
- Data owner: approves data fields, purpose, access, retention, and deletion.
- Policy owner: approves sources, effective dates, withdrawals, and policy releases.
- Model owner: approves model and prompt versions against the evaluation set.
- Security owner: approves the threat model, vulnerability exceptions, and incident closure.

No person may approve their own feedback correction or policy proposal.

## Data lifecycle

Maintain a data inventory covering residents, cases, letters, feedback, audit events, logs, and backups. Define an approved retention period for each class before live data is used. Deletion must cover the primary database, derived exports, review proposals, logs where legally permitted, and eventual backup expiry. Masked NRIC and contextual case text remain personal data.

## Policy release rules

- Only HTTPS Singapore government sources on the configured allowlist are accepted.
- Every rule requires source title, URL, effective date, named validator, and proposal hash.
- Promotion verifies the review sidecar and original proposal bytes.
- Active releases are manifested and hash-verified at runtime.
- Withdrawal or expiry creates a new release; deployed files are never edited in place.

## Model change rules

Every model, prompt, validator, and policy release must pass the fixed regression set. Required gates include zero privacy-blocking failures, zero unsupported policy claims in sampled outputs, no RBAC regression, and no statistically material deterioration in vetter acceptance or edit distance. Roll back when a gate is breached.

## Required governance evidence

Before live use, approve a data protection impact assessment, threat model, acceptable-use policy, access matrix, retention schedule, incident response contacts, processor and hosting assessment, and pilot success metrics. Repository controls support this evidence but do not replace organisational approval.
