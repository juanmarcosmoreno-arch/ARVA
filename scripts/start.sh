#!/bin/sh
# Start ARVA with Docker Compose (`docker compose up -d`; other arguments, such as --build, are passed on).
#
# Images: without --build, the published images (ghcr.io/juanmarcosmoreno-arch/arva-api and arva-web, tag = ARVA's
# version; ARVA_API_IMAGE, ARVA_WEB_IMAGE and ARVA_IMAGE_TAG choose others) are pulled first; while their owner keeps
# them private, sign in once with `docker login ghcr.io` (docs/installation.md). With --build
# the images are built here and named arva-api and arva-web instead.
#   --platform linux/amd64|linux/arm64|auto   the image architecture (saved; auto: chosen at each start)
# The automatic choice: the computer's own architecture, except on Apple silicon, where it is linux/amd64 (every
# tool, run through Rosetta) when Docker Desktop's "Use Rosetta for x86_64/amd64 emulation on Apple Silicon"
# setting is on, left at Docker Desktop's default (its settings file then has no such key) or cannot be read, and linux/arm64 (native, without the tools that have no arm64 build) when it is
# off. The choice and why are printed and shown in Settings → Performance.
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
# First run: in a terminal and with no saved locations yet (and none given as options), it first asks, in Spanish
# when the locale is Spanish, whether Docker Desktop is installed and running, which disk keeps the data and
# databases (/Volumes/<Disk>/ARVA/{data,databases} proposed), which existing database folders to add read-only and,
# on Apple silicon, which image architecture (scripts/lib/arva-firstrun.sh); then it starts and opens the browser.
#   --setup                  ask those questions again (reads the answers from standard input)
#   --no-setup               never ask (for scripts; a plain run without a terminal never asks either)
#   --open                   open http://localhost:8080 in the browser once ARVA answers (ARVA.command uses it)
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
arva_os=$(uname -s 2>/dev/null || true)
# shellcheck source=SCRIPTDIR/lib/arva-locations.sh
. "$ROOT/scripts/lib/arva-locations.sh"
# shellcheck source=SCRIPTDIR/lib/arva-firstrun.sh
. "$ROOT/scripts/lib/arva-firstrun.sh"

usage() {
  say "Usage: scripts/start.sh [--data-dir PATH] [--databases-dir PATH] [--add-databases PATH]... [--remove-databases PATH]...
                        [--import-dir PATH] [--platform linux/amd64|linux/arm64|auto] [--show-config | --reset-config]
                        [--setup | --no-setup] [--open] [docker compose up options, e.g. --build]
Chosen folders are remembered in ${XDG_CONFIG_HOME:-~/.config}/arva/arva.conf; see docs/installation.md (External disk)." \
"Uso: scripts/start.sh [--data-dir RUTA] [--databases-dir RUTA] [--add-databases RUTA]... [--remove-databases RUTA]...
                       [--import-dir RUTA] [--platform linux/amd64|linux/arm64|auto] [--show-config | --reset-config]
                       [--setup | --no-setup] [--open] [opciones de docker compose up, p. ej. --build]
Las carpetas elegidas se recuerdan en ${XDG_CONFIG_HOME:-~/.config}/arva/arva.conf; consulta docs/installation.md (Disco externo)."
}

want_data='' want_databases='' want_import='' want_add='' want_remove='' want_platform='' show=0 reset=0 build=0
setup='' open_browser=0
platform_option() {
  case "$1" in
    linux/amd64 | linux/arm64 | auto) want_platform=$1 ;;
    *)
      warn "--platform must be linux/amd64, linux/arm64 or auto." "--platform debe ser linux/amd64, linux/arm64 o auto."
      exit 2
      ;;
  esac
}
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
    --platform)
      if [ "$n" -eq 0 ]; then platform_option ''; fi
      platform_option "$1"
      shift
      n=$((n - 1))
      ;;
    --platform=*) platform_option "${arg#*=}" ;;
    --show-config) show=1 ;;
    --setup) setup=1 ;;
    --no-setup) setup=0 ;;
    --open) open_browser=1 ;;
    --reset-config) reset=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      if [ "$arg" = --build ]; then build=1; fi
      set -- "$@" "$arg"
      ;;
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

first_run=0
if [ "$setup" = 1 ]; then
  first_run=1
elif [ -z "$setup" ] && [ "$show" = 0 ] && [ -n "$ARVA_CONFIG" ] && [ ! -e "$ARVA_CONFIG" ] && [ -t 0 ] && [ -t 1 ] &&
  [ -z "$want_data$want_databases$want_import$want_add$want_remove$want_platform" ]; then
  first_run=1
fi
if [ "$first_run" = 1 ] && ! arva_first_run; then
  say "ARVA did not start; nothing was saved." "ARVA no se inició; no se guardó nada." >&2
  exit 1
fi

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
if [ -n "$want_platform" ]; then
  if [ "$want_platform" = auto ]; then cfg_platform=''; else cfg_platform=$want_platform; fi
  arva_write_config
fi
# Answers that keep everything in Docker volumes still leave a (header-only) file, so the questions are not asked again.
if [ "$first_run" = 1 ] && [ ! -e "$ARVA_CONFIG" ]; then arva_write_config; fi

for legacy in ARVA_DATA_DIR ARVA_DATABASES_DIR ARVA_IMPORT_DIR; do
  if printenv "$legacy" >/dev/null 2>&1 || { [ -f "$ROOT/.env" ] && grep -q "^[[:space:]]*$legacy=" "$ROOT/.env"; }; then
    warn "$legacy is no longer read by docker-compose.yml: choose the folder with scripts/start.sh (--data-dir, --databases-dir or --import-dir)." \
         "docker-compose.yml ya no lee $legacy: elige la carpeta con scripts/start.sh (--data-dir, --databases-dir o --import-dir)."
  fi
done

if [ "$show" = 1 ]; then
  say "Saved locations: $ARVA_CONFIG" "Ubicaciones guardadas: $ARVA_CONFIG"
  if [ -n "$cfg_platform" ]; then
    say "  Image architecture: $cfg_platform (scripts/start.sh --platform auto lets ARVA choose)" \
        "  Arquitectura de las imágenes: $cfg_platform (scripts/start.sh --platform auto deja que ARVA la elija)"
  fi
  if [ -z "$cfg_data$cfg_databases$cfg_import$cfg_extra" ]; then
    say "  none: projects and databases are kept in Docker volumes (inside Docker Desktop's disk image)." \
        "  ninguna: los proyectos y las bases de datos se guardan en volúmenes de Docker (dentro de la imagen de disco de Docker Desktop)."
  fi
  status=0
  arva_check_locations || status=1
  if [ "$arva_os" = Darwin ]; then sharing_report "$loc_paths"; fi
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
# A folder on an external disk that Docker Desktop shares only through /Volumes (or its default list): ARVA would read
# the startup disk's free space (the first run explains this and waits; here it is only said).
if [ "$arva_os" = Darwin ] && [ "$first_run" = 0 ]; then
  sharing_report "$loc_paths" >&2
fi

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
  if ! command -v docker >/dev/null 2>&1 && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
    PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin
    export PATH
  fi
  if ! command -v docker >/dev/null 2>&1; then
    say "Docker Desktop is not installed (no docker command was found): https://docs.docker.com/desktop/setup/install/mac-install/" \
        "Docker Desktop no está instalado (no se encontró el comando docker): https://docs.docker.com/desktop/setup/install/mac-install/"
    exit 1
  fi
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

# The image architecture: saved with --platform, else this computer's own, except on Apple silicon (see the top).
rosetta=''
if [ -n "$cfg_platform" ]; then
  image_platform=$cfg_platform image_reason=chosen
elif [ "$arva_os" = Darwin ]; then
  if [ "${arch:-}" = arm64 ]; then
    rosetta=$(docker_rosetta)
    case "$rosetta" in
      off) image_platform=linux/arm64 image_reason=rosetta_off ;;
      on) image_platform=linux/amd64 image_reason=rosetta_on ;;
      default) image_platform=linux/amd64 image_reason=rosetta_default ;;
      *) image_platform=linux/amd64 image_reason=rosetta_unknown ;;
    esac
  else
    image_platform=linux/amd64 image_reason=native
  fi
else
  case "$(uname -m 2>/dev/null || true)" in
    x86_64 | amd64) image_platform=linux/amd64 image_reason=native ;;
    aarch64 | arm64) image_platform=linux/arm64 image_reason=native ;;
    *) image_platform='' image_reason=unknown ;;
  esac
fi
export ARVA_PLATFORM="$image_platform" ARVA_HOST_IMAGE_PLATFORM="$image_platform" ARVA_HOST_IMAGE_REASON="$image_reason"
export ARVA_HOST_DOCKER_ROSETTA="$rosetta"

shown_platform=${image_platform:-?}
say "Image architecture: $shown_platform" "Arquitectura de las imágenes: $shown_platform"
case "$image_reason" in
  chosen)
    say "  chosen with --platform (scripts/start.sh --platform auto lets ARVA choose again)." \
        "  elegida con --platform (scripts/start.sh --platform auto deja que ARVA vuelva a elegir)."
    ;;
  native)
    say "  this computer's own architecture." "  la arquitectura propia de este equipo."
    ;;
  rosetta_on | rosetta_default | rosetta_unknown)
    say "  Apple silicon: the amd64 image runs every ARVA tool (Bakta with all its steps, Prokka, MOB-suite, IntegronFinder,
  AgrVATE, ISEScan and GTDB-Tk have no arm64 build), translated by Rosetta, so slower than a native program.
  scripts/start.sh --platform linux/arm64 runs natively without those tools." \
        "  Apple silicon: la imagen amd64 ejecuta todas las herramientas de ARVA (Bakta con todos sus pasos, Prokka, MOB-suite,
  IntegronFinder, AgrVATE, ISEScan y GTDB-Tk no tienen versión arm64), traducidas por Rosetta, así que más lentas que un
  programa nativo. scripts/start.sh --platform linux/arm64 se ejecuta de forma nativa sin esas herramientas."
    if [ "$image_reason" != rosetta_on ]; then
      rosetta_note "$rosetta"
      say "  If it is off, Docker emulates amd64 with QEMU, which is much slower: Settings → General → \"Use Rosetta for
  x86_64/amd64 emulation on Apple Silicon\"." \
          "  Si está desactivado, Docker emula amd64 con QEMU, mucho más lento: Settings → General → \"Use Rosetta for
  x86_64/amd64 emulation on Apple Silicon\"."
    fi
    ;;
  rosetta_off)
    say "  Apple silicon with Rosetta off in Docker Desktop: the native arm64 image, without the tools that have no arm64
  build (Bakta's CDS and RNA steps, Prokka, MOB-suite, IntegronFinder, AgrVATE, ISEScan, GTDB-Tk). To use them, turn on
  Settings → General → \"Use Rosetta for x86_64/amd64 emulation on Apple Silicon\" and run scripts/start.sh again." \
        "  Apple silicon con Rosetta desactivado en Docker Desktop: la imagen arm64 nativa, sin las herramientas que no tienen
  versión arm64 (los pasos de CDS y ARN de Bakta, Prokka, MOB-suite, IntegronFinder, AgrVATE, ISEScan, GTDB-Tk). Para
  usarlas, activa Settings → General → \"Use Rosetta for x86_64/amd64 emulation on Apple Silicon\" y vuelve a ejecutar
  scripts/start.sh."
    ;;
  *)
    say "  this computer's architecture is not one ARVA publishes images for; Docker chooses." \
        "  ARVA no publica imágenes para la arquitectura de este equipo; Docker elige."
    ;;
esac

# The images: the published ones (pulled now), or built here with --build under their own names.
version=$(sed -n 's/^__version__ = "\([0-9a-z.]*\)".*/\1/p' "$ROOT/apps/api/app/__init__.py" 2>/dev/null || true)
export ARVA_IMAGE_TAG="${ARVA_IMAGE_TAG:-${version:-latest}}"
if [ "$build" = 1 ]; then
  export ARVA_API_IMAGE="${ARVA_API_IMAGE:-arva-api}" ARVA_WEB_IMAGE="${ARVA_WEB_IMAGE:-arva-web}" ARVA_HOST_IMAGE_SOURCE=local
else
  export ARVA_API_IMAGE="${ARVA_API_IMAGE:-ghcr.io/juanmarcosmoreno-arch/arva-api}"
  export ARVA_WEB_IMAGE="${ARVA_WEB_IMAGE:-ghcr.io/juanmarcosmoreno-arch/arva-web}" ARVA_HOST_IMAGE_SOURCE=published
fi

# The commit the images are built from (docker/api.Dockerfile and web.Dockerfile record it for the error log).
arva_commit=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || true)
case "$arva_commit" in '' | *[!0-9a-f]*) arva_commit=unknown ;; esac
export ARVA_GIT_COMMIT="$arva_commit"

# A launcher failure in the data folder's error log (app/core/errorlog.py's format), only when that folder is there
# and already ARVA's (storage marker and logs folder present): never into a folder that may be on another disk.
log_launcher() {
  logs=$cfg_data/logs
  if [ -z "$cfg_data" ] || [ ! -f "$cfg_data/.arva-storage" ] || [ ! -d "$logs" ] || [ ! -w "$logs" ]; then return 0; fi
  id=$(od -An -N8 -tu1 /dev/urandom 2>/dev/null | awk -v a=23456789ABCDEFGHJKLMNPQRSTUVWXYZ '
    { for (i = 1; i <= NF; i++) s = s substr(a, $i % 32 + 1, 1) } END { print substr(s, 1, 4) "-" substr(s, 5, 4) }')
  version=$(sed -n 's/^__version__ = "\([0-9a-z.]*\)".*/\1/p' "$ROOT/apps/api/app/__init__.py" 2>/dev/null || true)
  printf '{"id":"%s","time":"%s","version":"%s","commit":"%s","component":"launcher","severity":"error","code":"%s","message":"%s","params":{"status":%d}}\n' \
    "$id" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${version:-unknown}" "$arva_commit" "$1" "$2" "$3" >> "$logs/errors.jsonl" 2>/dev/null || true
}

# In a terminal, a denied pull can be followed by `docker login ghcr.io` right here: Docker itself asks for the token
# (it never passes through this script) and keeps it in its credential store.
pull() {
  arva_compose pull api web && return 0
  if [ "$first_run" = 0 ] && { [ ! -t 0 ] || [ ! -t 1 ]; }; then return 1; fi
  if docker image inspect "$ARVA_API_IMAGE:$ARVA_IMAGE_TAG" "$ARVA_WEB_IMAGE:$ARVA_IMAGE_TAG" >/dev/null 2>&1; then return 1; fi
  say "The images could not be downloaded. If they are private, sign in to ghcr.io with your GitHub user name and a
personal access token with the read:packages scope (docs/guia-mac.md, step 5)." \
      "No se pudieron descargar las imágenes. Si son privadas, iniciar sesión en ghcr.io con el nombre de usuario de GitHub y
un token de acceso personal con el permiso read:packages (docs/guia-mac.md, paso 5)."
  ask_yes "Sign in now?" "¿Iniciar sesión ahora?" n || return 1
  ask "GitHub user name:" "Nombre de usuario de GitHub:"
  case "$reply" in
    '' | -* | *[!A-Za-z0-9-]*)
      say "That is not a GitHub user name." "Eso no es un nombre de usuario de GitHub."
      return 1
      ;;
  esac
  docker login ghcr.io -u "$reply" || return 1
  arva_compose pull api web
}

# Before the first download of this version's published images (the API image is not on this computer yet): how big
# they are and that it can take long. Nothing is asked of the registry for this: `docker image inspect` only looks
# at this computer's images, and the sizes are the ones measured when the images were published (docs/installation.md,
# "Size of ARVA's images": unpacked, as `docker image ls` shows them; the download is compressed, so smaller). The
# time is from a real test on a Mac (docs/registro-prueba-mac.md, row 6: about 1.5 h at about 0.8 MB/s).
if [ "$build" = 0 ] && [ "$ARVA_API_IMAGE" = ghcr.io/juanmarcosmoreno-arch/arva-api ] &&
  ! docker image inspect "$ARVA_API_IMAGE:$ARVA_IMAGE_TAG" >/dev/null 2>&1; then
  case "$image_platform" in linux/arm64) image_size='10 GB' ;; *) image_size='16 GB' ;; esac
  say "Downloading ARVA $ARVA_IMAGE_TAG for the first time on this computer: once unpacked, its images take about
$image_size (${image_platform:-linux/amd64}; the download itself is compressed, so smaller). On a slow connection this
can take more than an hour (one test on a Mac took 1.5 h at about 0.8 MB/s). Docker shows its progress below." \
      "Se descarga ARVA $ARVA_IMAGE_TAG por primera vez en esta computadora: ya descomprimidas, sus imágenes ocupan
unos $image_size (${image_platform:-linux/amd64}; la descarga en sí está comprimida, así que es menor). Con una
conexión lenta puede tardar más de una hora (en una prueba en una Mac tardó 1,5 h a unos 0,8 MB/s). Docker muestra
el avance a continuación."
fi
if [ "$build" = 0 ] && ! pull; then
  if docker image inspect "$ARVA_API_IMAGE:$ARVA_IMAGE_TAG" "$ARVA_WEB_IMAGE:$ARVA_IMAGE_TAG" >/dev/null 2>&1; then
    say "The images could not be updated; ARVA starts with the copies already on this computer."         "No se pudieron actualizar las imágenes; ARVA se inicia con las copias que ya hay en este equipo."
  else
    log_launcher launcher_pull_failed "docker compose pull failed" 1
    say "Docker could not download $ARVA_API_IMAGE:$ARVA_IMAGE_TAG and $ARVA_WEB_IMAGE:$ARVA_IMAGE_TAG. Check the
internet connection; if the images are private, sign in once with
  docker login ghcr.io -u <your GitHub user name>
giving a GitHub personal access token with the read:packages scope as the password (Docker keeps it, on a Mac in the
keychain; ARVA never sees or stores it), then run scripts/start.sh again. Or build the images here: scripts/start.sh --build"         "Docker no pudo descargar $ARVA_API_IMAGE:$ARVA_IMAGE_TAG ni $ARVA_WEB_IMAGE:$ARVA_IMAGE_TAG. Comprueba la
conexión a internet; si las imágenes son privadas, inicia sesión una vez con
  docker login ghcr.io -u <tu nombre de usuario de GitHub>
usando como contraseña un token de acceso personal de GitHub con el permiso read:packages (Docker lo guarda, en un Mac en
el llavero; ARVA nunca lo ve ni lo guarda) y vuelve a ejecutar scripts/start.sh. O construye las imágenes aquí:
scripts/start.sh --build" >&2
    exit 1
  fi
fi

arva_compose up -d "$@" || {
  status=$?
  log_launcher launcher_compose_failed "docker compose up failed (exit status $status)" "$status"
  say "Docker Compose could not start ARVA (exit status $status). scripts/diagnostics.sh prints a report to pass on." \
      "Docker Compose no pudo iniciar ARVA (estado de salida $status). scripts/diagnostics.sh imprime un informe para compartir."
  exit "$status"
}

if ! arva_compose exec -T api python -m app.services.performance --lang "$lang"; then
  say "ARVA is running; its performance profile is in Settings → Performance." \
      "ARVA está en marcha; su perfil de rendimiento está en Ajustes → Rendimiento."
fi
if ! arva_compose exec -T api python -m app.services.locations --lang "$lang"; then
  say "Where ARVA keeps its files is in Settings → Storage." "Dónde guarda ARVA sus archivos está en Ajustes → Almacenamiento."
fi
say "Open http://localhost:8080" "Abre http://localhost:8080"
# Once the web container answers (at most ARVA_OPEN_WAIT seconds, default 60), in the default browser.
if [ "$open_browser" = 1 ]; then
  waited=0 limit=${ARVA_OPEN_WAIT:-60}
  case "$limit" in '' | *[!0-9]*) limit=60 ;; esac
  if command -v curl >/dev/null 2>&1; then
    until curl -fsS -o /dev/null --max-time 2 http://localhost:8080/ 2>/dev/null || [ "$waited" -ge "$limit" ]; do
      sleep 1
      waited=$((waited + 1))
    done
  fi
  if [ "$arva_os" = Darwin ]; then
    open http://localhost:8080 >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:8080 >/dev/null 2>&1 || true
  fi
fi
