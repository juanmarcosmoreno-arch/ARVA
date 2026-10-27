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
apps/api/.venv/bin/pip install -q -e scientific-core -e workflows/tool-adapters -e "apps/api[dev]"

echo "==> Web dependencies"
(cd apps/web && npm ci --no-audit --no-fund)

if [ ! -f apps/api/.env ]; then
  cp .env.example apps/api/.env
  echo "==> Created apps/api/.env from .env.example — review the database URL."
fi

echo "==> Database migrations"
(cd apps/api && .venv/bin/alembic upgrade head)

echo "==> External tools (optional; install them yourself — ARVA never installs software)"
apps/api/.venv/bin/python -c "
from arva_tools.registry import detect_all
for d in detect_all():
    print(f'    {d.info.name:<9} {d.status.value:<14} {d.version or \"\"} {d.message}')
"
echo "    Install with: mamba env create -f workflows/tool-adapters/environment.yml (or apt/your package manager)"

echo "Done. Start ARVA with: scripts/dev.sh"
