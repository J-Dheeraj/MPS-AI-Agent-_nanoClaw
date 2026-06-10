#!/usr/bin/env bash
# backup.sh — back up the MPS database and skill files.
# Run before every MPS night:  bash backup.sh
# Restore:                     bash backup.sh --restore <backup-dir>
set -euo pipefail

cd "$(dirname "$0")"
BACKUP_ROOT="backups"
DB="mps_server/mps.db"
SKILLS="groups/mps-volunteers/skills"

if [ "${1:-}" = "--restore" ]; then
  SRC="${2:?Usage: bash backup.sh --restore backups/<timestamp>}"
  [ -d "$SRC" ] || { echo "ERROR: $SRC not found" >&2; exit 1; }
  echo "Restoring from $SRC ..."
  [ -f "$SRC/mps.db" ] && cp "$SRC/mps.db" "$DB" && chmod 600 "$DB"
  [ -d "$SRC/skills" ] && cp -r "$SRC/skills/." "$SKILLS/"
  echo "Restore complete. Restart the server."
  exit 0
fi

STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"

if [ -f "$DB" ]; then
  # Use SQLite's online backup (safe while the server is running) when
  # the sqlite3 CLI is available; fall back to a plain copy otherwise.
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB" ".backup '$DEST/mps.db'"
  else
    python3 - "$DB" "$DEST/mps.db" << 'EOF'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
EOF
  fi
  chmod 600 "$DEST/mps.db"
  echo "DB backed up: $DEST/mps.db"
else
  echo "No DB found at $DB (skipped)"
fi

if [ -d "$SKILLS" ]; then
  cp -r "$SKILLS" "$DEST/skills"
  echo "Skills backed up: $DEST/skills"
fi

# Keep the last 14 backups
ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | tail -n +15 | xargs -r rm -rf
echo "Backup complete: $DEST"
