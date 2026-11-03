#!/bin/sh
# ARVA's metadata backups: pg_dump archives (custom format) of ARVA's PostgreSQL database, kept in the data folder
# (<data folder>/backups), so that the disk holding the projects also holds their metadata and can be moved to
# another computer. It runs in the `backup` service of docker-compose.yml, which uses the postgres image itself, so
# pg_dump and pg_restore match the server's major version; it connects with libpq's PGHOST, PGPORT, PGUSER,
# PGPASSWORD and PGDATABASE.
#
#   metadata-backup.sh loop            a backup every ARVA_BACKUP_INTERVAL_HOURS (default 24), and each backup
#                                      asked for in ARVA (Settings → Storage, which writes backups/.request)
#   metadata-backup.sh backup KIND     one backup now; KIND is auto, manual or pre-restore
#   metadata-backup.sh restore NAME    replace the database with the backup NAME (or latest), after backing it up
#   metadata-backup.sh list            the backups, newest first
#   metadata-backup.sh latest          the newest backup of this data folder's metadata (what restore latest takes)
#
# Each kind keeps its newest ARVA_BACKUP_KEEP backups (default 14). An auto or manual backup is written only when
# the data folder's storage marker (.arva-storage) holds the ID the database has recorded (app setting "storage"):
# without the marker the external disk is not connected; with another ID it is another installation's folder; and
# a database with no ID recorded yet (a new installation, or one waiting for a restore) holds nothing of this
# folder's, and backing it up would put an empty backup at the top of the list. "latest" is the newest backup whose
# recorded ID is the marker's. Every archive is checked with pg_restore --list before it replaces anything; a
# restore goes into a new database first and replaces the current one only when it succeeded.
set -eu

DIR=${ARVA_BACKUP_DIR:-/data/backups}
MARKER=${ARVA_STORAGE_MARKER:-$(dirname -- "$DIR")/.arva-storage}
NAME_RE='^arva-metadata-(auto|manual|pre-restore)-[0-9]{8}T[0-9]{6}Z\.dump$'

whole() {
  case "$1" in '' | *[!0-9]*) printf '%s' "$2" ;; *) if [ "$1" -ge 1 ]; then printf '%s' "$1"; else printf '%s' "$2"; fi ;; esac
}
INTERVAL=$(whole "${ARVA_BACKUP_INTERVAL_HOURS:-}" 24)
KEEP=$(whole "${ARVA_BACKUP_KEEP:-}" 14)
POLL=$(whole "${ARVA_BACKUP_POLL_SECONDS:-}" 30)

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

# The outcome of the last backup, read by ARVA (KEY=VALUE lines; the detail is printable ASCII, the code one the
# interface translates).
result() {
  detail=$(printf '%s' "$3" | LC_ALL=C tr -cd '[:print:]' | cut -c 1-300)
  { printf 'result=%s\nkind=%s\nat=%s\ncode=%s\ndetail=%s\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${4:-}" "$detail" \
    > "$DIR/.last-result.tmp" && mv -f "$DIR/.last-result.tmp" "$DIR/.last-result"; } 2>/dev/null || true
}

marker_id() {
  sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([0-9a-fA-F-]*\)".*/\1/p' "$MARKER" 2>/dev/null | head -n 1
}

# The data folder ID the database has recorded (empty: none yet, or no ARVA tables).
recorded_id() {
  psql --quiet --no-psqlrc --tuples-only --no-align --dbname="${PGDATABASE:-}" \
    --command="SELECT value::json->>'data_id' FROM app_settings WHERE key = 'storage'" 2>/dev/null | head -n 1 || true
}

# The data folder ID recorded in a backup archive.
archive_id() {
  pg_restore --data-only --table=app_settings --file=- "$1" 2>/dev/null |
    sed -n 's/.*"data_id"[[:space:]]*:[[:space:]]*"\([0-9a-fA-F-]*\)".*/\1/p' | head -n 1
}

names() {
  for f in "$DIR"/arva-metadata-*.dump; do
    if [ -f "$f" ] && printf '%s\n' "${f##*/}" | grep -Eq "$NAME_RE"; then printf '%s\n' "${f##*/}"; fi
  done
}

list() {
  names | sed 's/^\(.*-\)\([0-9]\{8\}T[0-9]\{6\}Z\)\.dump$/\2 &/' | sort -r | cut -d ' ' -f 2
}

prune() {
  names | grep "^arva-metadata-$1-" | sort -r | tail -n +"$((KEEP + 1))" | while IFS= read -r old; do
    rm -f "$DIR/$old"
    log "Removed $old (more than $KEEP $1 backups)"
  done
}

backup() {
  kind=$1
  case "$kind" in auto | manual | pre-restore) ;; *) die "unknown backup kind: $kind" ;; esac
  if [ ! -f "$MARKER" ]; then
    log "No backup: the data folder's storage marker ($MARKER) is missing, so its disk is not connected"
    return 1
  fi
  if [ "$kind" != pre-restore ]; then
    disk=$(marker_id)
    recorded=$(recorded_id)
    if [ -z "$recorded" ]; then
      result failed "$kind" "No backup: this metadata is not tied to the data folder yet (new installation, or a restore is needed)" not_tied
      log "No backup: the database has recorded no data folder yet (new installation, or waiting for a restore)"
      return 1
    fi
    if [ "$recorded" != "$disk" ]; then
      result failed "$kind" "No backup: the data folder belongs to another ARVA installation (its marker does not match)" other_folder
      log "No backup: the data folder's marker ($disk) is not the one this database recorded ($recorded)"
      return 1
    fi
  fi
  mkdir -p "$DIR"
  name="arva-metadata-$kind-$(date -u +%Y%m%dT%H%M%SZ).dump"
  while [ -e "$DIR/$name" ]; do
    sleep 1
    name="arva-metadata-$kind-$(date -u +%Y%m%dT%H%M%SZ).dump"
  done
  tmp="$DIR/.partial-$name"
  if pg_dump --format=custom --file="$tmp" && pg_restore --list "$tmp" >/dev/null; then
    mv -f "$tmp" "$DIR/$name"
    result ok "$kind" "$name" ok
    log "Backup $name ($(wc -c < "$DIR/$name" | tr -d ' ') bytes)"
    prune "$kind"
    printf '%s\n' "$name"
  else
    rm -f "$tmp"
    result failed "$kind" "pg_dump of database ${PGDATABASE:-?} failed; see the backup service's log" dump_failed
    log "Backup failed"
    return 1
  fi
}

latest() {
  disk=$(marker_id)
  [ -n "$disk" ] || die "the data folder's storage marker ($MARKER) is missing or unreadable"
  list | while IFS= read -r candidate; do
    if [ "$(archive_id "$DIR/$candidate")" = "$disk" ]; then
      printf '%s\n' "$candidate"
      break
    fi
  done
}

restore() {
  name=$1
  if [ "$name" = latest ]; then
    name=$(latest)
    [ -n "$name" ] || die "no backup in $DIR holds this data folder's metadata (marker $(marker_id)); give a NAME from list"
  fi
  if ! printf '%s\n' "$name" | grep -Eq "$NAME_RE"; then die "give the name of a backup in $DIR (metadata-backup.sh list) or latest"; fi
  file="$DIR/$name"
  [ -f "$file" ] || die "no backup $name in $DIR"
  case "${PGDATABASE:-}" in '' | *[!A-Za-z0-9_]*) die "PGDATABASE must be a plain database name" ;; esac
  pg_restore --list "$file" >/dev/null || die "$name is not a readable pg_dump archive; nothing was changed"
  log "Backing up the current metadata before restoring $name"
  backup pre-restore >/dev/null || die "the current metadata could not be backed up; nothing was changed"
  staging="${PGDATABASE}_restoring"
  dropdb --if-exists "$staging"
  createdb "$staging"
  if ! pg_restore --exit-on-error --single-transaction --no-owner --no-privileges --dbname="$staging" "$file"; then
    dropdb --if-exists "$staging"
    die "restoring $name failed; the current metadata was not changed"
  fi
  # The current database is renamed aside, not dropped, until the restored one has taken its name.
  replaced="${PGDATABASE}_replaced"
  dropdb --if-exists --force "$replaced"
  sql() { psql --quiet --no-psqlrc --dbname=postgres --set ON_ERROR_STOP=1 --command="$1" >/dev/null; }
  sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$PGDATABASE' AND pid <> pg_backend_pid()"
  if ! sql "ALTER DATABASE \"$PGDATABASE\" RENAME TO \"$replaced\""; then
    dropdb --if-exists "$staging"
    die "the current database could not be set aside; the current metadata was not changed"
  fi
  if ! sql "ALTER DATABASE \"$staging\" RENAME TO \"$PGDATABASE\""; then
    if sql "ALTER DATABASE \"$replaced\" RENAME TO \"$PGDATABASE\""; then
      die "the restored database could not take the name $PGDATABASE; the current metadata was put back unchanged"
    fi
    die "the restored database could not take the name $PGDATABASE, and the current one could not be renamed back: it is in $replaced, the restored one in $staging"
  fi
  dropdb --if-exists --force "$replaced"
  log "Restored $name into $PGDATABASE"
}

loop() {
  log "Metadata backups every $INTERVAL h into $DIR, keeping $KEEP of each kind"
  trap 'exit 0' TERM INT
  retry_at=0
  while :; do
    if [ -f "$DIR/.request" ] && mv -f "$DIR/.request" "$DIR/.request.taken" 2>/dev/null; then
      backup manual >/dev/null || true
      rm -f "$DIR/.request.taken"
    fi
    now=$(date +%s)
    newest=$(names | grep '^arva-metadata-auto-' | sort | tail -n 1)
    last=0
    if [ -n "$newest" ]; then last=$(date -r "$DIR/$newest" +%s 2>/dev/null || echo 0); fi
    if [ "$now" -ge "$retry_at" ] && [ $((now - last)) -ge $((INTERVAL * 3600)) ]; then
      if ! backup auto >/dev/null; then retry_at=$((now + 3600)); fi
    fi
    sleep "$POLL" &
    wait $! || true
  done
}

case "${1:-}" in
  loop) loop ;;
  backup) backup "${2:-manual}" ;;
  restore) restore "${2:-}" ;;
  list) list ;;
  latest) latest ;;
  *) die "usage: metadata-backup.sh loop | backup KIND | restore NAME|latest | list | latest" ;;
esac
