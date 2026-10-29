#!/bin/sh
# Start ARVA with Docker Compose (`docker compose up -d`; extra arguments, such as --build, are passed on).
#
# On a Mac it first reads which Mac this is (sysctl, system_profiler, sw_vers) and what Docker Desktop gives its
# Linux virtual machine (docker info), and passes these facts to ARVA as ARVA_HOST_* variables, so that ARVA can
# choose a performance profile. Once ARVA runs it prints the profile and, when Docker Desktop's CPUs or memory do
# not suit it, what to set in Docker Desktop. Elsewhere it only starts ARVA. Nothing leaves this computer; of
# system_profiler's report only the model name, chip and core counts are kept (never the serial number).
#
# Not yet validated on a real Mac: see docs/installation.md.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

lang=en
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
  es*) lang=es ;;
esac

say() {
  if [ "$lang" = es ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

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

if [ "$(uname -s 2>/dev/null || true)" = Darwin ]; then
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

docker compose up -d "$@"

if ! docker compose exec -T api python -m app.services.performance --lang "$lang"; then
  say "ARVA is running; its performance profile is in Settings → Performance." \
      "ARVA está en marcha; su perfil de rendimiento está en Ajustes → Rendimiento."
fi
say "Open http://localhost:8080" "Abre http://localhost:8080"
