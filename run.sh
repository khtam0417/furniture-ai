#!/usr/bin/env bash
# One-command local launch: creates .venv if needed, installs pinned Python deps, serves the
# pre-built frontend (frontend/dist) and the API from ONE server at http://127.0.0.1:8000.
# Node is only needed if frontend/dist is missing.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment in .venv ..."
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building frontend ..."
    (cd frontend && npm ci --no-audit --no-fund && npm run build)
  else
    echo "frontend/dist is missing and npm is not installed; the API will run without the UI." >&2
  fi
fi

exec .venv/bin/python serve.py "$@"
