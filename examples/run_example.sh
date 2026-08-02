#!/usr/bin/env bash
# agentlog worked example — run from the repo root in under a minute.
#
# Usage:
#   cd /path/to/agentlog
#   bash examples/run_example.sh
#
# Requires: Python 3.9+, no other dependencies.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

# Helper to run agentlog from source without installing it.
agentlog() {
    PYTHONPATH="$REPO_DIR" "$PYTHON" -m agentlog "$@"
}

echo "--- agentlog version ---"
agentlog --version
echo ""

echo "--- agentlog today ---"
agentlog today
echo ""

echo "--- agentlog list (first 10 lines) ---"
agentlog list | head -10
echo ""

echo "--- agentlog since 3d (summary line only) ---"
agentlog since 3d | head -1
echo ""

echo "--- agentlog today --html /tmp/agentlog-demo.html ---"
agentlog today --html /tmp/agentlog-demo.html
echo "Open file:///tmp/agentlog-demo.html in your browser."
echo ""

echo "--- agentlog today --json (first 20 lines) ---"
agentlog today --json | head -20
echo ""

echo "Done."
