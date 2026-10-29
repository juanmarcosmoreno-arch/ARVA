#!/bin/sh
# A diagnostic report for when ARVA's interface does not open or Docker does not start (when it does, Settings →
# Diagnostics gives a fuller one). Prints Markdown, ready to paste into a chat or an issue:
#   ARVA's version and commit, the saved locations (scripts/start.sh), Docker and Compose versions, the containers
#   (docker compose ps), the health endpoint, each configured folder's disk and mount, the last entries of
#   <data folder>/logs/errors.jsonl, and the last lines of each container's log.
#
#   scripts/diagnostics.sh [--output FILE] [--lines N]
#     --output FILE   also write the report to FILE (readable by you only)
#     --lines N       container log lines per service (default 60, at most 500)
#
# Nothing is sent anywhere. Environment variables and Docker Compose's configuration (which holds the database
# password) are never printed; every line passes the same redaction as ARVA's own reports: the home folder becomes ~,
# credentials in URLs and secret-looking values become ***, e-mail addresses, serial numbers and sequence-like text
# are replaced, and lines are cut at 400 characters.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source=SCRIPTDIR/lib/arva-locations.sh
. "$ROOT/scripts/lib/arva-locations.sh"
arva_os=$(uname -s 2>/dev/null || true)
API_HEALTH=http://127.0.0.1:8000/health
WEB_URL=http://127.0.0.1:8080/

output='' lines=60
while [ $# -gt 0 ]; do
  case "$1" in
    --output) [ $# -ge 2 ] || { echo "--output needs a file" >&2; exit 2; }; output=$2; shift 2 ;;
    --output=*) output=${1#*=}; shift ;;
    --lines) [ $# -ge 2 ] || { echo "--lines needs a number" >&2; exit 2; }; lines=$2; shift 2 ;;
    --lines=*) lines=${1#*=}; shift ;;
    -h | --help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done
case "$lines" in '' | *[!0-9]*) echo "--lines needs a number from 1 to 500" >&2; exit 2 ;; esac
if [ "$lines" -lt 1 ] || [ "$lines" -gt 500 ]; then echo "--lines needs a number from 1 to 500" >&2; exit 2; fi

# The redaction every printed line passes (POSIX tr, sed -E and awk; the same rules as app/core/redaction.py).
redact() {
  LC_ALL=C tr -d '\001-\010\013\014\016-\037\177' |
    awk -v home="${HOME:-}" '{
      if (length(home) > 1) while ((i = index($0, home)) > 0) $0 = substr($0, 1, i - 1) "~" substr($0, i + length(home))
      print
    }' |
    sed -E \
      -e 's#([A-Za-z][A-Za-z0-9+.-]*://)[^/@[:space:]"'"'"']*@#\1***@#g' \
      -e 's/(Bearer|bearer|Basic|basic)[[:space:]]+[A-Za-z0-9._~+\/=-]{8,}/\1 ***/g' \
      -e 's/(gh[pousr]_|github_pat_|sk-|xox[abprs]-|glpat-|AKIA)[A-Za-z0-9_-]{12,}/<token>/g' \
      -e 's/([A-Za-z0-9_.-]*(PASSWORD|[Pp]assword|PASSWD|passwd|PWD|pwd|SECRET|[Ss]ecret|TOKEN|[Tt]oken|API_?KEY|[Aa]pi_?[Kk]ey|CREDENTIAL|[Cc]redential|[Aa]uthorization|COOKIE|[Cc]ookie)[A-Za-z0-9_.-]*["'"'"']?[[:space:]]*[=:][[:space:]]*)("[^"]*"|[^[:space:],;&"'"'"'}]+)/\1***/g' \
      -e 's/([Ss]erial[[:space:]_-]*([Nn]umber)?([[:space:]]*\([^)]*\))?["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?)[A-Z0-9]{6,20}/\1<serial>/g' \
      -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/<email>/g' \
      -e 's#/(Users|home)/[^/[:space:]:"'"'"'`]+#~#g' \
      -e 's/[ACGTUNacgtun]{20,}/<sequence>/g' \
      -e 's#[^[:space:]/]{80,}#<long value>#g' |
    cut -c 1-400
}

fence() {
  printf '```text\n'
  sed 's/```/'"'''"'/g'
  printf '```\n'
}

compose() {
  docker compose --project-directory "$ROOT" -f "$ROOT/docker-compose.yml" "$@"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

version=$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$ROOT/apps/api/app/__init__.py" 2>/dev/null || true)
commit=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || true)
case "$commit" in '' | *[!0-9a-f]*) commit=unknown ;; esac

folder_report() {
  # $1 label, $2 path, $3 rw|ro
  if [ -z "$2" ]; then
    printf -- '- %s: a Docker volume (inside Docker Desktop'"'"'s disk image)\n' "$1"
    return 0
  fi
  if arva_inspect "$2" "$3"; then
    state="there, $([ "$3" = rw ] && echo 'readable and writable' || echo 'readable')"
  else
    state="NOT USABLE: $chk_problem (is its disk connected?)"
  fi
  printf -- '- %s: %s — %s\n' "$1" "$2" "$state"
  if [ -n "$chk_mount" ]; then
    printf '  - disk mounted at %s, %s free of %s, filesystem %s\n' "$chk_mount" "$(arva_kb "$chk_avail")" \
      "$(arva_kb "$chk_total")" "${chk_fs_name:-${chk_fs:-?}}"
  fi
}

report() {
  printf '# ARVA diagnostics (scripts/diagnostics.sh)\n\n'
  printf 'Generated %s · ARVA %s (commit %s) · %s %s %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${version:-unknown}" \
    "$commit" "$(uname -s 2>/dev/null)" "$(uname -r 2>/dev/null)" "$(uname -m 2>/dev/null)"
  printf '%s\n' "> Included: ARVA's version, the saved locations, Docker's state, the health check, each folder's disk, recent" \
    "> errors and the last container log lines. Never included: environment variables, passwords, tokens, e-mail" \
    "> addresses, serial numbers, sequences or file contents; the home folder is shown as ~. Nothing was sent anywhere." ''

  printf '## Saved locations\n\n'
  arva_config_paths
  if [ -z "$ARVA_CONFIG" ]; then
    printf 'No HOME or XDG_CONFIG_HOME, so there are no saved locations.\n\n'
  else
    printf 'Configuration file: %s (%s)\n\n' "$ARVA_CONFIG" "$([ -f "$ARVA_CONFIG" ] && echo present || echo 'not created: Docker volumes are used')"
    # arva_read_config stops the script on an unsafe file; here that is reported and the rest of the report goes on.
    if problem=$( (arva_read_config) 2>&1 >/dev/null); [ -n "$problem" ]; then printf '%s\n\n' "$problem"; fi
    if (arva_read_config) >/dev/null 2>&1; then arva_read_config 2>/dev/null; else cfg_data='' cfg_databases='' cfg_import='' cfg_extra=''; fi
    folder_report "Data folder" "$cfg_data" rw
    if [ -n "$cfg_data" ] && [ -d "$cfg_data" ]; then
      printf '  - storage marker (.arva-storage): %s; logs folder: %s\n' \
        "$([ -f "$cfg_data/.arva-storage" ] && echo present || echo MISSING)" \
        "$([ -d "$cfg_data/logs" ] && echo present || echo missing)"
    fi
    folder_report "Database folder" "$cfg_databases" rw
    if [ -n "$cfg_import" ]; then folder_report "Import folder" "$cfg_import" ro; fi
    while IFS= read -r extra; do
      if [ -n "$extra" ]; then folder_report "Added database folder" "$extra" ro; fi
    done <<EOF
$cfg_extra
EOF
    printf '\n'
  fi

  printf '## Docker\n\n'
  if ! have docker; then
    printf 'docker: not found on PATH (is Docker Desktop installed?)\n\n'
  else
    printf -- '- docker: client %s, server %s\n' "$(docker version --format '{{.Client.Version}}' 2>/dev/null || echo '?')" \
      "$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'not reachable (is Docker Desktop running?)')"
    printf -- '- docker compose: %s\n' "$(docker compose version --short 2>/dev/null || echo 'not available')"
    printf -- '- Docker Desktop gives its virtual machine: %s\n\n' \
      "$(docker info --format '{{.NCPU}} CPUs, {{.MemTotal}} bytes of memory' 2>/dev/null || echo 'unknown')"
    printf 'Containers (docker compose ps --all):\n\n'
    compose ps --all 2>&1 | head -n 40 | fence
    printf '\n'
  fi

  printf '## Health\n\n'
  if have curl; then
    printf -- '- API %s: %s\n' "$API_HEALTH" "$(curl -fsS --max-time 5 "$API_HEALTH" 2>&1 | head -c 600 || true)"
    printf -- '- Web %s: HTTP %s\n\n' "$WEB_URL" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$WEB_URL" 2>/dev/null || true)"
  else
    printf 'curl: not found on PATH\n\n'
  fi

  printf '## Recent errors (errors.jsonl, newest last)\n\n'
  if [ -n "${cfg_data:-}" ] && [ -f "$cfg_data/logs/errors.jsonl" ]; then
    tail -n 20 "$cfg_data/logs/errors.jsonl" | cut -c 1-2000 | fence
  elif [ -z "${cfg_data:-}" ] && have docker && compose exec -T api tail -n 20 /data/logs/errors.jsonl >/dev/null 2>&1; then
    compose exec -T api tail -n 20 /data/logs/errors.jsonl 2>/dev/null | cut -c 1-2000 | fence
  else
    printf 'No error log could be read (the data folder or the API container is not available).\n'
  fi
  printf '\n'

  if have docker; then
    for service in api worker web postgres redis backup; do
      printf '## Log of %s (last %s lines)\n\n' "$service" "$lines"
      compose logs --no-color --tail "$lines" "$service" 2>&1 | tail -n "$lines" | fence
      printf '\n'
    done
  fi
}

text=$(report | redact)
printf '%s\n' "$text"
if [ -n "$output" ]; then
  (umask 077 && printf '%s\n' "$text" > "$output")
  printf 'Written to %s\n' "$output" >&2
fi
