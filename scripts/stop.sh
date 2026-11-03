#!/bin/sh
# Stop ARVA: `docker compose down` stops and removes its containers. Projects, databases, the metadata volume and
# the images are kept; scripts/start.sh (or ARVA.command) starts it again. Other arguments are passed on to
# `docker compose down`, except -v/--volumes, which would delete the metadata volume and is refused.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
arva_os=$(uname -s 2>/dev/null || true)
# shellcheck source=SCRIPTDIR/lib/arva-locations.sh
. "$ROOT/scripts/lib/arva-locations.sh"

for arg do
  case "$arg" in
    -v | --volumes | --volumes=*)
      warn "scripts/stop.sh does not delete volumes (the metadata of every project is in one)." \
           "scripts/stop.sh no borra volúmenes (los metadatos de todos los proyectos están en uno)."
      exit 2
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1 && [ "$arva_os" = Darwin ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
  PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin
  export PATH
fi
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  say "Docker is not running, so ARVA is not running either." "Docker no está en marcha, así que ARVA tampoco."
  exit 0
fi
docker compose -f "$ROOT/docker-compose.yml" down "$@"
say "ARVA stopped. Projects and databases are kept; start it again with ARVA.command or scripts/start.sh." \
    "ARVA se detuvo. Los proyectos y las bases de datos se conservan; se vuelve a iniciar con ARVA.command o scripts/start.sh."
