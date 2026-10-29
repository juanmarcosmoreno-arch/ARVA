#!/bin/sh
# Back up ARVA's metadata now into the data folder's backups/ folder (the same as "Back up now" in Settings →
# Storage; scripts/metadata-backup.sh). Uses the locations saved by scripts/start.sh, with the same checks.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=SCRIPTDIR/lib/arva-locations.sh
. "$ROOT/scripts/lib/arva-locations.sh"
arva_os=$(uname -s 2>/dev/null || true)

arva_config_paths
arva_read_config
if ! arva_check_locations; then
  say "No backup was made: connect the disk of the data folder first." "No se hizo ninguna copia: conecta primero el disco de la carpeta de datos." >&2
  exit 1
fi
arva_write_override
arva_compose up -d --wait postgres
arva_compose run --rm --no-deps -T backup backup manual
