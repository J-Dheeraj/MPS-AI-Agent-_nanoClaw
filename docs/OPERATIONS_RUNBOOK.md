# Operations Runbook

## Service objectives

- API availability: 99.5 percent per calendar month during declared operating hours.
- Non-LLM API p95 latency: below 2 seconds.
- Draft completion p95: below 120 seconds under the tested site load.
- Recovery point objective: 24 hours maximum; target 1 hour during MPS operations.
- Recovery time objective: 4 hours.
- Critical privacy or authorisation defects: disable drafting immediately and preserve evidence.

## Deployment

1. Replace every container tag in `.env.production` with an approved immutable digest.
2. Create `deploy/secrets/db_password.txt`, `jwt_secret.txt`, `metrics_token.txt`, and `bootstrap_admin_password.txt` using independent random values and permission mode `0600`. JWT and metrics secrets require at least 32 characters; the bootstrap password requires at least 16.
3. Place a reviewed `manifest.json` and its policy rule files in `policy/active`.
4. Run `docker compose --env-file .env.production -f deploy/compose.yaml config` and inspect the rendered configuration for exposed secrets or ports.
5. Run the migration service, then start the stack. Trust the Caddy internal CA only on managed client devices.
6. Log in with the bootstrap admin, change its password immediately, then rotate or remove the bootstrap secret. Confirm `/health/live`, `/health/ready`, a synthetic draft, final validation, audit verification, metrics, and encrypted backup.

## Incident priorities

- P1: suspected data disclosure, authorisation bypass, stolen signing or JWT key, audit-chain failure, or unsafe letter sent externally.
- P2: service unavailable during an MPS session, repeated draft corruption, database failure, or policy-manifest failure.
- P3: degraded latency, queue growth, individual client fault, or non-sensitive UI defect.

For P1, remove external access, revoke active tokens, preserve logs and database snapshots, notify the data and security owners, assess affected records, rotate relevant keys, and document the decision to restore service. Do not erase evidence during containment.

## Backup and restore

Run `scripts/backup-postgres.sh` from a restricted backup host. Backups are encrypted with an `age` recipient before being written and receive a SHA-256 checksum. Store the identity key separately from backups. Perform and record a restore test at least quarterly. A restore is not successful until migrations, audit verification, policy verification, and synthetic workflow tests pass.

## Routine controls

- Daily: review critical alerts, failed logins, failed generations, policy integrity, and disk capacity.
- Weekly: verify the audit chain and export its head hash to an independent log store; review privileged accounts and pending feedback.
- Monthly: patch dependencies, generate an SBOM, review access, test token revocation, and sample approved letters for quality.
- Quarterly: restore a backup, rotate operational secrets, run a tabletop privacy incident, and repeat load and security tests.
