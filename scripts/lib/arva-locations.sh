# shellcheck shell=sh
# shellcheck disable=SC2154 # arva_os and ROOT are set by the script that sources this file.
# Where ARVA keeps its files on this computer, shared by scripts/start.sh, scripts/restore.sh and scripts/backup.sh
# (sourced by them; it only defines functions and variables).
#
# The locations are saved in ${XDG_CONFIG_HOME:-$HOME/.config}/arva/arva.conf (mode 600) as KEY=VALUE lines. The
# file is read line by line and never run (no sourcing, no eval): a value is only ever a path string.
#
#   ARVA_DATA_DIR             projects (raw, processed, results, reports, logs) and the metadata backups -> /data
#   ARVA_DATABASES_DIR        reference databases ARVA downloads -> /databases
#   ARVA_IMPORT_DIR           sequencing runs to import from, read-only -> /import
#   ARVA_ADD_DATABASES        existing database folders used in place, read-only -> /databases-external/<n>
#                             (repeatable; <n> is the POSIX cksum of the folder's path, so it stays the same)
#   ARVA_*_DIR_MOUNT          the disk (mount point) each writable folder was on when it was chosen
#
# Every folder is checked before Docker starts: an absolute path to an existing folder, readable (and writable for
# data and databases), on the disk it was on when chosen. On a Mac, diskutil names the folder's filesystem, and
# exFAT or FAT gets a warning (no symbolic links or Unix permissions; the Bakta database contains a symbolic link).
# The folders are passed to Docker Compose in a generated override file as bind mounts with create_host_path:
# false, so Docker refuses to start rather than create an empty folder on the startup disk when a disk is missing.
# The paths reach that file only as ${VARIABLE} references, never as YAML text.
#
# Not yet validated on a real Mac: see docs/installation.md.

nl='
'
cr=$(printf '\r')
LOW_SPACE_KB=20971520
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
  es*) lang=es ;;
  *) lang=en ;;
esac

say() {
  if [ "$lang" = es ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

warn() {
  say "$1" "$2" >&2
}

# A path in single quotes for a command the user may copy (a ' inside becomes '\'').
shquote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# Without an absolute XDG_CONFIG_HOME or HOME there are no saved locations (and none can be saved).
arva_config_paths() {
  ARVA_CONFIG_DIR='' ARVA_CONFIG='' ARVA_OVERRIDE=''
  case "${XDG_CONFIG_HOME:-}" in
    /*) base=$XDG_CONFIG_HOME ;;
    *) case "${HOME:-}" in /*) base=$HOME/.config ;; *) return 0 ;; esac ;;
  esac
  ARVA_CONFIG_DIR=$base/arva
  ARVA_CONFIG=$ARVA_CONFIG_DIR/arva.conf
  ARVA_OVERRIDE=$ARVA_CONFIG_DIR/compose.storage.yml
}

list_add() {
  if [ -z "$1" ]; then printf '%s' "$2"; else printf '%s\n%s' "$1" "$2"; fi
}

list_has() {
  case "$nl$1$nl" in *"$nl$2$nl"*) return 0 ;; esac
  return 1
}

list_remove() {
  out=''
  while IFS= read -r item; do
    if [ -n "$item" ] && [ "$item" != "$2" ]; then out=$(list_add "$out" "$item"); fi
  done <<EOF
$1
EOF
  printf '%s' "$out"
}

arva_read_config() {
  cfg_data='' cfg_data_mount='' cfg_databases='' cfg_databases_mount='' cfg_import='' cfg_extra=''
  if [ -z "$ARVA_CONFIG" ] || { [ ! -e "$ARVA_CONFIG" ] && [ ! -L "$ARVA_CONFIG" ]; }; then return 0; fi
  if [ -L "$ARVA_CONFIG" ] || [ ! -f "$ARVA_CONFIG" ] || [ ! -O "$ARVA_CONFIG" ]; then
    warn "$ARVA_CONFIG must be a regular file of yours (not a link); ARVA did not start." \
         "$ARVA_CONFIG debe ser un archivo normal tuyo (no un enlace); ARVA no se inició."
    exit 1
  fi
  if [ -n "$(find "$ARVA_CONFIG" -prune \( -perm -g=w -o -perm -o=w \) -print)" ]; then
    warn "Others may change $ARVA_CONFIG; ARVA did not start. Fix it with: chmod 600 $(shquote "$ARVA_CONFIG")" \
         "Otros usuarios pueden modificar $ARVA_CONFIG; ARVA no se inició. Corrígelo con: chmod 600 $(shquote "$ARVA_CONFIG")"
    exit 1
  fi
  n=0
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    line=${line%"$cr"}
    case "$line" in '' | '#'*) continue ;; esac
    case "$line" in
      *=*) ;;
      *)
        warn "$ARVA_CONFIG line $n is not KEY=VALUE; ignored." "La línea $n de $ARVA_CONFIG no es CLAVE=VALOR; se ignora."
        continue
        ;;
    esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in
      ARVA_DATA_DIR) cfg_data=$value ;;
      ARVA_DATA_DIR_MOUNT) cfg_data_mount=$value ;;
      ARVA_DATABASES_DIR) cfg_databases=$value ;;
      ARVA_DATABASES_DIR_MOUNT) cfg_databases_mount=$value ;;
      ARVA_IMPORT_DIR) cfg_import=$value ;;
      ARVA_ADD_DATABASES)
        if [ -n "$value" ] && ! list_has "$cfg_extra" "$value"; then cfg_extra=$(list_add "$cfg_extra" "$value"); fi
        ;;
      *) warn "$ARVA_CONFIG line $n: unknown key ignored." "Línea $n de $ARVA_CONFIG: clave desconocida, se ignora." ;;
    esac
  done < "$ARVA_CONFIG"
}

arva_write_config() {
  if [ -z "$ARVA_CONFIG" ]; then
    warn "Neither HOME nor XDG_CONFIG_HOME is set, so the locations cannot be saved." \
         "No están definidos HOME ni XDG_CONFIG_HOME, así que no se pueden guardar las ubicaciones."
    exit 1
  fi
  (
    umask 077
    mkdir -p "$ARVA_CONFIG_DIR" || exit 1
    tmp=$ARVA_CONFIG.tmp.$$
    {
      printf '%s\n' "# ARVA storage locations, written by scripts/start.sh. KEY=VALUE, one per line: read line by line, never run."
      if [ -n "$cfg_data" ]; then printf 'ARVA_DATA_DIR=%s\nARVA_DATA_DIR_MOUNT=%s\n' "$cfg_data" "$cfg_data_mount"; fi
      if [ -n "$cfg_databases" ]; then
        printf 'ARVA_DATABASES_DIR=%s\nARVA_DATABASES_DIR_MOUNT=%s\n' "$cfg_databases" "$cfg_databases_mount"
      fi
      if [ -n "$cfg_import" ]; then printf 'ARVA_IMPORT_DIR=%s\n' "$cfg_import"; fi
      while IFS= read -r item; do
        if [ -n "$item" ]; then printf 'ARVA_ADD_DATABASES=%s\n' "$item"; fi
      done <<EOF
$cfg_extra
EOF
    } > "$tmp" && chmod 600 "$tmp" && mv -f "$tmp" "$ARVA_CONFIG"
  )
}

# The mount point, total and available 1024-byte blocks of the filesystem holding $1 (df -Pk, POSIX format; on macOS
# -P also leaves out the inode columns, file_cmds df/df.c). The filesystem name and the mount point may contain
# spaces, so the four numbers are matched before the mount point, which starts with "/".
arva_df() {
  chk_mount='' chk_total='' chk_avail=''
  line=$(LC_ALL=C df -Pk -- "$1" 2>/dev/null | sed -n '$p') || line=''
  fields=$(printf '%s\n' "$line" |
    sed -n 's/^.*[[:space:]]\([0-9][0-9]*\)[[:space:]][[:space:]]*[0-9][0-9]*[[:space:]][[:space:]]*\([0-9][0-9]*\)[[:space:]][[:space:]]*[^[:space:]]*[[:space:]][[:space:]]*\(\/.*\)$/\1 \2 \3/p')
  if [ -n "$fields" ]; then
    chk_total=${fields%% *}
    rest=${fields#* }
    chk_avail=${rest%% *}
    chk_mount=${rest#* }
  fi
}

# The <string> after <key>$1</key> in a property list ($2), or nothing.
plist_string() {
  printf '%s\n' "$2" | awk -v key="<key>$1</key>" '
    function value(s) { if (match(s, /<string>[^<]*<\/string>/)) { print substr(s, RSTART + 8, RLENGTH - 17); return 1 } return 0 }
    found { value($0); exit }
    index($0, key) { rest = substr($0, index($0, key) + length(key)); if (value(rest)) exit; found = 1 }'
}

# The filesystem of the folder $1 on the disk mounted at $2: on a Mac FilesystemType ("apfs", "hfs", "exfat"; the
# bundle name diskutil shows as "Type (Bundle)") and FilesystemName of `diskutil info -plist <mount point>`
# (diskutil(8): info accepts a mount point; keys as parsed by corpnewt/gibMacOS and brokeyourbike/mountefi), on
# Linux GNU stat's filesystem type. chk_fat is 1 for exFAT and FAT ("msdos" is assumed to be FAT's bundle name and
# not confirmed, so the name is checked too).
arva_filesystem() {
  chk_fs='' chk_fat=0
  fs_raw_name=''
  if [ "$arva_os" = Darwin ]; then
    plist=$(diskutil info -plist "$2" 2>/dev/null) || plist=''
    fs_raw_type=$(plist_string FilesystemType "$plist")
    fs_raw_name=$(plist_string FilesystemName "$plist")
    if [ -z "$fs_raw_name" ]; then fs_raw_name=$(plist_string FilesystemUserVisibleName "$plist"); fi
  else
    fs_raw_type=$(stat -f -c %T -- "$1" 2>/dev/null) || fs_raw_type=''
  fi
  chk_fs=$(printf '%s' "$fs_raw_type" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ/' 'abcdefghijklmnopqrstuvwxyz-' | LC_ALL=C tr -cd 'a-z0-9_+-' | cut -c 1-32)
  chk_fs_name=$(printf '%s' "$fs_raw_name" | LC_ALL=C tr -cd '[:print:]' | cut -c 1-60)
  case "$chk_fs" in exfat | msdos | vfat | fat | fat12 | fat16 | fat32) chk_fat=1 ;; esac
  case "$chk_fs_name" in *[Ff][Aa][Tt]*) chk_fat=1 ;; esac
  if [ -z "$chk_fs" ] && [ "$chk_fat" = 1 ]; then
    case "$chk_fs_name" in *[Ee][Xx][Ff][Aa][Tt]*) chk_fs=exfat ;; *) chk_fs=msdos ;; esac
  fi
}

# Checks the folder $1 ($2: rw or ro). On success sets chk_real (the path with links resolved), the mount point,
# space and filesystem; on failure chk_problem names the problem.
arva_inspect() {
  chk_real='' chk_problem='' chk_mount='' chk_total='' chk_avail='' chk_fs='' chk_fs_name='' chk_fat=0
  p=$1
  case "$p" in /*) ;; *) chk_problem=not_absolute; return 1 ;; esac
  if [ "$(printf '%s' "$p" | LC_ALL=C tr -d '\001-\037\177')" != "$p" ]; then chk_problem=control; return 1; fi
  if [ "${#p}" -gt 1024 ]; then chk_problem=too_long; return 1; fi
  if [ ! -d "$p" ]; then chk_problem=missing; return 1; fi
  if ! chk_real=$(CDPATH='' cd -P -- "$p" 2>/dev/null && pwd -P); then chk_problem=not_readable; return 1; fi
  if [ "$chk_real" = / ]; then chk_problem=root; return 1; fi
  if [ ! -r "$chk_real" ] || [ ! -x "$chk_real" ]; then chk_problem=not_readable; return 1; fi
  if [ "$2" = rw ] && [ ! -w "$chk_real" ]; then chk_problem=not_writable; return 1; fi
  arva_df "$chk_real"
  arva_filesystem "$chk_real" "$chk_mount"
  return 0
}

# The message for chk_problem about the folder $2 of role $1 (its label in $3/$4).
arva_problem() {
  q=$(shquote "$2")
  case "$chk_problem" in
    not_absolute) say "The $3 folder must be an absolute path (starting with /): $2" "La carpeta de $4 debe ser una ruta absoluta (que empiece por /): $2" ;;
    control) say "The $3 folder's path contains control characters." "La ruta de la carpeta de $4 contiene caracteres de control." ;;
    too_long) say "The $3 folder's path is longer than 1024 characters." "La ruta de la carpeta de $4 tiene más de 1024 caracteres." ;;
    missing)
      say "The $3 folder $2 does not exist. If it is on an external disk, connect the disk and run this script again; otherwise create the folder first: mkdir -p $q" \
          "La carpeta de $4 $2 no existe. Si está en un disco externo, conéctalo y vuelve a ejecutar este script; si no, crea primero la carpeta: mkdir -p $q"
      ;;
    root) say "The $3 folder cannot be the root folder /." "La carpeta de $4 no puede ser la carpeta raíz /." ;;
    not_readable) say "ARVA cannot read the $3 folder $2 (check its permissions)." "ARVA no puede leer la carpeta de $4 $2 (revisa sus permisos)." ;;
    not_writable) say "ARVA cannot write to the $3 folder $2 (check its permissions, or whether the disk is read-only)." "ARVA no puede escribir en la carpeta de $4 $2 (revisa sus permisos o si el disco es de solo lectura)." ;;
    moved)
      say "The $3 folder $2 is not on the disk it was on when you chose it ($chk_saved_mount) but on ${chk_mount:-?}: that disk is probably not connected. Connect it and run this script again. If you moved the folder on purpose, choose it again with --$1-dir."  \
          "La carpeta de $4 $2 no está en el disco en el que estaba al elegirla ($chk_saved_mount) sino en ${chk_mount:-?}: probablemente ese disco no está conectado. Conéctalo y vuelve a ejecutar este script. Si moviste la carpeta a propósito, vuelve a elegirla con --$1-dir."
      ;;
  esac
}

# A read-only folder that cannot be used: a missing one is most likely on a disk that is not connected.
arva_unavailable() {
  if [ "$chk_problem" = missing ]; then
    warn "The $3 folder $2 is not available: is its disk connected?" "La carpeta de $4 $2 no está disponible: ¿está conectado su disco?"
  else
    arva_problem "$1" "$2" "$3" "$4" >&2
  fi
}

arva_kb() {
  if [ -n "$1" ]; then awk -v kb="$1" 'BEGIN { printf "%.1f GB", kb / 1048576 }'; else printf '?'; fi
}

# One line about a checked folder, and its warnings.
arva_report() {
  fs=${chk_fs_name:-$chk_fs}
  printf '  %-30s %s\n' "$1" "$chk_real"
  say "  $(printf '%-30s' '') ${fs:-?} · $(arva_kb "$chk_avail") free of $(arva_kb "$chk_total")" \
      "  $(printf '%-30s' '') ${fs:-?} · $(arva_kb "$chk_avail") libres de $(arva_kb "$chk_total")"
  if [ "$chk_fat" = 1 ]; then
    warn "  Warning: $chk_real is on an exFAT or FAT disk, which keeps no symbolic links or Unix permissions (the Bakta database contains a symbolic link). Use a disk formatted as APFS or Mac OS Extended for ARVA." \
         "  Aviso: $chk_real está en un disco exFAT o FAT, que no guarda enlaces simbólicos ni permisos Unix (la base de datos de Bakta contiene un enlace simbólico). Usa para ARVA un disco con formato APFS o Mac OS Plus."
  fi
  if [ "$2" = rw ] && [ -n "$chk_avail" ] && [ "$chk_avail" -lt "$LOW_SPACE_KB" ]; then
    warn "  Warning: less than 20 GB free on the disk of $chk_real." "  Aviso: quedan menos de 20 GB libres en el disco de $chk_real."
  fi
  if [ "$arva_os" = Darwin ]; then
    case "$chk_real" in
      /Users/* | /Volumes/* | /private/* | /tmp/* | /var/folders/*) ;;
      *)
        warn "  Docker Desktop shares /Users, /Volumes, /private, /tmp and /var/folders by default: add $chk_real in Docker Desktop → Settings → Resources → File sharing, or Docker refuses to mount it (\"Mounts denied\")." \
             "  Docker Desktop comparte /Users, /Volumes, /private, /tmp y /var/folders por omisión: añade $chk_real en Docker Desktop → Settings → Resources → File sharing, o Docker se negará a montarla (\"Mounts denied\")."
        ;;
    esac
  fi
}

# On a Mac, a folder on the startup disk is not on an external disk (a note when a folder is chosen).
arva_startup_disk_note() {
  if [ "$arva_os" = Darwin ]; then
    case "$chk_mount" in
      / | /System/Volumes/Data)
        warn "  Note: $chk_real is on the Mac's startup disk, not on an external disk." "  Nota: $chk_real está en el disco de arranque de la Mac, no en un disco externo."
        ;;
    esac
  fi
}

# Checks every saved location and exports what Docker Compose and ARVA need (the ARVA_HOST_* strings are for
# display only; ARVA validates them again). Returns 1 when ARVA must not start.
arva_check_locations() {
  ok=0
  unset ARVA_HOST_DATA_DIR ARVA_HOST_DATA_FS ARVA_HOST_DATABASES_DIR ARVA_HOST_DATABASES_FS ARVA_HOST_IMPORT_DIR ARVA_HOST_IMPORT_FS
  loc_data='' loc_databases='' loc_import='' loc_slots='' loc_roots='' loc_mounted=''
  for role in data databases; do
    if [ "$role" = data ]; then
      path=$cfg_data chk_saved_mount=$cfg_data_mount en='data' es='datos'
      label=$(say "Data (projects, backups)" "Datos (proyectos, copias)")
    else
      path=$cfg_databases chk_saved_mount=$cfg_databases_mount en='databases' es='bases de datos'
      label=$(say "Databases (downloads)" "Bases de datos (descargas)")
    fi
    [ -n "$path" ] || continue
    if arva_inspect "$path" rw && [ -n "$chk_saved_mount" ] && [ "$chk_mount" != "$chk_saved_mount" ]; then
      chk_problem=moved
    fi
    if [ -n "$chk_problem" ]; then
      arva_problem "$role" "$path" "$en" "$es" >&2
      ok=1
      continue
    fi
    arva_report "$label" rw
    if [ "$role" = data ]; then
      loc_data=$chk_real
      export ARVA_HOST_DATA_DIR="$chk_real" ARVA_HOST_DATA_FS="$chk_fs"
    else
      loc_databases=$chk_real
      export ARVA_HOST_DATABASES_DIR="$chk_real" ARVA_HOST_DATABASES_FS="$chk_fs"
    fi
  done
  if [ -n "$loc_data" ] && [ "$loc_data" = "$loc_databases" ]; then
    warn "The data and database folders must be different folders." "Las carpetas de datos y de bases de datos deben ser distintas."
    ok=1
  fi
  if [ -n "$cfg_import" ]; then
    if arva_inspect "$cfg_import" ro; then
      arva_report "$(say "Import (read-only)" "Importación (solo lectura)")" ro
      loc_import=$chk_real
      export ARVA_HOST_IMPORT_DIR="$chk_real" ARVA_HOST_IMPORT_FS="$chk_fs"
    else
      arva_unavailable import "$cfg_import" "import" "importación"
      warn "  ARVA starts without it." "  ARVA se inicia sin ella."
    fi
  fi
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    slot=$(printf '%s' "$path" | cksum | awk '{ print $1 }')
    if list_has "$loc_slots" "$slot"; then
      warn "Two database folders share the mount number $slot; remove one with --remove-databases." \
           "Dos carpetas de bases de datos comparten el número de montaje $slot; quita una con --remove-databases."
      ok=1
      continue
    fi
    loc_slots=$(list_add "$loc_slots" "$slot")
    loc_roots="$loc_roots${loc_roots:+,}\"/databases-external/$slot\""
    if arva_inspect "$path" ro; then
      arva_report "$(say "Database folder (read-only)" "Carpeta de bases de datos (solo lectura)")" ro
      export "ARVA_HOST_EXTERNAL_DB_$slot=$chk_real" "ARVA_HOST_EXTERNAL_DB_${slot}_FS=$chk_fs"
      loc_mounted=$(list_add "$loc_mounted" "$slot")
    else
      export "ARVA_HOST_EXTERNAL_DB_$slot=$path" "ARVA_HOST_EXTERNAL_DB_${slot}_FS="
      arva_unavailable databases "$path" "database" "bases de datos"
      warn "  ARVA starts without it; its databases are shown as unavailable (disk not connected) and are not deleted." \
           "  ARVA se inicia sin ella; sus bases de datos se muestran como no disponibles (disco no conectado) y no se borran."
    fi
  done <<EOF
$cfg_extra
EOF
  return "$ok"
}

arva_mount() {
  # shellcheck disable=SC2016 # ${...} is for Docker Compose to read.
  printf '  %s: &%s\n    type: bind\n    source: ${%s:?set by scripts/start.sh}\n    target: %s\n' "$1" "$1" "$2" "$3"
  if [ "$4" = ro ]; then printf '    read_only: true\n'; fi
  printf '    bind:\n      create_host_path: false\n'
}

# The Compose override for the checked locations, or no file when every location is a Docker volume.
arva_write_override() {
  if [ -z "$loc_data$loc_databases$loc_import$loc_slots" ]; then
    if [ -n "$ARVA_OVERRIDE" ]; then rm -f "$ARVA_OVERRIDE"; fi
    arva_use_override=0
    return 0
  fi
  (
    umask 077
    mkdir -p "$ARVA_CONFIG_DIR" || exit 1
    tmp=$ARVA_OVERRIDE.tmp.$$
    {
      printf '%s\n' "# Generated by scripts/start.sh at every start from the locations it keeps; changes here are overwritten." \
        "# Host folders are bind mounts with create_host_path: false, so Docker refuses to start a container whose folder" \
        "# is missing instead of creating an empty one (Compose specification, services.volumes, long syntax). Paths" \
        "# appear only as variables, which scripts/start.sh sets after checking each folder." \
        "x-arva-mounts:"
      if [ -n "$loc_data" ]; then arva_mount data ARVA_HOST_DATA_DIR /data rw; fi
      if [ -n "$loc_databases" ]; then arva_mount databases ARVA_HOST_DATABASES_DIR /databases rw; fi
      if [ -n "$loc_import" ]; then arva_mount import ARVA_HOST_IMPORT_DIR /import ro; fi
      while IFS= read -r slot; do
        if [ -n "$slot" ]; then arva_mount "external-$slot" "ARVA_HOST_EXTERNAL_DB_$slot" "/databases-external/$slot" ro; fi
      done <<EOF
$loc_mounted
EOF
      printf 'services:\n'
      for service in api worker; do
        printf '  %s:\n' "$service"
        if [ -n "$loc_slots" ]; then
          printf '    environment:\n      ARVA_EXTERNAL_DB_ROOTS: '"'"'[%s]'"'"'\n' "$loc_roots"
          while IFS= read -r slot; do
            if [ -n "$slot" ]; then
              # shellcheck disable=SC2016 # ${...} is for Docker Compose to read.
              printf '      ARVA_HOST_EXTERNAL_DB_%s: ${ARVA_HOST_EXTERNAL_DB_%s:?set by scripts/start.sh}\n      ARVA_HOST_EXTERNAL_DB_%s_FS: ${ARVA_HOST_EXTERNAL_DB_%s_FS:-}\n' "$slot" "$slot" "$slot" "$slot"
            fi
          done <<EOF
$loc_slots
EOF
        fi
        printf '    volumes:\n'
        if [ -n "$loc_data" ]; then printf '      - *data\n'; fi
        if [ -n "$loc_databases" ]; then printf '      - *databases\n'; fi
        if [ -n "$loc_import" ]; then printf '      - *import\n'; fi
        while IFS= read -r slot; do
          if [ -n "$slot" ]; then printf '      - *external-%s\n' "$slot"; fi
        done <<EOF
$loc_mounted
EOF
        if [ -z "$loc_data$loc_databases$loc_import$loc_mounted" ]; then printf '      []\n'; fi
      done
      if [ -n "$loc_data" ]; then printf '  backup:\n    volumes:\n      - *data\n'; fi
    } > "$tmp" && mv -f "$tmp" "$ARVA_OVERRIDE"
  ) || return 1
  arva_use_override=1
}

arva_compose() {
  if [ "${arva_use_override:-0}" = 1 ]; then
    docker compose -f "$ROOT/docker-compose.yml" -f "$ARVA_OVERRIDE" "$@"
  else
    docker compose "$@"
  fi
}
