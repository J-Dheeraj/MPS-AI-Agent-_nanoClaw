# Runbook — PostgreSQL backup, restore & failover drill

Status: procedure (v10 follow-up). The review flags that backup restoration,
failover and RPO/RTO are *unverified* controls. This runbook makes the procedure
concrete and repeatable; the organisation must **execute** it on the production
topology and record the evidence (timings, success) to close the gap.

## Targets (set with the data owner before the pilot)
- **RPO** (max data loss): e.g. ≤ 5 min (continuous WAL archiving) or ≤ 24h
  (nightly base backup) — choose and document.
- **RTO** (max downtime): e.g. ≤ 30 min for a single-node restore.

## Backup (nightly base + continuous WAL)
```
# base backup
pg_basebackup -h $PGHOST -U $PGUSER -D /backups/base-$(date +%F) -Ft -z -Xs -P
# verify it is readable
tar -tzf /backups/base-$(date +%F)/base.tar.gz >/dev/null && echo OK
```
Store backups off the database host (different volume/site). Encrypt at rest.

## Restore drill (run quarterly; record start/end time)
1. Provision a clean PostgreSQL 16 instance (same minor version).
2. Restore the latest base backup into its data dir; replay WAL to the latest
   archived segment (point-in-time recovery via `recovery.conf`/`postgresql.auto.conf`).
3. Start the instance; confirm `alembic current` equals the app's
   `EXPECTED_SCHEMA_REVISION` (currently `20260621_03`).
4. **Integrity check:** point a NanoClaw instance at the restored DB and call
   `GET /health/audit-chain` with the metrics token — it must return
   `status: ok` and a `head_hash` matching the external checkpoint sink.
5. Record actual RTO (time from "start restore" to "health green").

## Failover (single-site today — documents the gap)
The current topology is single-site with one Ollama path. True HA requires a
standby (streaming replication) and a promotion procedure:
```
# on standby, when primary is lost:
pg_ctl promote -D $PGDATA
# repoint the app DATABASE_URL / connection string to the promoted node
```
Until a standby exists, the realistic recovery is the restore drill above.
**Out of scope for the repo:** provisioning the standby, the load balancer/VIP,
and Ollama failover — these are infrastructure to be stood up and tested.

## Evidence to capture (attach to the release record)
- Date of drill, backup timestamp used, measured RPO and RTO.
- `/health/audit-chain` output post-restore (head matches sink).
- Any deviations and remediation.
