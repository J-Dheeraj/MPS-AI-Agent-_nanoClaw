#!/usr/bin/env bash
# Governed feedback-to-policy workflow. This script never edits active policy
# from model output and never bypasses the independent review application.
set -euo pipefail

NANOCLAW_DIR="${NANOCLAW_DIR:-$HOME/nanoclaw}"
HERMES_DIR="${HERMES_DIR:-$HOME/mps-hermes-agent}"
REVIEW_ROOT="${REVIEW_ROOT:-$HERMES_DIR/review}"
ACTIVE_POLICY_DIR="${ACTIVE_POLICY_DIR:-$NANOCLAW_DIR/policy/active}"
BATCH_DIR="${BATCH_DIR:-$NANOCLAW_DIR/feedback-exports}"
PYTHON="${PYTHON:-python3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BATCH="$BATCH_DIR/feedback-$STAMP.json"

mkdir -p "$BATCH_DIR"

case "${1:-propose}" in
  propose)
    cd "$NANOCLAW_DIR"
    "$PYTHON" -m mps_server.export_feedback "$BATCH"
    cd "$HERMES_DIR"
    "$PYTHON" hermes.py "$BATCH" "$REVIEW_ROOT"
    echo "Review pending proposals with hermes-review-app."
    echo "No policy has been activated."
    ;;
  promote)
    cd "$HERMES_DIR"
    "$PYTHON" promote_approved.py "$REVIEW_ROOT" "$ACTIVE_POLICY_DIR"
    echo "Promotion completed. Validate the new manifest and run the policy regression suite before deployment."
    ;;
  *)
    echo "Usage: $0 [propose|promote]" >&2
    exit 2
    ;;
esac
