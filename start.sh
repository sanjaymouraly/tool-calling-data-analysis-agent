#!/usr/bin/env bash
# Start the backend and the frontend development server.
#
#   ./start.sh            # backend on :8000, frontend on :5173
#   BACKEND_PORT=9000 ./start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }

info "Creating the Python environment"
cd "$ROOT"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

info "Installing the frontend dependencies"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi

info "Generating the synthetic demo datasets"
cd "$ROOT/backend"
python -m app.demo.generator "$ROOT/data/demo" >/dev/null

info "Starting the API on http://localhost:${BACKEND_PORT}"
cd "$ROOT/backend"
uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

info "Starting the frontend on http://localhost:${FRONTEND_PORT}"
cd "$ROOT/frontend"
npm run dev -- --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

printf '\n\033[1;32mReady.\033[0m Open http://localhost:%s\n' "$FRONTEND_PORT"
wait
