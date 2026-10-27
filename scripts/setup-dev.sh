#!/usr/bin/env bash
# One-time local development setup (macOS or Linux, no Docker required).
# Prerequisites: Python >= 3.11, Node >= 20, PostgreSQL >= 14 and Redis running locally.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> System"
echo "    $(uname -s) $(uname -m) · $(python3 --version) · node $(node --version)"

echo "==> Python environment (apps/api/.venv)"
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -q --upgrade pip
apps/api/.venv/bin/pip install -q -e scientific-core -e "apps/api[dev]"

echo "==> Web dependencies"
(cd apps/web && npm ci --no-audit --no-fund)

if [ ! -f apps/api/.env ]; then
  cp .env.example apps/api/.env
  echo "==> Created apps/api/.env from .env.example — review the database URL."
fi

echo "==> Database migrations"
(cd apps/api && .venv/bin/alembic upgrade head)

echo "Done. Start ARVA with: scripts/dev.sh"
