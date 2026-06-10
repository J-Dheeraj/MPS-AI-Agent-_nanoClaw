# Production Release Gate

A release is eligible only when every mandatory item is evidenced:

- All Python, JavaScript, Rust, authorisation, migration, and pipeline tests pass from a clean checkout.
- Dependency and secret scans have no unresolved critical or high findings.
- SBOMs exist for the server and both desktop applications.
- Container base images and CI actions are pinned to reviewed immutable digests or commits.
- Database migration and rollback or restore are tested on production-like PostgreSQL.
- Backup restore, audit verification, policy-manifest verification, and token revocation are demonstrated.
- TLS configuration passes the approved internal security test and managed clients trust only the intended CA.
- Load testing meets the declared concurrency, p95 latency, queue-age, and error-rate thresholds.
- Prompt-injection, privacy, unsupported-claim, and policy-regression evaluations meet their thresholds.
- A penetration test has no unresolved critical or high findings.
- The DPIA, threat model, access matrix, retention schedule, incident plan, and operational ownership are approved.
- A rollback decision-maker and tested rollback package are identified.

Passing repository tests alone is not a production approval. The release record must link to the external evidence above.
