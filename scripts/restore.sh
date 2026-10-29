#!/bin/sh
# Restore ARVA's metadata (projects, samples, files, jobs, results, databases, settings) from one of the backups in
# the data folder's backups/ folder, which the backup service makes every day and when asked in Settings → Storage
# (scripts/metadata-backup.sh).
#
#   scripts/restore.sh --list          the backups, newest first
#   scripts/restore.sh latest          restore the newest backup
#   scripts/restore.sh NAME            restore the backup NAME (as --list shows it)
#   --yes                              do not ask for confirmation
#
# It uses the locations saved by scripts/start.sh, with the same checks: nothing runs when the data folder's disk is
# missing. The current metadata is backed up first (a pre-restore backup), ARVA's API, worker and backup service are
# stopped while the database is replaced, and ARVA is started again; at start-up ARVA upgrades the restored database
# to its own version. The files in the data folder are not touched.
#
# Moving the external disk to another Mac: install ARVA there, run scripts/start.sh with the same --data-dir and
# --databases-dir, then scripts/restore.sh latest (docs/installation.md, External disk).
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=SCRIPTDIR/lib/arva-locations.sh
. "$ROOT/scripts/lib/arva-locations.sh"
arva_os=$(uname -s 2>/dev/null || true)

usage() {
  say "Usage: scripts/restore.sh --list | [--yes] latest | [--yes] NAME" "Uso: scripts/restore.sh --list | [--yes] latest | [--yes] NOMBRE"
}

yes=0 list=0 wanted=''
for arg do
  case "$arg" in
    -y | --yes) yes=1 ;;
    --list) list=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      usage >&2
      exit 2
      ;;
    *)
      if [ -n "$wanted" ]; then
        usage >&2
        exit 2
      fi
      wanted=$arg
      ;;
  esac
done
if [ "$list" = 0 ] && [ -z "$wanted" ]; then
  usage >&2
  exit 2
fi
case "$wanted" in
  */*)
    warn "Give the backup's name as --list shows it, not a path." "Indica el nombre de la copia como lo muestra --list, no una ruta."
    exit 2
    ;;
esac

arva_config_paths
arva_read_config
if ! arva_check_locations; then
  say "Nothing was changed: connect the disk of the data folder first." "No se cambió nada: conecta primero el disco de la carpeta de datos." >&2
  exit 1
fi
arva_write_override

if [ "$list" = 1 ]; then
  arva_compose run --rm --no-deps -T backup list
  exit 0
fi

arva_compose up -d --wait postgres
chosen=$wanted
if [ "$wanted" = latest ]; then chosen=$(arva_compose run --rm --no-deps -T backup list | head -n 1); fi
if [ -z "$chosen" ]; then
  say "There is no backup in the data folder yet; nothing was changed." "Todavía no hay ninguna copia en la carpeta de datos; no se cambió nada." >&2
  exit 1
fi

say "This replaces ARVA's current metadata with the backup $chosen. The current metadata is backed up first, and no file in the data folder is touched." \
    "Esto sustituye los metadatos actuales de ARVA por la copia $chosen. Antes se hace una copia de los metadatos actuales, y no se toca ningún archivo de la carpeta de datos."
if [ "$yes" = 0 ]; then
  printf '%s ' "$(say "Type yes to continue:" "Escribe yes para continuar:")"
  answer=''
  read -r answer || true
  if [ "$answer" != yes ]; then
    say "Nothing was changed." "No se cambió nada."
    exit 1
  fi
fi

arva_compose stop api worker backup
restored=0
if arva_compose run --rm --no-deps -T backup restore "$chosen"; then restored=1; fi
arva_compose up -d
if [ "$restored" = 1 ]; then
  say "Restored $chosen. ARVA is starting again: open http://localhost:8080" "Restaurada $chosen. ARVA se está iniciando de nuevo: abre http://localhost:8080"
else
  say "The restore failed and the metadata was not changed (see the messages above)." "La restauración falló y los metadatos no se cambiaron (consulta los mensajes anteriores)." >&2
  exit 1
fi
