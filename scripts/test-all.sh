#!/usr/bin/env bash
# Run every automated test suite. The API suite needs PostgreSQL
# (ARVA_TEST_DATABASE_URL, default: local arva_test database).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# MultiQC, NanoPlot and QUAST live in their own virtual environments (docs/installation.md); use them when installed there.
if [ -z "${ARVA_TOOL_MULTIQC:-}" ] && [ -x "$HOME/.arva-tools/multiqc/bin/multiqc" ]; then
  export ARVA_TOOL_MULTIQC="$HOME/.arva-tools/multiqc/bin/multiqc"
fi
if [ -z "${ARVA_TOOL_NANOPLOT:-}" ] && [ -x "$HOME/.arva-tools/nanoplot/bin/NanoPlot" ]; then
  export ARVA_TOOL_NANOPLOT="$HOME/.arva-tools/nanoplot/bin/NanoPlot"
fi
if [ -z "${ARVA_TOOL_QUAST:-}" ] && [ -x "$HOME/.arva-tools/quast/bin/quast.py" ]; then
  export ARVA_TOOL_QUAST="$HOME/.arva-tools/quast/bin/quast.py"
fi

echo "==> scientific-core"
(cd "$ROOT/scientific-core" && "$ROOT/apps/api/.venv/bin/pytest" -q)

echo "==> tool adapters (real-tool tests are skipped for tools that are not installed)"
(cd "$ROOT/workflows/tool-adapters" && "$ROOT/apps/api/.venv/bin/pytest" -q)

echo "==> api"
(cd "$ROOT/apps/api" && .venv/bin/pytest -q)

echo "==> web (typecheck + unit tests)"
(cd "$ROOT/apps/web" && npx tsc -b --noEmit && npx vitest run)

if [ "${ARVA_E2E:-0}" = "1" ]; then
  echo "==> end-to-end (requires the running stack)"
  node "$ROOT/tests/e2e/golden_path.cjs"
fi
