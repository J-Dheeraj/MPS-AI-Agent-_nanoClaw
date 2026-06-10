#!/usr/bin/env bash
# Start the MPS FastAPI server
# Usage: bash start-server.sh [--prod]
#   HOST defaults to 127.0.0.1 (localhost only).
#   Set HOST=0.0.0.0 in mps_server/.env to accept LAN connections
#   from volunteer/vetter laptops.
set -euo pipefail

cd "$(dirname "$0")"

# Load .env if present (SECRET_KEY, HOST, PORT, ALLOWED_ORIGINS...)
if [ -f mps_server/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source mps_server/.env
  set +a
fi

if [ -z "${SECRET_KEY:-}" ]; then
  echo "ERROR: SECRET_KEY is not set. Run: bash harden.sh" >&2
  exit 1
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

RELOAD_FLAG="--reload --reload-dir mps_server"
if [ "${1:-}" = "--prod" ]; then
  RELOAD_FLAG=""
  export DISABLE_DOCS=1
fi

echo "Starting mps-server on ${HOST}:${PORT}"
exec python3 -m uvicorn mps_server.main:app \
  --host "$HOST" \
  --port "$PORT" \
  $RELOAD_FLAG
