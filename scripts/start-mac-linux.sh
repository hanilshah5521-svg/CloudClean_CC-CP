#!/usr/bin/env bash
# CloudClean - one-command setup and start for macOS / Linux.
# First run: creates backend/venv and installs packages (a few minutes).
# Runs the backend, the worker and the frontend; Ctrl+C stops all three.
# Pass --setup-only to install without starting.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== CloudClean setup ==="
PY=""
for candidate in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 13)))' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 to 3.13 is required (3.12 recommended): https://www.python.org/downloads/"
  exit 1
fi
command -v npm >/dev/null 2>&1 || { echo "Node.js 18 or newer is required: https://nodejs.org/"; exit 1; }
echo "Using Python: $PY"

[ -x backend/venv/bin/python ] || "$PY" -m venv backend/venv
echo "Installing backend packages ..."
backend/venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip
backend/venv/bin/python -m pip install --quiet --disable-pip-version-check -r backend/requirements.txt
if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend packages ..."
  (cd frontend && npm ci --no-audit --no-fund)
fi

if [ "${1:-}" = "--setup-only" ]; then
  echo "Setup complete."
  exit 0
fi

echo "=== Starting CloudClean ==="
trap 'kill $(jobs -p) 2>/dev/null || true' EXIT INT TERM
(cd backend && exec venv/bin/python -m uvicorn app.main:app --port 8000) &
(cd backend && exec venv/bin/python -m app.worker) &
echo
echo "CloudClean will be at http://localhost:5173 - click \"Try Demo Mode\". Press Ctrl+C to stop."
cd frontend && npm run dev
