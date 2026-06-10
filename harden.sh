#!/usr/bin/env bash
# harden.sh -- Run once after initial setup to generate proper secrets
# and tighten file permissions.
set -euo pipefail

ENV_FILE="$(dirname "$0")/mps_server/.env"
DB_FILE="$(dirname "$0")/mps_server/mps.db"

echo '=== MPS Server Hardening ==='

# 1. Generate a proper SECRET_KEY (create .env if it does not exist yet)
NEW_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
if [ ! -f "$ENV_FILE" ]; then
  printf 'SECRET_KEY=%s\nHOST=127.0.0.1\nPORT=8000\n' "$NEW_KEY" > "$ENV_FILE"
elif grep -q '^SECRET_KEY=' "$ENV_FILE"; then
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_KEY}|" "$ENV_FILE"
else
  printf 'SECRET_KEY=%s\n' "$NEW_KEY" >> "$ENV_FILE"
fi
echo "[1/5] Generated new SECRET_KEY"

# 2. Restrict .env permissions
chmod 600 "$ENV_FILE"
echo "[2/5] .env permissions set to 600"

# 3. Restrict DB permissions
if [ -f "$DB_FILE" ]; then
  chmod 600 "$DB_FILE"
  echo "[3/5] mps.db permissions set to 600"
else
  echo "[3/5] mps.db not found (will be created on first start)"
fi

# 4. Restrict skill files (read-only for group)
find "$(dirname "$0")/groups/mps-volunteers/skills/" -type d -exec chmod 750 {} + 2>/dev/null || true
find "$(dirname "$0")/groups/mps-volunteers/skills/" -type f -exec chmod 640 {} + 2>/dev/null || true
echo "[4/5] Skill files set to 640"

# 5. Remind admin about first-run credentials
echo "[5/5] NOTE: On first start the server creates an 'admin' account with a"
echo "      RANDOM one-time password printed to the server console. Log in with"
echo "      it, change it via PUT /auth/change-password, then create real"
echo "      accounts via POST /auth/register (admin only)."
echo ''
echo '=== Hardening complete ==='
