#!/usr/bin/env bash
# mps-stop.sh — Stop the full MPS AI Agent stack
echo "Stopping MPS server..."
fuser -k 8000/tcp 2>/dev/null && echo "  done" || echo "  was not running"

echo "Stopping Ollama..."
pkill ollama 2>/dev/null && echo "  done" || echo "  was not running"

echo "All stopped. WSL itself keeps running — close the terminal to exit WSL."
