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

# Docker Desktop's "Use Rosetta for x86_64/amd64 emulation on Apple Silicon" (Settings → General), from its settings
# file (Docker's settings reference names the key useVirtualizationFrameworkRosetta; settings-store.json since Docker
# Desktop 4.35, settings.json before). The key's spelling in the file is not documented, so it is matched without
# regard to case. Prints on, off or unknown.
docker_rosetta() {
  dir=${HOME:+$HOME/Library/Group Containers/group.com.docker}
  for file in "$dir/settings-store.json" "$dir/settings.json"; do
    if [ -z "$dir" ] || [ ! -f "$file" ]; then continue; fi
    value=$(grep -io '"usevirtualizationframeworkrosetta"[[:space:]]*:[[:space:]]*[a-z]*' "$file" 2>/dev/null |
      head -n 1 | sed 's/.*:[[:space:]]*//' | tr '[:upper:]' '[:lower:]')
    case "$value" in
      true) printf on; return 0 ;;
      false) printf off; return 0 ;;
    esac
  done
  printf unknown
}

# The folders Docker Desktop shares with its virtual machine (Settings → Resources → File sharing), one per line, from
# the same settings file (key filesharingDirectories, matched without regard to case; not documented either). Prints
# nothing when the file or the key cannot be read.
docker_file_sharing() {
  dir=${HOME:+$HOME/Library/Group Containers/group.com.docker}
  for file in "$dir/settings-store.json" "$dir/settings.json"; do
    if [ -z "$dir" ] || [ ! -f "$file" ]; then continue; fi
    list=$(tr -d '\n\r' < "$file" 2>/dev/null | grep -io '"filesharingdirectories"[[:space:]]*:[[:space:]]*\[[^]]*\]' |
      head -n 1 | sed 's/^[^[]*\[//; s/\]$//' | tr ',' '\n' | sed -n 's/^[[:space:]]*"\(\/[^"]*\)"[[:space:]]*$/\1/p')
    if [ -n "$list" ]; then
      printf '%s\n' "$list"
      return 0
    fi
  done
}

# One answer from standard input (a terminal, or a pipe in the tests); at the end of the input, the default.
ask() {
  if [ "$lang" = es ]; then printf '%s ' "$2"; else printf '%s ' "$1"; fi
  if IFS= read -r reply; then
    reply=${reply%"$cr"}
  else
    reply='' wiz_eof=1
    printf '\n'
  fi
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
  fi
  say "Docker is running." "Docker está en marcha."
  return 0
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
      if [ -z "$reply" ]; then reply=1; fi
    else
      ask "No external disk is connected. A folder path for ARVA's data and databases, or Enter to keep them inside Docker Desktop:" \
          "No hay ningún disco externo conectado. La ruta de una carpeta para los datos y las bases de datos de ARVA, o Enter para guardarlos dentro de Docker Desktop:"
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
        if [ "${wiz_eof:-0}" = 1 ]; then return 1; fi
        continue
        ;;
    esac
    wiz_base=$(wiz_path "$reply")
    case "$wiz_base" in
      /?*) break ;;
    esac
    say "Type a number from the list or an absolute folder path (starting with /)." \
        "Escribir un número de la lista o la ruta absoluta de una carpeta (que empiece por /)."
    if [ "${wiz_eof:-0}" = 1 ]; then return 1; fi
  done
  data=$wiz_base/data databases=$wiz_base/databases
  say "Proposed folders:" "Carpetas propuestas:"
  say "  projects, results, reports, logs, backups:  $data" "  proyectos, resultados, informes, registros, copias:  $data"
  say "  databases that ARVA downloads:              $databases" "  bases de datos que descarga ARVA:                    $databases"
  if [ -f "$data/.arva-storage" ]; then
    say "  $data is already an ARVA data folder: it is used as it is." "  $data ya es una carpeta de datos de ARVA: se usa tal como está."
  fi
  if ! ask_yes "Use these folders (created if missing)?" "¿Usar estas carpetas (se crean si no existen)?" y; then
    ask "Data folder [$data]:" "Carpeta de datos [$data]:"
    if [ -n "$reply" ]; then data=$(wiz_path "$reply"); fi
    ask "Database folder [$databases]:" "Carpeta de bases de datos [$databases]:"
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
  while :; do
    ask "Existing database folder (e.g. $example), or Enter to continue:" \
        "Carpeta de bases de datos existente (p. ej. $example), o Enter para continuar:"
    [ -n "$reply" ] || break
    folder=$(wiz_path "$reply")
    if arva_inspect "$folder" ro; then
      if ! list_has "$want_add" "$folder"; then want_add=$(list_add "$want_add" "$folder"); fi
      say "  added (read-only): $chk_real" "  añadida (solo lectura): $chk_real"
    else
      arva_unavailable databases "$folder" database "bases de datos"
    fi
    if [ "${wiz_eof:-0}" = 1 ]; then break; fi
  done
  ask "Folder with sequencing runs to import from, read-only (Enter to skip):" \
      "Carpeta con corridas de secuenciación para importar, en solo lectura (Enter para omitir):"
  if [ -n "$reply" ]; then
    folder=$(wiz_path "$reply")
    if arva_inspect "$folder" ro; then want_import=$folder; else arva_unavailable import "$folder" import importación; fi
  fi
}

# Docker Desktop must share every chosen folder with its virtual machine, or it refuses to mount it ("Mounts denied").
wiz_sharing() {
  [ "$arva_os" = Darwin ] || return 0
  shared=$(docker_file_sharing)
  [ -n "$shared" ] || return 0
  printf '%s\n%s\n%s\n%s\n' "$want_data" "$want_databases" "$want_import" "$want_add" | while IFS= read -r folder; do
    [ -n "$folder" ] || continue
    covered=0
    while IFS= read -r s; do
      case "$folder/" in "${s%/}"/*) covered=1 ;; esac
    done <<EOF
$shared
EOF
    if [ "$covered" = 0 ]; then
      say "  Docker Desktop does not share $folder: add it (or its disk under /Volumes) in Docker Desktop → Settings →
  Resources → File sharing, then Apply & restart." \
          "  Docker Desktop no comparte $folder: agregarla (o su disco en /Volumes) en Docker Desktop → Settings →
  Resources → File sharing y luego Apply & restart."
    fi
  done
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
    if [ "$rosetta" = off ]; then
      say "  Docker Desktop's Rosetta setting is off." "  El ajuste de Rosetta de Docker Desktop está desactivado."
    else
      say "  Docker Desktop's Rosetta setting could not be read." "  No se pudo leer el ajuste de Rosetta de Docker Desktop."
    fi
    say "  Turn on Docker Desktop → Settings → General → \"Use Rosetta for x86_64/amd64 emulation on Apple Silicon\"
  (Apply & restart); without it Docker emulates amd64 with QEMU, which is much slower." \
        "  Activar Docker Desktop → Settings → General → \"Use Rosetta for x86_64/amd64 emulation on Apple Silicon\"
  (Apply & restart); sin él Docker emula amd64 con QEMU, que es mucho más lento."
    ask "Press Enter when done." "Presionar Enter cuando esté listo."
    rosetta=$(docker_rosetta)
  fi
  if [ "$rosetta" = off ]; then want_platform=linux/amd64; else want_platform=auto; fi
}

# The whole first run. Returns 1 when ARVA must not start (the reason has been printed).
arva_first_run() {
  wiz_eof=0
  say "Welcome to ARVA. A few questions before the first start (the answers are saved in $ARVA_CONFIG;
scripts/start.sh --setup asks them again)." \
      "Bienvenido a ARVA. Unas preguntas antes del primer inicio (las respuestas se guardan en $ARVA_CONFIG;
scripts/start.sh --setup las vuelve a hacer)."
  wiz_docker || return 1
  wiz_storage || return 1
  wiz_existing
  wiz_platform
  wiz_sharing
  printf '\n'
  if ! ask_yes "Save these choices and start ARVA?" "¿Guardar estas elecciones e iniciar ARVA?" y; then
    say "Nothing was saved. Run ARVA again to answer the questions again." \
        "No se guardó nada. Volver a abrir ARVA para responder de nuevo las preguntas."
    exit 0
  fi
  wiz_create || return 1
  open_browser=1
  return 0
}
