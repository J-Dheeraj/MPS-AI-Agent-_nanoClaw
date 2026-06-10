#!/usr/bin/env bash
set -euo pipefail

: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=restore-mps-database}"
[ "$RESTORE_CONFIRM" = "restore-mps-database" ] || { echo "Invalid confirmation" >&2; exit 2; }
: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGPASSWORD_FILE:?PGPASSWORD_FILE is required}"
: "${AGE_IDENTITY_FILE:?AGE_IDENTITY_FILE is required}"

BACKUP="${1:?Usage: restore-postgres.sh <backup.dump.age>}"
sha256sum --check "$BACKUP.sha256"
export PGPASSWORD="$(cat "$PGPASSWORD_FILE")"

age --decrypt --identity "$AGE_IDENTITY_FILE" "$BACKUP" \
  | pg_restore --clean --if-exists --no-owner --no-acl --dbname "$PGDATABASE"

echo "Restore completed. Run alembic upgrade head and the smoke tests before reopening access."
