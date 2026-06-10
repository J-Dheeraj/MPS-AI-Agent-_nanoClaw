#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGPASSWORD_FILE:?PGPASSWORD_FILE is required}"
: "${AGE_RECIPIENT:?AGE_RECIPIENT is required}"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/mps-agent}"
RETENTION_DAYS="${RETENTION_DAYS:-35}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="$BACKUP_DIR/mps-$STAMP.dump.age"

install -d -m 0700 "$BACKUP_DIR"
export PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
umask 077

pg_dump --format=custom --no-owner --no-acl \
  | age --recipient "$AGE_RECIPIENT" --output "$OUTPUT"
sha256sum "$OUTPUT" > "$OUTPUT.sha256"
find "$BACKUP_DIR" -type f -mtime "+$RETENTION_DAYS" -delete

echo "Encrypted backup written: $OUTPUT"
