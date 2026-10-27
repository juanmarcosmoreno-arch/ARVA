#!/usr/bin/env bash
# Run every automated test suite. The API suite needs PostgreSQL
# (ARVA_TEST_DATABASE_URL, default: local arva_test database).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> scientific-core"
(cd "$ROOT/scientific-core" && "$ROOT/apps/api/.venv/bin/pytest" -q)

echo "==> api"
(cd "$ROOT/apps/api" && .venv/bin/pytest -q)

echo "==> web (typecheck + unit tests)"
(cd "$ROOT/apps/web" && npx tsc -b --noEmit && npx vitest run)

if [ "${ARVA_E2E:-0}" = "1" ]; then
  echo "==> end-to-end (requires the running stack)"
  node "$ROOT/tests/e2e/golden_path.cjs"
fi
