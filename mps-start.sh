#!/usr/bin/env bash
# mps-start.sh — Start the full MPS AI Agent stack on demand
set -euo pipefail

cd ~/nanoclaw

echo "Starting Ollama..."
if ! pgrep -x ollama > /dev/null; then
    ollama serve &>/tmp/ollama.log &
    sleep 2
    echo "  Ollama started (log: /tmp/ollama.log)"
else
    echo "  Ollama already running"
fi

echo "Starting MPS server..."
if ! fuser 8000/tcp &>/dev/null; then
    python3 -m uvicorn mps_server.main:app --host 127.0.0.1 --port 8000 &>/tmp/mps-server.log &
    sleep 2
    echo "  Server started on :8000 (log: /tmp/mps-server.log)"
else
    echo "  Server already running on :8000"
fi

echo "Launching MPS client..."
DISPLAY=:0 python3 -m mps_client &

echo ""
echo "MPS AI Agent is running."
echo "  Server log : tail -f /tmp/mps-server.log"
echo "  Ollama log : tail -f /tmp/ollama.log"
echo ""
echo "To stop everything:  bash ~/nanoclaw/mps-stop.sh"
