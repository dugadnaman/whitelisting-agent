#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
export PORT=8001
export STORAGE_DIR="$(pwd)/agents/apparel-attribution/data"
export APPAREL_ATTRIBUTION_TOKEN="g9T2kP7xV4mQ8zA1wR6nH3cJ5sL0uE_bD"
export MOENGAGE_MODE="browser"
export MOENGAGE_DASHBOARD_URL="https://dashboard-03.moengage.com/"
export MOENGAGE_REMOTE_CDP_URL="http://127.0.0.1:9222"
export MOENGAGE_BROWSER_LOGIN_URL="https://dashboard-03.moengage.com/"
export PYTHONPATH="$(pwd)/agents/apparel-attribution/Backend"

PYTHON_BIN="$(pwd)/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

mkdir -p "$STORAGE_DIR"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
