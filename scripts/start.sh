#!/bin/sh
# Start ARVA with Docker Compose (`docker compose up -d`; other arguments, such as --build, are passed on).
#
# Storage: where ARVA keeps its files is chosen here once and remembered (scripts/lib/arva-locations.sh), so that
# on a Mac only the program lives on the internal disk and projects and databases can live on an external disk:
#   --data-dir PATH          projects (raw, processed, results, reports, logs) and the metadata backups
#   --databases-dir PATH     reference databases that ARVA downloads
#   --add-databases PATH     an existing database folder to use where it is, read-only (repeat for several)
#   --remove-databases PATH  stop using an added database folder (the folder itself is not touched)
#   --import-dir PATH        sequencing runs to import from, read-only
#   --show-config            show and check the saved locations, then stop
#   --reset-config           forget the saved locations (no folder is touched), then stop
# Every folder is checked before Docker starts. When the disk of the data or database folder is missing, ARVA does
# not start, so nothing is written to the internal disk instead.
#
# On a Mac it also reads which Mac this is (sysctl, system_profiler, sw_vers) and what Docker Desktop gives its
# Linux virtual machine (docker info), and passes these facts to ARVA as ARVA_HOST_* variables, so that ARVA can
# choose a performance profile. Once ARVA runs it prints the profile and, when Docker Desktop's CPUs or memory do
# not suit it, what to set in Docker Desktop. Nothing leaves this computer; of system_profiler's report only the
# model name, chip and core counts are kept (never the serial number).
#
# Not yet validated on a real Mac: see docs/installation.md.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=SCRIPTDIR/lib/arva-locations.sh
. "$ROOT/scripts/lib/arva-locations.sh"
arva_os=$(uname -s 2>/dev/null || true)

usage() {
  say "Usage: scripts/start.sh [--data-dir PATH] [--databases-dir PATH] [--add-databases PATH]... [--remove-databases PATH]...
                        [--import-dir PATH] [--show-config | --reset-config] [docker compose up options, e.g. --build]
Chosen folders are remembered in ${XDG_CONFIG_HOME:-~/.config}/arva/arva.conf; see docs/installation.md (External disk)." \
"Uso: scripts/start.sh [--data-dir RUTA] [--databases-dir RUTA] [--add-databases RUTA]... [--remove-databases RUTA]...
                       [--import-dir RUTA] [--show-config | --reset-config] [opciones de docker compose up, p. ej. --build]
Las carpetas elegidas se recuerdan en ${XDG_CONFIG_HOME:-~/.config}/arva/arva.conf; consulta docs/installation.md (Disco externo)."
}

want_data='' want_databases='' want_import='' want_add='' want_remove='' show=0 reset=0
option() {
  if [ "$(printf '%s' "$2" | LC_ALL=C tr -d '\001-\037\177')" != "$2" ] || [ -z "$2" ]; then
    warn "$1 needs a folder path without control characters." "$1 necesita una ruta de carpeta sin caracteres de control."
    exit 2
  fi
  case "$1" in
    --data-dir) want_data=$2 ;;
    --databases-dir) want_databases=$2 ;;
    --import-dir) want_import=$2 ;;
    --add-databases) want_add=$(list_add "$want_add" "$2") ;;
    --remove-databases) want_remove=$(list_add "$want_remove" "$2") ;;
  esac
}

# Our options are taken out; everything else is kept, in order, for `docker compose up`.
n=$#
while [ "$n" -gt 0 ]; do
  arg=$1
  shift
  n=$((n - 1))
  case "$arg" in
    --data-dir | --databases-dir | --import-dir | --add-databases | --remove-databases)
      if [ "$n" -eq 0 ]; then option "$arg" ''; fi
      option "$arg" "$1"
      shift
      n=$((n - 1))
      ;;
    --data-dir=* | --databases-dir=* | --import-dir=* | --add-databases=* | --remove-databases=*)
      option "${arg%%=*}" "${arg#*=}"
      ;;
    --show-config) show=1 ;;
    --reset-config) reset=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) set -- "$@" "$arg" ;;
  esac
done

arva_config_paths
if [ "$reset" = 1 ]; then
  if [ -n "$ARVA_CONFIG" ]; then rm -f "$ARVA_CONFIG" "$ARVA_OVERRIDE"; fi
  say "Saved locations forgotten ($ARVA_CONFIG). No folder was touched; ARVA uses Docker volumes at its next start." \
      "Ubicaciones guardadas olvidadas ($ARVA_CONFIG). No se tocó ninguna carpeta; ARVA usará volúmenes de Docker en su próximo inicio."
  exit 0
fi
arva_read_config

if [ -n "$want_data$want_databases$want_import$want_add$want_remove" ]; then
  for role in data databases; do
    if [ "$role" = data ]; then want=$want_data en=data es=datos; else want=$want_databases en=databases es='bases de datos'; fi
    [ -n "$want" ] || continue
    if ! arva_inspect "$want" rw; then
      arva_problem "$role" "$want" "$en" "$es" >&2
      exit 1
    fi
    arva_startup_disk_note
    if [ "$role" = data ]; then cfg_data=$chk_real cfg_data_mount=$chk_mount; else cfg_databases=$chk_real cfg_databases_mount=$chk_mount; fi
  done
  if [ -n "$want_import" ]; then
    if ! arva_inspect "$want_import" ro; then
      arva_problem import "$want_import" import importación >&2
      exit 1
    fi
    cfg_import=$chk_real
  fi
  while IFS= read -r want; do
    [ -n "$want" ] || continue
    if ! arva_inspect "$want" ro; then
      arva_problem databases "$want" database "bases de datos" >&2
      exit 1
    fi
    if ! list_has "$cfg_extra" "$chk_real"; then cfg_extra=$(list_add "$cfg_extra" "$chk_real"); fi
  done <<EOF
$want_add
EOF
  while IFS= read -r want; do
    [ -n "$want" ] || continue
    gone=$want
    if [ -d "$want" ]; then gone=$(CDPATH='' cd -P -- "$want" 2>/dev/null && pwd -P) || gone=$want; fi
    if list_has "$cfg_extra" "$gone"; then
      cfg_extra=$(list_remove "$cfg_extra" "$gone")
    else
      warn "$want is not one of the added database folders." "$want no es una de las carpetas de bases de datos añadidas."
    fi
  done <<EOF
$want_remove
EOF
  arva_write_config
  say "Locations saved in $ARVA_CONFIG." "Ubicaciones guardadas en $ARVA_CONFIG."
fi

for legacy in ARVA_DATA_DIR ARVA_DATABASES_DIR ARVA_IMPORT_DIR; do
  if printenv "$legacy" >/dev/null 2>&1 || { [ -f "$ROOT/.env" ] && grep -q "^[[:space:]]*$legacy=" "$ROOT/.env"; }; then
    warn "$legacy is no longer read by docker-compose.yml: choose the folder with scripts/start.sh (--data-dir, --databases-dir or --import-dir)." \
         "docker-compose.yml ya no lee $legacy: elige la carpeta con scripts/start.sh (--data-dir, --databases-dir o --import-dir)."
  fi
done

if [ "$show" = 1 ]; then
  say "Saved locations: $ARVA_CONFIG" "Ubicaciones guardadas: $ARVA_CONFIG"
  if [ -z "$cfg_data$cfg_databases$cfg_import$cfg_extra" ]; then
    say "  none: projects and databases are kept in Docker volumes (inside Docker Desktop's disk image)." \
        "  ninguna: los proyectos y las bases de datos se guardan en volúmenes de Docker (dentro de la imagen de disco de Docker Desktop)."
  fi
  status=0
  arva_check_locations || status=1
  say "Change a location with scripts/start.sh and the option, e.g.:" "Cambia una ubicación con scripts/start.sh y la opción, p. ej.:"
  printf '  %s\n' "scripts/start.sh --data-dir /Volumes/<Disk>/ARVA/data --databases-dir /Volumes/<Disk>/ARVA/databases" \
    "scripts/start.sh --add-databases /Volumes/<Disk>/<existing database folder>"
  exit "$status"
fi

if [ -n "$cfg_data$cfg_databases$cfg_import$cfg_extra" ]; then say "Storage" "Almacenamiento"; fi
if ! arva_check_locations; then
  say "ARVA did not start, so nothing was written to another disk. Saved locations: $ARVA_CONFIG (scripts/start.sh --show-config)." \
      "ARVA no se inició, así que no se escribió nada en otro disco. Ubicaciones guardadas: $ARVA_CONFIG (scripts/start.sh --show-config)." >&2
  exit 1
fi
arva_write_override

# Printable ASCII only, at most 80 characters (the values are shown and passed on; ARVA validates them again).
clean() {
  printf '%s' "$1" | LC_ALL=C tr -cd '[:print:]' | cut -c 1-80
}

number() {
  case "$1" in
    '' | *[!0-9]*) ;;
    *) printf '%s' "$1" ;;
  esac
}

# One sysctl value, or nothing for a key this Mac lacks (Intel Macs and older macOS have no hw.perflevel* keys).
sysctl_n() {
  sysctl -n "$1" 2>/dev/null || true
}

# The string value of key $1 in system_profiler's JSON ($2), or nothing. A narrow match rather than a JSON parser
# (macOS has no jq before 15); it also skips the log line some macOS versions print before the JSON.
json_string() {
  printf '%s\n' "$2" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -n 1
}

read_mac() {
  # Keys: Apple, "Determining system capabilities" (hw.nperflevels, hw.perflevelN.physicalcpu with N = 0 the
  # fastest cores, hw.physicalcpu, hw.logicalcpu, hw.memsize), sysctl(3) (hw.model, machdep.cpu.brand_string),
  # "About the Rosetta translation environment" (sysctl.proc_translated).
  model_id=$(clean "$(sysctl_n hw.model)")
  chip=$(clean "$(sysctl_n machdep.cpu.brand_string)")
  physical=$(number "$(sysctl_n hw.physicalcpu)")
  logical=$(number "$(sysctl_n hw.logicalcpu)")
  memory=$(number "$(sysctl_n hw.memsize)")
  perf=''
  eff=''
  levels=$(number "$(sysctl_n hw.nperflevels)")
  if [ -n "$levels" ] && [ "$levels" -ge 2 ]; then
    perf=$(number "$(sysctl_n hw.perflevel0.physicalcpu)")
    eff=0
    n=1
    while [ "$n" -lt "$levels" ]; do
      count=$(number "$(sysctl_n "hw.perflevel$n.physicalcpu")")
      if [ -z "$count" ]; then
        eff=''
        break
      fi
      eff=$((eff + count))
      n=$((n + 1))
    done
    if [ -z "$eff" ]; then perf=''; fi
  fi
  # machine_name ("MacBook Air"): model identifiers from 2022 on ("Mac14,2") do not name the family.
  hardware=$(system_profiler -json SPHardwareDataType 2>/dev/null |
    grep -E '"(machine_name|chip_type|number_processors)"' || true)
  model_name=$(clean "$(json_string machine_name "$hardware")")
  if [ -z "$chip" ]; then chip=$(clean "$(json_string chip_type "$hardware")"); fi
  if [ -z "$perf" ]; then
    # Apple silicon: "proc TOTAL:PERFORMANCE:EFFICIENCY" (a plain number on Intel Macs).
    procs=$(json_string number_processors "$hardware")
    case "$procs" in
      "proc "*:*:*)
        rest=${procs#proc }
        rest=${rest#*:}
        perf=$(number "${rest%%:*}")
        eff=$(number "${rest#*:}")
        ;;
    esac
    if [ -z "$perf" ] || [ -z "$eff" ]; then
      perf=''
      eff=''
    fi
  fi
  os_version=$(clean "$(sw_vers -productVersion 2>/dev/null || true)")
  arch=$(clean "$(uname -m 2>/dev/null || true)")
  if [ "$(sysctl_n sysctl.proc_translated)" = 1 ]; then arch=arm64; fi
}

if [ "$arva_os" = Darwin ]; then
  if ! docker_info=$(docker info --format '{{.NCPU}} {{.MemTotal}}' 2>/dev/null); then
    say "Docker is not running. Start Docker Desktop, wait until it is ready, then run this script again." \
        "Docker no está en marcha. Abre Docker Desktop, espera a que esté listo y vuelve a ejecutar este script."
    exit 1
  fi
  docker_cpus=$(number "${docker_info%% *}")
  docker_memory=$(number "${docker_info##* }")
  read_mac

  export ARVA_HOST_PLATFORM=macos
  export ARVA_HOST_MODEL_NAME="$model_name" ARVA_HOST_MODEL_ID="$model_id" ARVA_HOST_CHIP="$chip"
  export ARVA_HOST_PERF_CORES="$perf" ARVA_HOST_EFF_CORES="$eff" ARVA_HOST_PHYSICAL_CORES="$physical"
  export ARVA_HOST_LOGICAL_CPUS="$logical" ARVA_HOST_MEMORY_BYTES="$memory" ARVA_HOST_OS_VERSION="$os_version"
  export ARVA_HOST_ARCH="$arch" ARVA_HOST_DOCKER_CPUS="$docker_cpus" ARVA_HOST_DOCKER_MEMORY_BYTES="$docker_memory"

  gb() {
    if [ -n "$1" ]; then awk -v bytes="$1" 'BEGIN { printf "%.1f GB", bytes / 1073741824 }'; else printf '?'; fi
  }
  if [ -n "$perf" ]; then
    cores=$(say "$perf performance + $eff efficiency cores" "$perf núcleos de rendimiento + $eff de eficiencia")
  else
    cores=$(say "${physical:-?} cores" "${physical:-?} núcleos")
  fi
  say "This Mac" "Esta Mac"
  printf '  %s\n' "${model_name:-?}${model_id:+ ($model_id)} · ${chip:-?} · $cores · $(gb "$memory") · macOS ${os_version:-?}"
  say "  Docker Desktop gives its virtual machine ${docker_cpus:-?} CPUs and $(gb "$docker_memory")" \
      "  Docker Desktop da a su máquina virtual ${docker_cpus:-?} CPU y $(gb "$docker_memory")"
fi

arva_compose up -d "$@"

if ! arva_compose exec -T api python -m app.services.performance --lang "$lang"; then
  say "ARVA is running; its performance profile is in Settings → Performance." \
      "ARVA está en marcha; su perfil de rendimiento está en Ajustes → Rendimiento."
fi
if ! arva_compose exec -T api python -m app.services.locations --lang "$lang"; then
  say "Where ARVA keeps its files is in Settings → Storage." "Dónde guarda ARVA sus archivos está en Ajustes → Almacenamiento."
fi
say "Open http://localhost:8080" "Abre http://localhost:8080"
