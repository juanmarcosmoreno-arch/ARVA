#!/usr/bin/env bash
# Run API, analysis worker and web dev server together. Ctrl+C stops all three.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cd "$ROOT/apps/api"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
PIDS+=($!)
.venv/bin/python ../workers/run_worker.py &
PIDS+=($!)

cd "$ROOT/apps/web"
npx vite --host 127.0.0.1 --port 5173 &
PIDS+=($!)

echo "ARVA: http://localhost:5173  ·  API docs: http://localhost:8000/docs"
wait
