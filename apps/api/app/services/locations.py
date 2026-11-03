"""Where ARVA keeps its files, whether each folder is there, and the marker that ties the data folder to the metadata.

Locations: the data folder (ARVA_STORAGE_ROOT: raw, processed, results, reports, logs and the metadata backups), the
database folder (ARVA_DB_DIR, where the Database Manager installs databases), the import folders (ARVA_IMPORT_ROOTS,
read-only) and the external database folders (ARVA_EXTERNAL_DB_ROOTS: existing databases used in place, read-only,
never modified or deleted). scripts/start.sh passes each folder's path on the host and its filesystem as ARVA_HOST_*
variables: untrusted strings, validated here and only shown.

Free space. scripts/start.sh also measures the size and free space of each folder's disk on the host
(ARVA_HOST_<NAME>_TOTAL_BYTES, ARVA_HOST_<NAME>_AVAIL_BYTES) and when (ARVA_HOST_SPACE_MEASURED_AT), and writes them
as KEY=VALUE lines to a file mounted read-only at /run/arva-host/space (HOST_SPACE_FILE), read at every use: they
change at every start, and as environment variables they would make Docker Compose recreate the containers (and stop
running jobs) at every start. Variables of the same names, if set, take precedence (tests, a hand-made setup). Seen on a real
Mac with Docker Desktop: a folder on an external disk (/Volumes/JM/ARVA/data) that Docker Desktop shares only through
/Volumes (its default File sharing list) is mounted from /run/host_mark/Volumes, and inside the container its free
space and size are the Mac's startup disk's; with /Volumes/JM itself shared (and /Volumes removed) the mount comes
from /run/host_mark/Volumes/JM and shows the external disk's. A location's space is "misreported" when the mount
comes from a share above its disk (/run/host_mark/Volumes or /run/host_mark for a /Volumes/<Disk>/... folder) or when
the mount comes from Docker Desktop's file sharing (/run/host_mark/...) and the size the container reads differs from
the launcher's by more than SIZE_TOLERANCE. Then:
* the location carries the warning space_misreported, the launcher's figures and their time;
* every free-space check (uploads, jobs, database downloads and extractions) and the low-space warning use the
  launcher's free space minus what ARVA has written since to its writable folders on that disk (the growth of those
  folders' trees since the first reading after the measurement, kept in the metadata as app setting "space_baseline"
  so that it survives container restarts, e.g. after the Mac restarts). What other programs write to the disk is not
  counted, nor what ARVA frees (conservative); when a tree cannot be measured (more than TREE_MAX_ENTRIES entries)
  the launcher's figure is used as it is and said so. The warning stays until the disk is shared as itself (Docker
  Desktop → Settings → File sharing → /Volumes/<Disk>, /Volumes removed) and ARVA is started again, which also
  measures again; without a launcher figure the container's figure is kept, flagged as wrong.
Natively, on Linux (no /run/host_mark mount), and whenever the mount and the sizes agree, nothing changes.

The data folder holds a marker file, .arva-storage, with an ID written at its first use and recorded in the metadata
(app setting "storage"). When the folder is not there, or holds another ID, its external disk is not connected or
another disk is in its place: writes are then refused (503) and jobs fail, instead of writing elsewhere. A marker
whose ID the metadata does not know is adopted, unless the folder holds metadata backups: the metadata is then new
(another computer, or a reset Docker volume) and scripts/restore.sh brings back the disk's own.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import __version__
from app.core.config import get_settings
from app.core.messages import render
from app.db.session import SessionLocal
from app.services.capacity import fmt_bytes

MARKER = ".arva-storage"
SETTING_KEY = "storage"
EXTERNAL_PREFIX = "/databases-external/"
REQUEST = ".request"
LAST_RESULT = ".last-result"
# Codes scripts/metadata-backup.sh writes with its result; the interface has them as storage.backups.code.<code>.
BACKUP_CODES = ("ok", "dump_failed", "not_tied", "other_folder")
# ARVA's own threshold for a "low space" warning (the launcher uses the same).
LOW_SPACE_BYTES = 20 * 1024**3
FAT = {"exfat", "msdos", "vfat", "fat", "fat12", "fat16", "fat32"}
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FS = re.compile(r"[a-z0-9_+-]{1,32}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BACKUP = re.compile(r"arva-metadata-(auto|manual|pre-restore)-(\d{8}T\d{6}Z)\.dump")
_SLOT = re.compile(r"ARVA_HOST_EXTERNAL_DB_(\d{1,10})")
_BYTES = re.compile(r"\d{1,20}")
# Docker Desktop's mount sources inside its Linux VM: /run/host_mark<shared host folder> (seen in /proc/mounts on a
# real Mac: "/run/host_mark/Volumes /data fakeowner rw,...").
HOST_MARK = "/run/host_mark"
PROC_MOUNTS = "/proc/self/mounts"
# The container's size of a folder's disk may differ from the launcher's by rounding and the filesystem's own
# reservation; a different disk differs by far more.
SIZE_TOLERANCE = 0.02
SIZE_TOLERANCE_MIN_BYTES = 1024**3
# The launcher's figures (scripts/lib/arva-locations.sh, arva_write_space), and the names they may have there.
HOST_SPACE_FILE = "/run/arva-host/space"
_HOST_SPACE_KEY = re.compile(r"ARVA_HOST_(?:[A-Z]+|EXTERNAL_DB_\d{1,10})_(?:TOTAL|AVAIL)_BYTES|ARVA_HOST_SPACE_MEASURED_AT")
# What ARVA wrote since the measurement: tree sizes, re-read at most every TREE_CACHE_SECONDS, at most
# TREE_MAX_ENTRIES entries per tree (beyond that the growth is unknown).
BASELINE_KEY = "space_baseline"
TREE_CACHE_SECONDS = 60.0
TREE_MAX_ENTRIES = 500_000

# The English texts of the coded refusals; the interface has them as api.error.<code> (apps/web/src/i18n).
MESSAGES = {
    "storage_unavailable": "The ARVA data folder {path} cannot be read: the external disk that holds it is probably "
                           "not connected. Connect it and start ARVA again (scripts/start.sh). Nothing was written.",
    "storage_missing": "The ARVA data folder {path} has no storage marker (.arva-storage) although this ARVA has used "
                       "it before: its external disk is probably not connected, or another folder is in its place. "
                       "Connect the disk and start ARVA again (scripts/start.sh). Nothing was written.",
    "storage_mismatch": "The ARVA data folder {path} belongs to another ARVA installation (storage ID {disk_id}; this "
                        "ARVA expects {recorded_id}): another disk is probably connected in its place. Connect the "
                        "right disk, or restore this disk's metadata with scripts/restore.sh. Nothing was written.",
    "storage_restore_needed": "The ARVA data folder {path} holds {count, plural, one {# metadata backup} other {# "
                              "metadata backups}} of the ARVA that used it, but this ARVA's metadata is new. Restore "
                              "the latest with scripts/restore.sh latest, or use the folder with the current metadata "
                              "in Settings → Storage. Nothing was written.",
    "storage_invalid": "The storage marker {path}/.arva-storage cannot be read or is damaged; check the disk. Nothing "
                       "was written.",
}
# The same in Spanish, for the summary scripts/start.sh prints (the interface has its own translations).
MESSAGES_ES = {
    "storage_unavailable": "No se puede leer la carpeta de datos de ARVA {path}: probablemente el disco externo que la "
                           "contiene no está conectado. Conéctalo e inicia ARVA de nuevo (scripts/start.sh). No se "
                           "escribió nada.",
    "storage_missing": "La carpeta de datos de ARVA {path} no tiene la marca de almacenamiento (.arva-storage), aunque "
                       "este ARVA ya la usó: probablemente su disco externo no está conectado, u otra carpeta ocupa su "
                       "lugar. Conecta el disco e inicia ARVA de nuevo (scripts/start.sh). No se escribió nada.",
    "storage_mismatch": "La carpeta de datos de ARVA {path} pertenece a otra instalación de ARVA (identificador "
                        "{disk_id}; este ARVA espera {recorded_id}): probablemente hay otro disco conectado en su "
                        "lugar. Conecta el disco correcto o restaura los metadatos de este disco con "
                        "scripts/restore.sh. No se escribió nada.",
    "storage_restore_needed": "La carpeta de datos de ARVA {path} contiene {count, plural, one {# copia} other {# "
                              "copias}} de los metadatos del ARVA que la usó, pero los metadatos de este ARVA son "
                              "nuevos. Restaura la última con scripts/restore.sh latest, o usa la carpeta con los "
                              "metadatos actuales en Ajustes → Almacenamiento. No se escribió nada.",
    "storage_invalid": "La marca de almacenamiento {path}/.arva-storage no se puede leer o está dañada; revisa el "
                       "disco. No se escribió nada.",
}


class StorageUnavailable(Exception):
    """The data folder cannot be written now (503); `code` names the reason for the interface."""

    def __init__(self, state: MarkerState):
        self.state = state
        self.code = f"storage_{state.status}"
        self.params: dict[str, Any] = {"path": state.host_path or state.path}
        if state.status == "mismatch":
            self.params |= {"disk_id": state.disk_id, "recorded_id": state.recorded_id}
        if state.status == "restore_needed":
            self.params["count"] = state.backups
        super().__init__(render(MESSAGES[self.code], self.params))


@dataclass(frozen=True)
class MarkerState:
    # ok; new (no marker yet, written at the first write); unavailable; missing; mismatch; restore_needed; invalid
    status: str
    path: str
    host_path: str | None = None
    disk_id: str | None = None
    recorded_id: str | None = None
    backups: int = 0

    @property
    def writable(self) -> bool:
        return self.status in ("ok", "new")


# --- Host paths and filesystems (from the launcher) -------------------------------------------------------------

def host_path(value: str | None) -> str | None:
    """An absolute host path from the launcher, or None when it is missing or malformed (only shown)."""
    text = (value or "").strip()
    if not text.startswith("/") or len(text) > 1024 or _CONTROL.search(text):
        return None
    return text


def filesystem(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    return text if _FS.fullmatch(text) else None


def in_container() -> bool:
    from app.services.host import detection

    return detection().container.in_container


def byte_count(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if _BYTES.fullmatch(text) else None


def host_space(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The launcher's space figures: the lines of HOST_SPACE_FILE with a known name, then the variables of the same
    names, which take precedence. Untrusted strings, validated where used."""
    environ = os.environ if environ is None else environ
    out: dict[str, str] = {}
    try:
        with open(HOST_SPACE_FILE, encoding="utf-8", errors="replace") as fh:
            lines = fh.read(65_536).splitlines()
    except OSError:
        lines = []
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and _HOST_SPACE_KEY.fullmatch(key):
            out[key] = value.strip()
    out.update({k: v for k, v in environ.items() if _HOST_SPACE_KEY.fullmatch(k)})
    return out


def measured_at(environ: Mapping[str, str] | None = None) -> datetime | None:
    """When scripts/start.sh measured the host figures (ARVA_HOST_SPACE_MEASURED_AT), or None."""
    try:
        return datetime.strptime((host_space(environ).get("ARVA_HOST_SPACE_MEASURED_AT") or "").strip(),
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class Location:
    role: str  # data | databases | import | external_databases
    container_path: str
    read_only: bool
    host_path: str | None
    filesystem: str | None
    stores: tuple[str, ...]
    slot: str | None = None
    # The folder's disk as scripts/start.sh measured it on the host (None without the launcher).
    host_total_bytes: int | None = None
    host_free_bytes: int | None = None


def _space(environ: Mapping[str, str], name: str) -> dict[str, int | None]:
    total = byte_count(environ.get(f"ARVA_HOST_{name}_TOTAL_BYTES"))
    free = byte_count(environ.get(f"ARVA_HOST_{name}_AVAIL_BYTES"))
    if total is None or free is None or free > total or total == 0:
        return {"host_total_bytes": None, "host_free_bytes": None}
    return {"host_total_bytes": total, "host_free_bytes": free}


def _external_hosts(environ: Mapping[str, str]) -> dict[str, tuple[str | None, str | None]]:
    out = {}
    for name, value in environ.items():
        if m := _SLOT.fullmatch(name):
            out[m.group(1)] = (host_path(value), filesystem(environ.get(f"{name}_FS")))
    return out


def locations(environ: Mapping[str, str] | None = None) -> list[Location]:
    """Every folder ARVA uses. Running natively (not in a container), a folder's host path is its own path."""
    environ = os.environ if environ is None else environ
    space = host_space(environ)
    s = get_settings()
    native = not in_container()

    def host(name: str, path: Path) -> tuple[str | None, str | None]:
        given = host_path(environ.get(f"ARVA_HOST_{name}_DIR"))
        return (given or (str(path) if native else None)), filesystem(environ.get(f"ARVA_HOST_{name}_FS"))

    data, databases = s.storage_root.resolve(), s.databases_dir.resolve()
    out = [
        Location("data", str(data), False, *host("DATA", data),
                 ("raw", "processed", "results", "reports", "logs", "backups"), **_space(space, "DATA")),
        Location("databases", str(databases), False, *host("DATABASES", databases), ("downloads",),
                 **_space(space, "DATABASES")),
    ]
    for root in s.import_roots:
        if str(root) == "/import":
            out.append(Location("import", str(root), True, *host("IMPORT", root), ("import",),
                                **_space(space, "IMPORT")))
        else:
            out.append(Location("import", str(root), True, str(root) if native else None, None, ("import",)))
    hosts = _external_hosts(environ)
    for root in s.external_db_roots:
        slot = root.name if root.name.isdigit() else None
        given, fs = hosts.get(slot or "", (str(root) if native else None, None))
        figures = _space(space, f"EXTERNAL_DB_{slot}") if slot else {}
        out.append(Location("external_databases", str(root), True, given, fs, ("external",), slot, **figures))
    return out


def to_host(path: str | None) -> str | None:
    """The host path of a path inside one of the locations, when the launcher gave that location's host path."""
    if not path:
        return None
    for loc in sorted(locations(), key=lambda x: len(x.container_path), reverse=True):
        root = loc.container_path.rstrip("/")
        if loc.host_path and (path == root or path.startswith(root + "/")):
            return loc.host_path.rstrip("/") + path[len(root):]
    return None


def from_host(path: str) -> str:
    """A path given as on the host (e.g. /Volumes/JM/BioInf/bakta/db) translated to where ARVA sees it; other paths
    are returned unchanged. Only a location's own folder and what lies under it are translated."""
    for loc in sorted(locations(), key=lambda x: len(x.host_path or ""), reverse=True):
        host = (loc.host_path or "").rstrip("/")
        if host and host != loc.container_path.rstrip("/") and (path == host or path.startswith(host + "/")):
            return loc.container_path.rstrip("/") + path[len(host):]
    return path


def usage(path: str) -> tuple[int | None, int | None]:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None, None
    return u.free, u.total


# --- Free space as seen through Docker Desktop's file sharing ---------------------------------------------------

def _unescape(field_text: str) -> str:
    """A /proc/mounts field: space, tab, newline and backslash are written as octal escapes (\\040 ...)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field_text)


def mount_source(path: str) -> str | None:
    """The source of the mount whose target is exactly `path` (the last one listed, as it hides the others)."""
    try:
        with open(PROC_MOUNTS, encoding="utf-8", errors="replace") as fh:
            lines = fh.read(1_000_000).splitlines()
    except OSError:
        return None
    found = None
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and _unescape(fields[1]) == path:
            found = _unescape(fields[0])
    return found


def volume_of(host: str | None) -> str | None:
    """/Volumes/<Disk> for a host path on a Mac's external disk, else None."""
    m = re.match(r"(/Volumes/[^/]+)(?:/|$)", host or "")
    return m.group(1) if m else None


def docker_share(source: str | None) -> str | None:
    """The host folder Docker Desktop shares a mount from (/run/host_mark/Volumes -> /Volumes), or None."""
    if not source or not (source == HOST_MARK or source.startswith(HOST_MARK + "/")):
        return None
    return source[len(HOST_MARK):] or "/"


@dataclass(frozen=True)
class Space:
    """The free space and size ARVA uses for a location, and where they come from: "container" (read here),
    "host_at_start" (the launcher's, because the container's belongs to another disk) or "container_misreported"
    (the container's, known to be another disk's, with no launcher figure to use instead)."""
    free_bytes: int | None
    total_bytes: int | None
    source: str
    misreported: bool = False
    reason: str | None = None  # parent_share | size_differs
    container_free_bytes: int | None = None
    container_total_bytes: int | None = None
    share: str | None = None
    disk: str | None = None
    # host_at_start: what ARVA has written to its folders on that disk since the measurement (subtracted from the
    # launcher's free space), or None when it could not be measured (then nothing is subtracted).
    written_bytes: int | None = None


def misreport(loc: Location, container_total: int | None) -> tuple[str | None, str | None, str | None]:
    """(reason, Docker's share, the disk to share) when the container's figures are not the location's disk's."""
    disk = volume_of(loc.host_path)
    share = docker_share(mount_source(loc.container_path))
    if disk and share and (share == "/" or (share != disk and disk.startswith(share.rstrip("/") + "/"))):
        return "parent_share", share, disk
    # The size check only where Docker Desktop's file sharing serves the mount: elsewhere (Linux, a Docker volume) a
    # filesystem's reported size may change on its own (ZFS datasets share their pool), and nothing is misreported.
    if share is not None and loc.host_total_bytes and container_total is not None:
        tolerance = max(SIZE_TOLERANCE_MIN_BYTES, SIZE_TOLERANCE * loc.host_total_bytes)
        if abs(container_total - loc.host_total_bytes) > tolerance:
            return "size_differs", share, disk
    return None, share, disk


def _space_for(loc: Location, free: int | None, total: int | None) -> Space:
    reason, share, disk = misreport(loc, total)
    if reason is None:
        return Space(free, total, "container", share=share, disk=disk)
    if loc.host_free_bytes is not None:
        written = written_since(loc)
        left = max(0, loc.host_free_bytes - (written or 0))
        return Space(left, loc.host_total_bytes, "host_at_start", True, reason, free, total, share, disk, written)
    return Space(free, total, "container_misreported", True, reason, free, total, share, disk)


# --- What ARVA has written since the launcher measured the disk -------------------------------------------------

_tree_cache: dict[str, tuple[float, int | None]] = {}
_local_baseline: dict[str, dict[str, int | None]] = {}


def tree_bytes(path: str) -> int | None:
    """The space the files under `path` take (the larger of their size and their allocated blocks, so that a
    growth is not under-counted), re-read at most every TREE_CACHE_SECONDS; None beyond TREE_MAX_ENTRIES entries."""
    now = time.monotonic()
    hit = _tree_cache.get(path)
    if hit is not None and now - hit[0] < TREE_CACHE_SECONDS:
        return hit[1]
    total, entries, stack = 0, 0, [path]
    while stack and entries <= TREE_MAX_ENTRIES:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for entry in it:
                entries += 1
                if entries > TREE_MAX_ENTRIES:
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                except OSError:
                    continue
                total += max(st.st_size, getattr(st, "st_blocks", 0) * 512)
    result = total if entries <= TREE_MAX_ENTRIES else None
    _tree_cache[path] = (now, result)
    return result


def _baseline(key: str, paths: list[str]) -> dict[str, int | None]:
    """Each folder's tree size at its first reading after the measurement `key`, kept in the metadata (shared by
    the API and the worker, and surviving restarts); in this process only when the metadata cannot be used."""
    local = _local_baseline.setdefault(key, {})
    if all(p in local for p in paths):
        return local
    try:
        from app.models import AppSetting

        with SessionLocal() as db:
            row = db.get(AppSetting, BASELINE_KEY)
            value = row.value if row is not None and isinstance(row.value, dict) else {}
            trees = value.get("trees") if value.get("measured_at") == key else None
            trees = {k: v for k, v in trees.items() if v is None or isinstance(v, int)} if isinstance(trees, dict) else {}
            missing = [p for p in paths if p not in trees]
            if missing:
                trees.update({p: tree_bytes(p) for p in missing})
                new = {"measured_at": key, "trees": trees}
                if row is None:
                    db.add(AppSetting(key=BASELINE_KEY, value=new))
                else:
                    row.value = new
                db.commit()
    except SQLAlchemyError:
        trees = {**{p: tree_bytes(p) for p in paths if p not in local}, **local}
    local.update(trees)
    return local


def _same_disk(a: Location, b: Location) -> bool:
    disk = volume_of(a.host_path)
    return a.container_path == b.container_path or (disk is not None and disk == volume_of(b.host_path))


def written_since(loc: Location) -> int | None:
    """What ARVA has added to its writable folders on `loc`'s disk since the launcher measured it, or None when a
    folder's tree could not be measured."""
    when = host_space().get("ARVA_HOST_SPACE_MEASURED_AT") or ""
    paths = [x.container_path for x in locations() if not x.read_only and _same_disk(x, loc)
             and folder_available(x.container_path)]
    if not paths:
        return 0
    base = _baseline(when, paths)
    grown = 0
    for p in paths:
        now, then = tree_bytes(p), base.get(p)
        if now is None or then is None:
            return None
        grown += max(0, now - then)
    return grown


def space_of(loc: Location) -> Space:
    return _space_for(loc, *usage(loc.container_path))


def location_of(path: str | Path) -> Location | None:
    """The most specific location that holds `path` (as ARVA sees it)."""
    text = str(path)
    for loc in sorted(locations(), key=lambda x: len(x.container_path), reverse=True):
        root = loc.container_path.rstrip("/")
        if text == root or text.startswith(root + "/"):
            return loc
    return None


def free_space(path: str | Path) -> Space:
    """The free space a write to `path` may count on: the location's (space_of) or, outside every location, the
    filesystem's own. Raises OSError when the path cannot be read, as shutil.disk_usage does."""
    u = shutil.disk_usage(path)
    loc = location_of(path)
    return Space(u.free, u.total, "container") if loc is None else _space_for(loc, u.free, u.total)


def folder_available(path: str | Path) -> bool:
    try:
        return os.path.isdir(path) and os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


def unavailable_reason(path: str) -> str:
    """Why a folder ARVA expected is not there: its location's root is missing (the disk is not connected) or only
    the folder itself is. The most specific location counts (natively the database folder can lie in the data
    folder)."""
    for loc in sorted(locations(), key=lambda x: len(x.container_path), reverse=True):
        root = loc.container_path.rstrip("/")
        if path == root or path.startswith(root + "/"):
            return "folder_missing" if folder_available(root) else "disk_not_connected"
    if path.startswith(EXTERNAL_PREFIX):
        return "disk_not_connected"
    return "folder_missing"


# --- Storage marker ---------------------------------------------------------------------------------------------

class _InvalidMarker(Exception):
    pass


def _read_marker(root: Path) -> str | None:
    try:
        text = (root / MARKER).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _InvalidMarker from exc
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not _ID.fullmatch(data["id"]):
        raise _InvalidMarker
    return data["id"]


def marker_present(root: Path | None = None) -> bool:
    """The data folder holds a readable storage marker (what can be known without the metadata)."""
    try:
        return _read_marker(root or get_settings().storage_root) is not None
    except (OSError, _InvalidMarker):
        return False


def _write_marker(root: Path) -> str:
    """The marker of a data folder used for the first time (never replaced: an existing one is read instead)."""
    marker_id = str(uuid.uuid4())
    content = json.dumps({"id": marker_id, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                          "created_by": f"ARVA {__version__}",
                          "note": "Ties this data folder to ARVA's metadata; do not edit or copy it to another folder."},
                         indent=2) + "\n"
    try:
        fd = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return _read_marker(root) or marker_id
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    return marker_id


def _recorded(db) -> str | None:
    from app.models import AppSetting

    row = db.get(AppSetting, SETTING_KEY)
    value = row.value.get("data_id") if row and isinstance(row.value, dict) else None
    return value if isinstance(value, str) else None


def _record(db, marker_id: str) -> None:
    from app.models import AppSetting

    try:
        row = db.get(AppSetting, SETTING_KEY, with_for_update=True)
        value = {"data_id": marker_id, "recorded_at": datetime.now(UTC).isoformat(timespec="seconds")}
        if row is None:
            db.add(AppSetting(key=SETTING_KEY, value=value))
        elif row.value.get("data_id") is None:
            row.value = {**row.value, **value}
        db.commit()
    except IntegrityError:
        db.rollback()


def backup_files(root: Path | None = None) -> list[dict[str, Any]]:
    folder = (root or get_settings().storage_root) / "backups"
    files = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    for entry in entries:
        m = _BACKUP.fullmatch(entry.name)
        if not m or not entry.is_file(follow_symlinks=False):
            continue
        try:
            created = datetime.strptime(m.group(2), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        files.append({"name": entry.name, "kind": m.group(1), "created_at": created,
                      "size_bytes": entry.stat(follow_symlinks=False).st_size})
    return sorted(files, key=lambda f: f["created_at"], reverse=True)


def inspect(db, create: bool = False) -> MarkerState:
    """The data folder's marker against the metadata. With `create`, a first-used folder gets its marker and an
    unrecorded marker (no backups beside it) is recorded."""
    root = get_settings().storage_root
    host = host_path(os.environ.get("ARVA_HOST_DATA_DIR"))
    recorded = _recorded(db)
    base = {"path": str(root), "host_path": host, "recorded_id": recorded}
    try:
        if not root.is_dir():
            return MarkerState("unavailable", **base)
        disk_id = _read_marker(root)
    except OSError:
        return MarkerState("unavailable", **base)
    except _InvalidMarker:
        return MarkerState("invalid", **base)
    created = False
    if disk_id is None:
        if recorded is not None:
            return MarkerState("missing", **base)
        if not create:
            return MarkerState("new", **base)
        try:
            disk_id, created = _write_marker(root), True
        except OSError:
            return MarkerState("unavailable", **base)
    if recorded is None:
        if not created and (count := len(backup_files(root))):
            return MarkerState("restore_needed", **base, disk_id=disk_id, backups=count)
        if not create:
            return MarkerState("new", **base, disk_id=disk_id)
        _record(db, disk_id)
        base["recorded_id"] = recorded = _recorded(db)
    if recorded != disk_id:
        return MarkerState("mismatch", **base, disk_id=disk_id)
    return MarkerState("ok", **base, disk_id=disk_id)


def ensure_data() -> MarkerState:
    """Raise StorageUnavailable unless ARVA may write to the data folder now (its own database session, so that a
    caller's transaction is left alone)."""
    with SessionLocal() as db:
        state = inspect(db, create=True)
    if state.status != "ok":
        raise StorageUnavailable(state)
    return state


def adopt() -> MarkerState:
    """Use a data folder that holds metadata backups with the current (new) metadata, at the user's request."""
    with SessionLocal() as db:
        state = inspect(db)
        if state.status == "restore_needed" and state.disk_id is not None:
            _record(db, state.disk_id)
            return inspect(db)
    if not state.writable:
        raise StorageUnavailable(state)
    raise ValueError("this data folder is already used by this ARVA; there is nothing to adopt")


def health() -> str:
    try:
        with SessionLocal() as db:
            return inspect(db).status
    except (SQLAlchemyError, OSError):
        return "unknown"


# --- Metadata backups -------------------------------------------------------------------------------------------

def _last_result(folder: Path) -> dict[str, Any] | None:
    try:
        text = (folder / LAST_RESULT).read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    try:
        at = datetime.strptime(values.get("at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    result = values.get("result")
    if result not in ("ok", "failed"):
        return None
    kind = values.get("kind") if values.get("kind") in ("auto", "manual", "pre-restore") else None
    detail = " ".join(_CONTROL.sub(" ", values.get("detail", "")).split())[:300] or None
    code = values.get("code") if values.get("code") in BACKUP_CODES else None
    return {"result": result, "kind": kind, "at": at, "detail": detail, "code": code}


def _pending(folder: Path) -> datetime | None:
    for name in (REQUEST, REQUEST + ".taken"):
        try:
            return datetime.fromtimestamp((folder / name).stat().st_mtime, UTC)
        except OSError:
            continue
    return None


def backups_overview() -> dict[str, Any]:
    s = get_settings()
    folder = s.backups_dir
    files = backup_files()
    return {"folder": str(folder), "host_folder": to_host(str(folder)), "count": len(files), "files": files[:30],
            "last_result": _last_result(folder), "pending_since": _pending(folder),
            "interval_hours": s.backup_interval_hours, "keep": s.backup_keep}


def request_backup() -> datetime:
    """Ask the backup service for a backup now (it looks for the request every 30 seconds)."""
    ensure_data()
    folder = get_settings().backups_dir
    folder.mkdir(exist_ok=True)
    tmp = folder / f"{REQUEST}.{uuid.uuid4().hex}"
    tmp.write_text(json.dumps({"requested_at": datetime.now(UTC).isoformat(timespec="seconds")}) + "\n")
    os.replace(tmp, folder / REQUEST)
    return _pending(folder) or datetime.now(UTC)


# --- Overview ---------------------------------------------------------------------------------------------------

@dataclass
class LocationStatus:
    location: Location
    available: bool
    free_bytes: int | None
    total_bytes: int | None
    warnings: list[str] = field(default_factory=list)
    space: Space | None = None


def status(loc: Location) -> LocationStatus:
    available = folder_available(loc.container_path)
    sp = space_of(loc) if available else None
    free, total = (sp.free_bytes, sp.total_bytes) if sp else (None, None)
    warnings = []
    if not available:
        warnings.append("not_connected")
    if loc.filesystem in FAT:
        warnings.append("fat_filesystem")
    if sp is not None and sp.misreported:
        warnings.append("space_misreported")
    if not loc.read_only and free is not None and free < LOW_SPACE_BYTES and (sp is None or sp.source != "container_misreported"):
        warnings.append("low_space")
    return LocationStatus(loc, available, free, total, warnings, sp)


def overview(db) -> dict[str, Any]:
    from app.models import ReferenceDatabase

    marker = inspect(db)
    paths = list(db.scalars(select(ReferenceDatabase.path).where(ReferenceDatabase.path.isnot(None))))
    when = measured_at()
    out = []
    for st in map(status, locations()):
        loc = st.location
        root = loc.container_path.rstrip("/")
        sp = st.space
        out.append({
            "role": loc.role, "container_path": loc.container_path, "host_path": loc.host_path,
            "read_only": loc.read_only, "available": st.available, "free_bytes": st.free_bytes,
            "total_bytes": st.total_bytes, "filesystem": loc.filesystem, "warnings": st.warnings,
            "marker": marker.status if loc.role == "data" else None, "stores": list(loc.stores), "slot": loc.slot,
            "databases": sum(1 for p in paths if p == root or p.startswith(root + "/"))
            if loc.role in ("databases", "external_databases", "import") else None,
            "space_source": sp.source if sp else None,
            "misreport": None if sp is None or not sp.misreported else {
                "reason": sp.reason, "share": sp.share, "disk": sp.disk or volume_of(loc.host_path),
                "container_free_bytes": sp.container_free_bytes, "container_total_bytes": sp.container_total_bytes,
                "written_since_bytes": sp.written_bytes},
            "host_free_bytes": loc.host_free_bytes, "host_total_bytes": loc.host_total_bytes,
            "host_measured_at": when if loc.host_total_bytes is not None else None,
        })
    return {"marker": marker, "locations": out, "backups": backups_overview(), "in_container": in_container()}


def _misreport_text(loc: dict[str, Any], es: bool) -> str:
    """The launcher summary's line about a location whose space Docker reports from another disk."""
    m = loc["misreport"]
    disk = m["disk"] or ("su disco" if es else "its disk")
    # The share to remove: the one the mount comes from when it lies above the disk (/Volumes, or /), else /Volumes.
    share = m["share"] if m["share"] and m["share"] != disk and not (m["share"] + "/").startswith(disk + "/") \
        else "/Volumes"
    seen = fmt_bytes(m["container_total_bytes"]) if m["container_total_bytes"] is not None else "?"
    host = fmt_bytes(loc["host_total_bytes"]) if loc["host_total_bytes"] is not None else "?"
    written = m.get("written_since_bytes")
    if es:
        why = (f"Docker Desktop la comparte a través de {m['share']}, y así ARVA lee dentro de Docker el espacio de "
               "otro disco (el de arranque de la Mac)" if m["reason"] == "parent_share" else
               f"dentro de Docker su disco mide {seen}, pero en la Mac {host}: ARVA lee el espacio de otro disco")
        used = (("los controles de espacio usan la cifra que midió scripts/start.sh al iniciar, menos "
                 f"{fmt_bytes(written)} que ARVA escribió desde entonces (no cuenta lo que escriben otros programas)")
                if written is not None else
                "los controles de espacio usan la cifra que midió scripts/start.sh al iniciar, sin descontar lo "
                "escrito desde entonces (no se pudo medir)") if loc["space_source"] == "host_at_start" else \
            "no hay cifra del lanzador, así que los controles usan la de Docker, que es de otro disco"
        return (f"ATENCIÓN: {why}; {used}. Compartir el propio disco: Docker Desktop → Settings → File sharing → + → "
                f"Cmd+Shift+G → {disk} → quitar {share} → Apply, y volver a abrir ARVA.")
    why = (f"Docker Desktop shares it through {m['share']}, so inside Docker ARVA reads another disk's space (the "
           "Mac's startup disk)" if m["reason"] == "parent_share" else
           f"inside Docker its disk measures {seen} but {host} on the Mac: ARVA reads another disk's space")
    used = (("the free-space checks use the figure scripts/start.sh measured at start, minus "
             f"{fmt_bytes(written)} ARVA has written since (what other programs write is not counted)")
            if written is not None else
            "the free-space checks use the figure scripts/start.sh measured at start, without subtracting what was "
            "written since (it could not be measured)") if loc["space_source"] == "host_at_start" else \
        "there is no launcher figure, so the checks use Docker's, which is another disk's"
    return (f"ATTENTION: {why}; {used}. Share the disk itself: Docker Desktop → Settings → File sharing → + → "
            f"Cmd+Shift+G → {disk} → remove {share} → Apply, then start ARVA again.")


def _report(lang: str) -> int:
    """The storage summary scripts/start.sh prints once ARVA runs (English or Spanish)."""
    es = lang == "es"
    with SessionLocal() as db:
        state = inspect(db, create=True)
        o = overview(db)
    names = {"data": ("Data folder", "Carpeta de datos"), "databases": ("Database folder", "Carpeta de bases de datos"),
             "import": ("Import folder", "Carpeta de importación"),
             "external_databases": ("Added database folder", "Carpeta de bases de datos añadida")}
    print("Almacenamiento" if es else "Storage")
    for loc in o["locations"]:
        if loc["host_path"]:
            where = loc["host_path"]
        elif loc["role"] == "import" and loc["container_path"] == "/import":
            # docker-compose.yml mounts the import/ folder next to it (not a Docker volume).
            where = ("la carpeta import/ junto a docker-compose.yml" if es
                     else "the import/ folder next to docker-compose.yml")
        elif loc["role"] in ("data", "databases"):
            where = "volumen de Docker" if es else "Docker volume"
        else:
            where = "no indicada por el lanzador" if es else "not given by the launcher"
        space = (f"{fmt_bytes(loc['free_bytes'])} libres" if es else f"{fmt_bytes(loc['free_bytes'])} free") \
            if loc["free_bytes"] is not None else ("no disponible" if es else "not available")
        print(f"  {names[loc['role']][es]}: {where} ({space})")
        if loc["misreport"]:
            print("    " + _misreport_text(loc, es))
    if state.status != "ok":
        exc = StorageUnavailable(state)
        print(("  ATENCIÓN: " + render(MESSAGES_ES[exc.code], exc.params)) if es else f"  ATTENTION: {exc}")
        return 1
    b = o["backups"]
    last = b["files"][0]["created_at"].strftime("%Y-%m-%d %H:%M UTC") if b["files"] else None
    print(f"  Copias de los metadatos: {b['count']}" + (f", la última {last}" if last else "") if es
          else f"  Metadata backups: {b['count']}" + (f", latest {last}" if last else ""))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print where ARVA keeps its files.")
    parser.add_argument("--lang", choices=("en", "es"), default="en")
    raise SystemExit(_report(parser.parse_args().lang))
