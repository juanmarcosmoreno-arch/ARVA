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
# Bioconda tools live in environments created from docker/conda-locks (scripts/conda_locks.py install <tool>).
for spec in MLST:mlst/bin/mlst FASTANI:fastani/bin/fastANI SKANI:skani/bin/skani MASH:mash/bin/mash \
  SYLPH:sylph/bin/sylph GTDBTK:gtdbtk/bin/gtdbtk AMRFINDERPLUS:amrfinderplus/bin/amrfinder BAKTA:bakta/bin/bakta \
  ABRICATE:abricate/bin/abricate MOBSUITE:mobsuite/bin/mob_recon INTEGRONFINDER:integronfinder/bin/integron_finder \
  ISESCAN:isescan/bin/isescan.py GENOMAD:genomad/bin/genomad; do
  var="ARVA_TOOL_${spec%%:*}"
  exe="$HOME/.arva-tools/conda/${spec#*:}"
  if [ -z "${!var:-}" ] && [ -x "$exe" ]; then
    export "$var=$exe"
  fi
done
# The species identification tests on NCBI genomes need ARVA_TEST_SPECIES_GENOMES (see
# workflows/tool-adapters/tests/fixtures/species/README.md); without it they are skipped.

echo "==> scientific-core"
(cd "$ROOT/scientific-core" && "$ROOT/apps/api/.venv/bin/pytest" -q)

echo "==> tool adapters (real-tool tests are skipped for tools or databases that are not installed;"
echo "    Bakta's real runs use the light database at ARVA_TEST_BAKTA_DB, default ~/.arva-db/bakta-light/6.0, and"
echo "    AMRFinderPlus's the database at ARVA_TEST_AMRFINDER_DB, default ~/.arva-db/amrfinderplus/2026-08-07.1;"
echo "    MOB-suite's the database at ARVA_TEST_MOBSUITE_DB, default ~/.arva-db/mobsuite-3.1.8/3.1.8)"
(cd "$ROOT/workflows/tool-adapters" && "$ROOT/apps/api/.venv/bin/pytest" -q)

echo "==> api"
(cd "$ROOT/apps/api" && .venv/bin/pytest -q)

echo "==> web (typecheck + unit tests)"
(cd "$ROOT/apps/web" && npx tsc -b --noEmit && npx vitest run)

if [ "${ARVA_E2E:-0}" = "1" ]; then
  echo "==> end-to-end (requires the running stack)"
  node "$ROOT/tests/e2e/golden_path.cjs"
fi
