# shellcheck shell=sh
# shellcheck disable=SC2154,SC2034 # arva_os, lang, cr and want_* are shared with scripts/start.sh and arva-locations.sh.
# The questions scripts/start.sh asks the first time it runs in a terminal (no saved locations yet), or with --setup:
# Docker Desktop installed and running, which disk keeps ARVA's data and databases, which existing database folders
# to use read-only, and on Apple silicon which image architecture. The answers only fill the same variables as the
# options (--data-dir, --databases-dir, --add-databases, --import-dir, --platform); start.sh checks and saves them.
#
# Not yet validated on a real Mac: tested with fake executables (apps/api/tests/test_first_run.py).

# macOS Terminal sets LANG from the system language only when its "Set locale environment variables on startup"
# setting is on; without any locale variable, the Mac's own language (AppleLocale, e.g. es_AR) is used instead.
if [ "$arva_os" = Darwin ] && [ -z "${LC_ALL:-}${LC_MESSAGES:-}${LANG:-}" ]; then
  case "$(defaults read -g AppleLocale 2>/dev/null || true)" in es*) lang=es ;; esac
fi

# Docker Desktop's settings file: settings-store.json since Docker Desktop 4.35, settings.json before. Prints the
# first one that exists and can be read, or nothing.
docker_settings_file() {
  dir=${HOME:+$HOME/Library/Group Containers/group.com.docker}
  [ -n "$dir" ] || return 0
  for file in "$dir/settings-store.json" "$dir/settings.json"; do
    if [ -f "$file" ] && [ -r "$file" ]; then
      printf '%s' "$file"
      return 0
    fi
  done
}

# Docker Desktop's "Use Rosetta for x86_64/amd64 emulation on Apple Silicon" (Settings → General), from its settings
# file (Docker's settings reference names the key useVirtualizationFrameworkRosetta; the spelling in the file is not
# documented, so it is matched without regard to case). Prints on, off, default or unknown. "default": the file was
# read but has no such key. On one real Mac (Docker Desktop with settings-store.json, keys in PascalCase) the file
# stored only the settings changed from Docker Desktop's defaults: no Rosetta key although Rosetta was on in the
# window. A missing key therefore means "Docker Desktop's default", not "off"; what that default is, Docker's
# documentation does not state consistently. "unknown": no settings file could be read.
docker_rosetta() {
  file=$(docker_settings_file)
  if [ -z "$file" ]; then
    printf unknown
    return 0
  fi
  if ! grep -iq '"usevirtualizationframeworkrosetta"' "$file" 2>/dev/null; then
    printf default
    return 0
  fi
  value=$(grep -io '"usevirtualizationframeworkrosetta"[[:space:]]*:[[:space:]]*[a-z]*' "$file" 2>/dev/null |
    head -n 1 | sed 's/.*:[[:space:]]*//' | tr '[:upper:]' '[:lower:]')
  case "$value" in
    true) printf on ;;
    false) printf off ;;
    *) printf unknown ;;
  esac
}

# The folders Docker Desktop shares with its virtual machine (Settings → File sharing), one per line, from the same
# settings file (key filesharingDirectories, matched without regard to case; not documented either, and not yet seen
# in a real file: on the Mac above, with the default list, the file had no such key). Prints nothing when the file
# or the key cannot be read. The strings are read as JSON strings (a comma or ] inside a path is kept), and the
# escapes \" \\ \/ and \u0026 \u003c \u003e are decoded (Go's JSON encoder writes &, < and > that way; whether
# Docker Desktop's does is not known).
docker_file_sharing() {
  file=$(docker_settings_file)
  [ -n "$file" ] || return 0
  tr -d '\n\r' < "$file" 2>/dev/null |
    grep -ioE '"filesharingdirectories"[[:space:]]*:[[:space:]]*\[([[:space:]]*"([^"\\]|\\.)*"[[:space:]]*,?)*[[:space:]]*\]' |
    head -n 1 | sed 's/^[^[]*\[//' | grep -oE '"([^"\\]|\\.)*"' | sed 's/^"//; s/"$//' |
    sed 's/\\u0026/\&/g; s/\\u003[cC]/</g; s/\\u003[eE]/>/g; s/\\\//\//g; s/\\"/"/g; s/\\\\/\\/g' | sed -n '/^\//p'
}

# The disk /Volumes/<Disk> that holds the folder $1, or nothing for a folder elsewhere (ARVA_VOLUMES_ROOT stands for
# /Volumes in the tests).
volume_of() {
  vroot=${ARVA_VOLUMES_ROOT:-/Volumes}
  case "$1" in
    "$vroot"/?*)
      rest=${1#"$vroot"/}
      printf '%s/%s' "$vroot" "${rest%%/*}"
      ;;
  esac
}

# The folder $1 is covered by an entry of the File sharing list $2.
shared_by() {
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    case "$1/" in "${s%/}"/*) return 0 ;; esac
  done <<EOF
$2
EOF
  return 1
}

# How Docker Desktop shares the folder $1 on the disk $2 (/Volumes/<Disk>), from its File sharing list ($3, one per
# line, empty when the settings file has none):
#   disk         a share of the disk itself or of a folder on it covers the folder (what ARVA asks for);
#   both         that, and also /Volumes (or /): which of the two Docker uses has not been confirmed;
#   parent       only /Volumes (or /) covers it;
#   defaults     the settings file has no list, so Docker Desktop's defaults apply (they include /Volumes);
#   not_shared   the list covers neither the folder nor /Volumes ("mounts denied" when ARVA starts);
#   unknown      no settings file could be read.
# Observed on a real Mac: through the /Volumes share, the free space ARVA reads inside Docker is the startup disk's
# (df in the container showed /run/host_mark/Volumes with the startup disk's size); with /Volumes/<Disk> shared
# instead (and /Volumes removed), the external disk's own.
docker_share_state() {
  if [ -z "$(docker_settings_file)" ]; then
    printf unknown
    return 0
  fi
  if [ -z "$3" ]; then
    printf defaults
    return 0
  fi
  own=0 parent=0 vroot=${ARVA_VOLUMES_ROOT:-/Volumes}
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    s=${s%/}
    case "$1/" in "$s"/*) ;; *) continue ;; esac
    case "$s" in
      "$2" | "$2"/*) own=1 ;;
      *) parent=1 ;;
    esac
  done <<EOF
$3
EOF
  if [ "$own" = 1 ] && [ "$parent" = 1 ]; then
    printf both
  elif [ "$own" = 1 ]; then
    printf disk
  elif [ "$parent" = 1 ]; then
    printf parent
  else
    printf not_shared
  fi
}

# The entry of the File sharing list $3 above the disk $2 that covers the folder $1 (/Volumes, or / ...), or nothing.
parent_share() {
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    t=${s%/}
    case "$1/" in "$t"/*) ;; *) continue ;; esac
    case "$t" in "$2" | "$2"/*) ;; *) printf '%s' "${t:-/}"; return 0 ;; esac
  done <<EOF
$3
EOF
}

# The steps that share the disk $1 itself, and remove the share above it ($2, e.g. /Volumes) when one is listed.
sharing_steps() {
  if [ -n "${2:-}" ]; then
    say "    Docker Desktop → Settings → File sharing (under Resources in some versions) → + → Cmd+Shift+G → type $1 →
    Open; then select $2 in the list and remove it (−) → Apply (& restart). Then run ARVA again." \
        "    Docker Desktop → Settings → File sharing (en algunas versiones dentro de Resources) → + → Cmd+Shift+G →
    escribir $1 → Abrir; luego seleccionar $2 en la lista y quitarla (−) → Apply (& restart). Después volver
    a abrir ARVA."
  else
    say "    Docker Desktop → Settings → File sharing (under Resources in some versions) → + → Cmd+Shift+G → type $1 →
    Open → Apply (& restart). Then run ARVA again." \
        "    Docker Desktop → Settings → File sharing (en algunas versiones dentro de Resources) → + → Cmd+Shift+G →
    escribir $1 → Abrir → Apply (& restart). Después volver a abrir ARVA."
  fi
}

# What to do about each folder of the list $1 (one per line): a folder the File sharing list does not cover ("mounts
# denied"), and a folder on a disk under /Volumes that Docker Desktop does not share as that disk. Every folder is
# checked (two folders on one disk may be covered differently); the advice is printed once per disk and state.
# Prints nothing when all is well. Sets sharing_bad to the disks (or folders) with a problem.
sharing_report() {
  sharing_bad=''
  shared=$(docker_file_sharing)
  vroot=${ARVA_VOLUMES_ROOT:-/Volumes}
  seen=''
  while IFS= read -r folder; do
    [ -n "$folder" ] || continue
    disk=$(volume_of "$folder")
    if [ -z "$disk" ]; then
      if [ -n "$shared" ] && ! shared_by "$folder" "$shared"; then
        sharing_bad=$(list_add "$sharing_bad" "$folder")
        say "  Docker Desktop does not share $folder: add it in Docker Desktop → Settings → File sharing (under Resources
  in some versions), then Apply (& restart), or Docker refuses to mount it (\"mounts denied\")." \
            "  Docker Desktop no comparte $folder: agregarla en Docker Desktop → Settings → File sharing (en algunas
  versiones dentro de Resources) y luego Apply (& restart), o Docker se negará a montarla (\"mounts denied\")."
      fi
      continue
    fi
    state=$(docker_share_state "$folder" "$disk" "$shared")
    case "$state" in disk | unknown) continue ;; esac
    if ! list_has "$sharing_bad" "$disk"; then sharing_bad=$(list_add "$sharing_bad" "$disk"); fi
    if list_has "$seen" "$disk:$state"; then continue; fi
    seen=$(list_add "$seen" "$disk:$state")
    parent=$(parent_share "$folder" "$disk" "$shared")
    case "$state" in
      defaults)
        # Only a list ARVA can read counts: a list stored under another key name looks like no list at all.
        say "  Docker Desktop's settings file has no File sharing list that ARVA can read. With Docker Desktop's default
  list (/Users, /Volumes, /private, /tmp, /var/folders), $disk reaches ARVA only through $vroot, and through $vroot
  ARVA (inside Docker) reads the free space of the Mac's startup disk instead of $disk's (seen on a real Mac). If you
  already shared $disk itself, Docker Desktop may keep the list under a name ARVA does not know: what ARVA sees
  once it runs decides (Settings → Storage). Otherwise share the disk itself:" \
            "  El archivo de ajustes de Docker Desktop no tiene una lista de File sharing que ARVA pueda leer. Con la lista
  por omisión de Docker Desktop (/Users, /Volumes, /private, /tmp, /var/folders), $disk llega a ARVA solo a través
  de $vroot, y a través de $vroot ARVA (dentro de Docker) lee el espacio libre del disco de arranque de la Mac en
  lugar del de $disk (comprobado en una Mac real). Si ya se compartió el propio $disk, puede que Docker Desktop
  guarde la lista con un nombre que ARVA no conoce: decide lo que ARVA ve una vez en marcha (Ajustes →
  Almacenamiento). Si no, compartir el propio disco:"
        sharing_steps "$disk" "$vroot"
        ;;
      parent)
        say "  Docker Desktop shares $disk with ARVA only through $parent. Through it, ARVA (inside Docker) reads the free
  space of another disk instead of $disk's (seen on a real Mac with $vroot: the startup disk's), so its free-space
  checks would use the wrong disk. Share the disk itself:" \
            "  Docker Desktop comparte $disk con ARVA solo a través de $parent. Así ARVA (dentro de Docker) lee el espacio
  libre de otro disco en lugar del de $disk (comprobado en una Mac real con $vroot: el del disco de arranque), así
  que sus controles de espacio usarían el disco equivocado. Compartir el propio disco:"
        sharing_steps "$disk" "$parent"
        ;;
      both)
        say "  Docker Desktop shares $disk and also $parent. Whether Docker then reports $disk's own free space has not
  been confirmed (seen on a real Mac: with $vroot removed it does). Remove $parent: Docker Desktop → Settings →
  File sharing (under Resources in some versions) → select $parent → remove it (−) → Apply (& restart). ARVA also
  checks this once it runs (Settings → Storage)." \
            "  Docker Desktop comparte $disk y también $parent. No está confirmado que Docker informe entonces el espacio
  libre propio de $disk (comprobado en una Mac real: sin $vroot sí lo hace). Quitar $parent: Docker Desktop →
  Settings → File sharing (en algunas versiones dentro de Resources) → seleccionar $parent → quitarla (−) →
  Apply (& restart). ARVA también lo comprueba una vez en marcha (Ajustes → Almacenamiento)."
        ;;
      not_shared)
        say "  Docker Desktop does not share $folder, so Docker refuses to mount it (\"mounts denied\"). Share its disk:" \
            "  Docker Desktop no comparte $folder, así que Docker se niega a montarla (\"mounts denied\"). Compartir su disco:"
        sharing_steps "$disk" ""
        ;;
    esac
  done <<EOF
$1
EOF
}

# One answer from standard input (a terminal, or a pipe in the tests). At the end of the input (Control-D, a Terminal
# window that went away, a pipe with no more lines) the answer is empty and wiz_eof is set: every question of the first
# run checks it right after asking (wiz_ended), and the first run then stops without saving anything, saying why,
# instead of taking the defaults of the questions that are left (the last one being "Save?", whose default is yes).
ask() {
  if [ "$lang" = es ]; then printf '%s ' "$2"; else printf '%s ' "$1"; fi
  if IFS= read -r reply; then
    reply=${reply%"$cr"}
  else
    reply='' wiz_eof=1
    printf '\n'
  fi
}

# The input of the first run ended (wiz_eof): says so once, on standard error, and returns 0 so that the question
# can stop the first run (`wiz_ended && return 1`). Returns 1 while answers are still being read.
wiz_ended() {
  [ "${wiz_eof:-0}" = 1 ] || return 1
  if [ "${wiz_eof_said:-0}" = 0 ]; then
    wiz_eof_said=1
    say "The answers ended before all the questions were answered (no more input could be read: Control-D was pressed,
the window was closed, or the input is not a terminal). Nothing was saved and ARVA did not start. Run ARVA again
(or scripts/start.sh --setup) to answer the questions." \
        "Las respuestas terminaron antes de que se respondieran todas las preguntas (no se pudo leer nada más: se pulsó
Control-D, se cerró la ventana o la entrada no es una terminal). No se guardó nada y ARVA no se inició. Volver a
abrir ARVA (o scripts/start.sh --setup) para responder las preguntas." >&2
  fi
  return 0
}

# Yes or no; $3 is the default (y or n).
ask_yes() {
  if [ "$3" = y ]; then ask "$1 [Y/n]" "$2 [S/n]"; else ask "$1 [y/N]" "$2 [s/N]"; fi
  case "$reply" in
    [YySs]*) return 0 ;;
    [Nn]*) return 1 ;;
  esac
  [ "$3" = y ]
}

# A folder as typed or dragged into Terminal (which escapes spaces with backslashes; other terminals add quotes).
wiz_path() {
  p=$(printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  case "$p" in
    \'*\') p=${p#\'} p=${p%\'} ;;
    \"*\") p=${p#\"} p=${p%\"} ;;
    *\\*) p=$(printf '%s' "$p" | sed 's/\\\(.\)/\1/g') ;;
  esac
  case "$p" in
    '~') p=${HOME:-~} ;;
    \~/*) p=${HOME:-~}/${p#?/} ;;
  esac
  while [ "${#p}" -gt 1 ] && [ "${p%/}" != "$p" ]; do p=${p%/}; done
  printf '%s' "$p"
}

wiz_rule() {
  printf '\n'
  say "── $1" "── $2"
}

# Docker Desktop installed and running (it is opened and waited for, at most ARVA_DOCKER_WAIT seconds, default 180).
wiz_docker() {
  wiz_rule "1/4 · Docker Desktop" "1/4 · Docker Desktop"
  if ! command -v docker >/dev/null 2>&1 && [ "$arva_os" = Darwin ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
    PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin
    export PATH
  fi
  if ! command -v docker >/dev/null 2>&1; then
    if [ "$arva_os" = Darwin ]; then
      say "Docker Desktop is not installed (no docker command was found). Install it from
  https://docs.docker.com/desktop/setup/install/mac-install/
choosing \"Mac with Apple chip\" or \"Mac with Intel chip\" (Apple menu → About This Mac shows which: \"Chip\" or
\"Processor\"), open it once, accept its terms, then run ARVA again." \
          "Docker Desktop no está instalado (no se encontró el comando docker). Instalarlo desde
  https://docs.docker.com/desktop/setup/install/mac-install/
eligiendo \"Mac with Apple chip\" o \"Mac with Intel chip\" (menú Apple → Acerca de esta Mac lo indica: \"Chip\" o
\"Procesador\"), abrirlo una vez, aceptar sus condiciones y volver a abrir ARVA."
    else
      say "Docker is not installed (no docker command was found): https://docs.docker.com/engine/install/" \
          "Docker no está instalado (no se encontró el comando docker): https://docs.docker.com/engine/install/"
    fi
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    if [ "$arva_os" != Darwin ]; then
      say "Docker is installed but not running. Start it (for example: sudo systemctl start docker), then run this script again." \
          "Docker está instalado pero no está en marcha. Iniciarlo (por ejemplo: sudo systemctl start docker) y volver a ejecutar este script."
      return 1
    fi
    say "Docker Desktop is installed but not running: opening it…" "Docker Desktop está instalado pero no está en marcha: abriéndolo…"
    open -a Docker >/dev/null 2>&1 || true
    wiz_wait_docker || return 1
  fi
  say "Docker is running." "Docker está en marcha."
  return 0
}

# Waits until Docker answers (at most ARVA_DOCKER_WAIT seconds, default 180), e.g. while Docker Desktop restarts
# after "Apply & restart".
wiz_wait_docker() {
  waited=0 limit=${ARVA_DOCKER_WAIT:-180}
  case "$limit" in '' | *[!0-9]*) limit=180 ;; esac
  until docker info >/dev/null 2>&1; do
    if [ "$waited" -ge "$limit" ]; then
      say "Docker Desktop did not become ready within $limit s. Open it from Applications, wait until its whale icon in the
menu bar stops moving, then run ARVA again." \
          "Docker Desktop no estuvo listo en $limit s. Abrirlo desde Aplicaciones, esperar a que el ícono de la ballena en la
barra de menús deje de moverse y volver a abrir ARVA."
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
}

# The mounted disks under /Volumes (ARVA_VOLUMES_ROOT in the tests): the startup disk and read-only volumes (such as
# an installer's disk image) are listed but not offered.
wiz_disks() {
  wiz_offered=''
  root=${ARVA_VOLUMES_ROOT:-}
  if [ -z "$root" ] && [ "$arva_os" = Darwin ]; then root=/Volumes; fi
  [ -n "$root" ] || return 0
  say "Disks connected to this computer:" "Discos conectados a esta computadora:"
  i=0
  for v in "$root"/*; do
    [ -d "$v" ] || continue
    name=${v##*/}
    arva_df "$v"
    arva_filesystem "$v" "$chk_mount"
    fs=${chk_fs_name:-${chk_fs:-?}}
    space=$(say "$(arva_kb "$chk_avail") free of $(arva_kb "$chk_total")" "$(arva_kb "$chk_avail") libres de $(arva_kb "$chk_total")")
    case "$chk_mount" in
      / | /System/Volumes/Data)
        say "   -  $name · $fs · $space (the Mac's startup disk)" "   -  $name · $fs · $space (el disco de arranque de la Mac)"
        continue
        ;;
    esac
    if [ ! -w "$v" ]; then
      say "   -  $name · $fs (read-only)" "   -  $name · $fs (solo lectura)"
      continue
    fi
    i=$((i + 1))
    wiz_offered=$(list_add "$wiz_offered" "$v")
    printf '  %2d) %s · %s · %s\n' "$i" "$name" "$fs" "$space"
    if [ "$chk_fat" = 1 ]; then
      say "      exFAT/FAT: no symbolic links or Unix permissions (the Bakta database needs a symbolic link); use APFS." \
          "      exFAT/FAT: sin enlaces simbólicos ni permisos Unix (la base de datos de Bakta necesita un enlace simbólico); usar APFS."
    fi
  done
  wiz_count=$i
}

# Where data and databases go: wiz_base (a folder that gets data/ and databases/), or nothing for Docker volumes.
wiz_storage() {
  wiz_rule "2/4 · Where ARVA keeps projects and databases" "2/4 · Dónde guarda ARVA los proyectos y las bases de datos"
  wiz_count=0
  wiz_disks
  wiz_base=''
  while :; do
    if [ "$wiz_count" -gt 0 ]; then
      ask "Disk for ARVA's data and databases: its number [1], 0 to keep them inside Docker Desktop, or a folder path:" \
          "Disco para los datos y las bases de datos de ARVA: su número [1], 0 para guardarlos dentro de Docker Desktop, o la ruta de una carpeta:"
      wiz_ended && return 1
      if [ -z "$reply" ]; then reply=1; fi
    else
      ask "No external disk is connected. A folder path for ARVA's data and databases, or Enter to keep them inside Docker Desktop:" \
          "No hay ningún disco externo conectado. La ruta de una carpeta para los datos y las bases de datos de ARVA, o Enter para guardarlos dentro de Docker Desktop:"
      wiz_ended && return 1
      if [ -z "$reply" ]; then reply=0; fi
    fi
    case "$reply" in
      0) return 0 ;;
      *[!0-9]*) ;;
      *)
        if [ "$reply" -le "$wiz_count" ]; then
          wiz_base=$(printf '%s\n' "$wiz_offered" | sed -n "${reply}p")/ARVA
          break
        fi
        say "There is no disk $reply." "No hay ningún disco $reply."
        continue
        ;;
    esac
    wiz_base=$(wiz_path "$reply")
    case "$wiz_base" in
      /?*) break ;;
    esac
    say "Type a number from the list or an absolute folder path (starting with /)." \
        "Escribir un número de la lista o la ruta absoluta de una carpeta (que empiece por /)."
  done
  data=$wiz_base/data databases=$wiz_base/databases
  say "Proposed folders:" "Carpetas propuestas:"
  say "  projects, results, reports, logs, backups:  $data" "  proyectos, resultados, informes, registros, copias:  $data"
  say "  databases that ARVA downloads:              $databases" "  bases de datos que descarga ARVA:                    $databases"
  if [ -f "$data/.arva-storage" ]; then
    say "  $data is already an ARVA data folder: it is used as it is." "  $data ya es una carpeta de datos de ARVA: se usa tal como está."
  fi
  if ask_yes "Use these folders (created if missing)?" "¿Usar estas carpetas (se crean si no existen)?" y; then use=1; else use=0; fi
  wiz_ended && return 1
  if [ "$use" = 0 ]; then
    ask "Data folder [$data]:" "Carpeta de datos [$data]:"
    wiz_ended && return 1
    if [ -n "$reply" ]; then data=$(wiz_path "$reply"); fi
    ask "Database folder [$databases]:" "Carpeta de bases de datos [$databases]:"
    wiz_ended && return 1
    if [ -n "$reply" ]; then databases=$(wiz_path "$reply"); fi
  fi
  for folder in "$data" "$databases"; do
    case "$folder" in /?*) ;; *)
      say "$folder is not an absolute path." "$folder no es una ruta absoluta."
      return 1
      ;;
    esac
  done
  want_data=$data want_databases=$databases
}

# After the answers are confirmed: the data and database folders, created when missing.
wiz_create() {
  for folder in "$want_data" "$want_databases"; do
    if [ -n "$folder" ] && [ ! -d "$folder" ] && ! mkdir -p -- "$folder"; then
      say "The folder $folder could not be created (is the disk connected and writable?)." \
          "No se pudo crear la carpeta $folder (¿el disco está conectado y se puede escribir en él?)."
      return 1
    fi
  done
}

# Existing database folders (for example a Bakta database and a FastANI genome collection), used read-only.
wiz_existing() {
  wiz_rule "3/4 · Databases you already have" "3/4 · Bases de datos que ya existen"
  example=${wiz_base%/ARVA}
  example=${example:-/Volumes/<Disk>}/BioInf
  say "ARVA can use database folders you already have where they are, read-only (it never writes, moves or deletes
anything in them): for example the folder with the Bakta full database and the FastANI reference genomes. Register
each database afterwards in Tools & Databases. A folder can be dragged from Finder into this window." \
      "ARVA puede usar las carpetas de bases de datos que ya existen donde están, en solo lectura (nunca escribe, mueve ni
borra nada en ellas): por ejemplo la carpeta con la base de datos completa de Bakta y los genomas de referencia de
FastANI. Después cada base de datos se registra en Herramientas y bases de datos. Se puede arrastrar una carpeta desde
el Finder a esta ventana."
  # Folders saved by an earlier run (--setup, ARVA → Set Up Again) stay: these questions only add.
  if [ -n "$cfg_extra" ]; then
    say "Already added, kept (scripts/start.sh --remove-databases PATH stops using one):" \
        "Ya añadidas, se conservan (scripts/start.sh --remove-databases RUTA deja de usar una):"
    while IFS= read -r folder; do
      [ -n "$folder" ] || continue
      printf '  - %s\n' "$folder"
    done <<EOF
$cfg_extra
EOF
  fi
  while :; do
    ask "Existing database folder (e.g. $example), or Enter to continue:" \
        "Carpeta de bases de datos existente (p. ej. $example), o Enter para continuar:"
    wiz_ended && return 1
    [ -n "$reply" ] || break
    folder=$(wiz_path "$reply")
    if arva_inspect "$folder" ro; then
      if ! list_has "$want_add" "$chk_real"; then want_add=$(list_add "$want_add" "$chk_real"); fi
      say "  added (read-only): $chk_real" "  añadida (solo lectura): $chk_real"
    else
      arva_unavailable databases "$folder" database "bases de datos"
    fi
  done
  if [ -n "$cfg_import" ]; then
    ask "Folder with sequencing runs to import from, read-only (Enter to keep $cfg_import):" \
        "Carpeta con corridas de secuenciación para importar, en solo lectura (Enter para conservar $cfg_import):"
  else
    ask "Folder with sequencing runs to import from, read-only (Enter to skip):" \
        "Carpeta con corridas de secuenciación para importar, en solo lectura (Enter para omitir):"
  fi
  wiz_ended && return 1
  if [ -n "$reply" ]; then
    folder=$(wiz_path "$reply")
    if arva_inspect "$folder" ro; then want_import=$folder; else arva_unavailable import "$folder" import importación; fi
  fi
  return 0
}

# Docker Desktop must share every chosen folder with its virtual machine, or it refuses to mount it ("mounts
# denied"), and a folder on an external disk must be shared as that disk, or ARVA reads the startup disk's free
# space (sharing_report). As for Rosetta, the steps are shown, Enter is waited for and the list is read again.
wiz_sharing() {
  [ "$arva_os" = Darwin ] || return 0
  # Without a chosen import folder, docker-compose.yml mounts the import/ folder next to it, which must be shared too.
  # Folders saved by an earlier run that the answers keep (the import folder, existing database folders) count too.
  import=${want_import:-$cfg_import}
  default_import=''
  if [ -z "$import" ] && [ -n "${ROOT:-}" ] && [ -d "$ROOT/import" ]; then default_import=$ROOT/import; fi
  folders=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n' "$want_data" "$want_databases" "$import" "$default_import" "$want_add" \
    "$cfg_extra" | sed '/^$/d' | awk '!seen[$0]++')
  [ -n "$folders" ] || return 0
  wiz_rule "File sharing" "Uso compartido de archivos (File sharing)"
  sharing_report "$folders"
  if [ -z "$sharing_bad" ]; then
    if [ -n "$(printf '%s\n' "$folders" | while IFS= read -r f; do volume_of "$f"; done)" ] && [ -z "$(docker_settings_file)" ]; then
      say "  Docker Desktop's settings file was not found, so ARVA cannot tell how it shares the disk; it checks the free
  space it sees once it runs (Settings → Storage)." \
          "  No se encontró el archivo de ajustes de Docker Desktop, así que ARVA no puede saber cómo comparte el disco;
  comprueba el espacio libre que ve una vez en marcha (Ajustes → Almacenamiento)."
    else
      say "  Docker Desktop shares the chosen folders." "  Docker Desktop comparte las carpetas elegidas."
    fi
    return 0
  fi
  ask "Press Enter when done." "Presionar Enter cuando esté listo."
  wiz_ended && return 1
  wiz_wait_docker || true
  before=$sharing_bad
  sharing_report "$folders" >/dev/null
  while IFS= read -r disk; do
    [ -n "$disk" ] || continue
    if list_has "$sharing_bad" "$disk"; then
      say "  Docker Desktop's settings file still shows the problem above for $disk (if you did change it, the file may
  keep the list under a name ARVA does not know). ARVA starts anyway and checks the free space it sees in
  Settings → Storage." \
          "  El archivo de ajustes de Docker Desktop todavía muestra el problema de arriba para $disk (si se cambió, puede
  que el archivo guarde la lista con un nombre que ARVA no conoce). ARVA se inicia igual y comprueba el espacio
  libre que ve en Ajustes → Almacenamiento."
    else
      say "  Docker Desktop now shares $disk." "  Docker Desktop ahora comparte $disk."
    fi
  done <<EOF
$before
EOF
}

# What the Rosetta setting as read ($1: off, default or unknown) means; the amd64 image is used in every case but off.
rosetta_note() {
  case "$1" in
    off) say "  Docker Desktop's Rosetta setting is off." "  El ajuste de Rosetta de Docker Desktop está desactivado." ;;
    default)
      say "  Docker Desktop's settings file does not store the Rosetta setting: it keeps only settings changed from Docker
  Desktop's defaults, and Docker's documentation does not say consistently whether Rosetta is on by default.
  Nothing failed; check the setting in Docker Desktop." \
          "  El archivo de ajustes de Docker Desktop no guarda el ajuste de Rosetta: solo guarda los ajustes cambiados
  respecto de los valores por omisión, y la documentación de Docker no indica de forma coherente si Rosetta viene
  activado. No falló nada; comprobar el ajuste en Docker Desktop."
      ;;
    *)
      say "  No Docker Desktop settings file was found to read the Rosetta setting from; check it in Docker Desktop." \
          "  No se encontró el archivo de ajustes de Docker Desktop del que leer el ajuste de Rosetta; comprobarlo en
  Docker Desktop."
      ;;
  esac
}

# Apple silicon: the amd64 image (every tool, through Rosetta) or the native arm64 image (without Bakta's CDS step,
# Prokka and the other tools that have no arm64 build).
wiz_platform() {
  wiz_rule "4/4 · Image architecture" "4/4 · Arquitectura de las imágenes"
  machine=$(uname -m 2>/dev/null || true)
  if [ "$arva_os" = Darwin ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" = 1 ]; then machine=arm64; fi
  if [ "$arva_os" != Darwin ] || [ "$machine" != arm64 ]; then
    say "This computer's own architecture ($machine) is used." "Se usa la arquitectura propia de esta computadora ($machine)."
    return 0
  fi
  rosetta=$(docker_rosetta)
  say "This Mac has an Apple chip. Two images:
  1) amd64: every ARVA tool (Bakta with all its steps, Prokka, MOB-suite, IntegronFinder, AgrVATE, ISEScan, GTDB-Tk),
     translated by Rosetta, so slower than native. Needs Docker Desktop's Rosetta setting.
  2) arm64: native, without the tools that have no arm64 build (Bakta's CDS and RNA steps, Prokka, MOB-suite,
     IntegronFinder, AgrVATE, ISEScan, GTDB-Tk)." \
      "Esta Mac tiene un chip de Apple. Hay dos imágenes:
  1) amd64: todas las herramientas de ARVA (Bakta con todos sus pasos, Prokka, MOB-suite, IntegronFinder, AgrVATE,
     ISEScan, GTDB-Tk), traducidas por Rosetta, por eso más lentas que una nativa. Necesita el ajuste de Rosetta de
     Docker Desktop.
  2) arm64: nativa, sin las herramientas que no tienen versión arm64 (los pasos de CDS y ARN de Bakta, Prokka,
     MOB-suite, IntegronFinder, AgrVATE, ISEScan, GTDB-Tk)."
  ask "Image [1]:" "Imagen [1]:"
  wiz_ended && return 1
  case "$reply" in
    2)
      want_platform=linux/arm64
      return 0
      ;;
  esac
  if ! arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
    say "  Rosetta 2 does not seem to be installed on this Mac. Install it with:
    softwareupdate --install-rosetta --agree-to-license" \
        "  Rosetta 2 no parece estar instalado en esta Mac. Instalarlo con:
    softwareupdate --install-rosetta --agree-to-license"
  fi
  if [ "$rosetta" != on ]; then
    rosetta_note "$rosetta"
    say "  Turn on Docker Desktop → Settings → General → \"Use Rosetta for x86_64/amd64 emulation on Apple Silicon\"
  (Apply & restart) if it is off; without it Docker emulates amd64 with QEMU, which is much slower." \
        "  Activar Docker Desktop → Settings → General → \"Use Rosetta for x86_64/amd64 emulation on Apple Silicon\"
  (Apply & restart) si está desactivado; sin él Docker emula amd64 con QEMU, que es mucho más lento."
    ask "Press Enter when done." "Presionar Enter cuando esté listo."
    wiz_ended && return 1
    rosetta=$(docker_rosetta)
    if [ "$rosetta" = on ]; then say "  Rosetta is on." "  Rosetta está activado."; fi
  fi
  if [ "$rosetta" = off ]; then want_platform=linux/amd64; else want_platform=auto; fi
}

# Everything that "Save these choices and start ARVA?" saves (what arva.conf holds afterwards), so that an answer
# skipped with Enter shows as "none" before anything is saved. On a run with saved choices (--setup, ARVA → Set Up
# Again), the answers to the disk and image questions replace the saved ones (scripts/start.sh forgets a saved data
# or database folder when the answer is 0, inside Docker Desktop: the folder itself is not touched), while the
# existing database folders and the import folder saved before are kept unless replaced, and are marked so.
wiz_summary() {
  wiz_rule "Summary" "Resumen"
  docker_volumes=$(say "inside Docker Desktop (Docker volumes)" "dentro de Docker Desktop (volúmenes de Docker)")
  none=$(say "none" "ninguna")
  kept=$(say "(saved before, kept)" "(guardada antes, se conserva)")
  say "  Projects, results, reports, logs, backups:  ${want_data:-$docker_volumes}" \
      "  Proyectos, resultados, informes, registros, copias:  ${want_data:-$docker_volumes}"
  say "  Databases that ARVA downloads:              ${want_databases:-$docker_volumes}" \
      "  Bases de datos que descarga ARVA:                    ${want_databases:-$docker_volumes}"
  for folder in "$cfg_data" "$cfg_databases"; do
    if [ -n "$folder" ] && [ "$folder" != "$want_data" ] && [ "$folder" != "$want_databases" ]; then
      say "    $folder, saved before, is no longer used (nothing in it is moved or deleted)." \
          "    $folder, guardada antes, deja de usarse (no se mueve ni se borra nada de ella)."
    fi
  done
  kept_add=''
  while IFS= read -r folder; do
    if [ -n "$folder" ] && ! list_has "$want_add" "$folder"; then kept_add=$(list_add "$kept_add" "$folder"); fi
  done <<EOF
$cfg_extra
EOF
  if [ -z "$want_add$kept_add" ]; then
    say "  Existing database folders (read-only):      $none" \
        "  Carpetas de bases de datos existentes (solo lectura): $none"
  else
    say "  Existing database folders (read-only):" "  Carpetas de bases de datos existentes (solo lectura):"
    while IFS= read -r folder; do
      [ -n "$folder" ] || continue
      printf '    - %s\n' "$folder"
    done <<EOF
$want_add
EOF
    while IFS= read -r folder; do
      [ -n "$folder" ] || continue
      printf '    - %s %s\n' "$folder" "$kept"
    done <<EOF
$kept_add
EOF
  fi
  if [ -n "$want_import" ]; then
    say "  Folder to import from (read-only):          $want_import" \
        "  Carpeta para importar (solo lectura):                $want_import"
  elif [ -n "$cfg_import" ]; then
    say "  Folder to import from (read-only):          $cfg_import $kept" \
        "  Carpeta para importar (solo lectura):                $cfg_import $kept"
  else
    say "  Folder to import from (read-only):          $none (ARVA's own import folder)" \
        "  Carpeta para importar (solo lectura):                $none (la carpeta de importación propia de ARVA)"
  fi
  case "${want_platform:-}" in
    linux/arm64) image=$(say "arm64 (native, without the tools that have no arm64 build)" "arm64 (nativa, sin las herramientas que no tienen versión arm64)") ;;
    linux/amd64) image=amd64 ;;
    auto) image=$(say "amd64 (every tool, through Rosetta)" "amd64 (todas las herramientas, a través de Rosetta)") ;;
    *) image=$(say "this computer's own (${machine:-?})" "la propia de esta computadora (${machine:-?})") ;;
  esac
  say "  Image architecture:                         $image" \
      "  Arquitectura de las imágenes:                        $image"
}

# The whole first run. Returns 1 when ARVA must not start (the reason has been printed). Stopped from outside
# (Control-C, the Terminal window closed), it says so before ending, so the window never just goes back to the prompt.
arva_first_run() {
  wiz_eof=0 wiz_eof_said=0
  trap 'printf "\n"; say "The questions were interrupted: nothing was saved and ARVA did not start." "Las preguntas se interrumpieron: no se guardó nada y ARVA no se inició." >&2; exit 130' INT HUP TERM
  say "Welcome to ARVA. A few questions before the first start (the answers are saved in $ARVA_CONFIG;
scripts/start.sh --setup asks them again)." \
      "Bienvenido a ARVA. Unas preguntas antes del primer inicio (las respuestas se guardan en $ARVA_CONFIG;
scripts/start.sh --setup las vuelve a hacer)."
  if ! wiz_docker || ! wiz_storage || ! wiz_existing || ! wiz_platform || ! wiz_sharing; then
    trap - INT HUP TERM
    return 1
  fi
  wiz_summary
  printf '\n'
  if ask_yes "Save these choices and start ARVA?" "¿Guardar estas elecciones e iniciar ARVA?" y; then save=1; else save=0; fi
  trap - INT HUP TERM
  # The end of the input is no "yes" (the default of that question): nothing is saved.
  wiz_ended && return 1
  if [ "$save" = 0 ]; then
    say "Nothing was saved. Run ARVA again to answer the questions again." \
        "No se guardó nada. Volver a abrir ARVA para responder de nuevo las preguntas."
    exit 0
  fi
  wiz_create || return 1
  open_browser=1
  return 0
}
