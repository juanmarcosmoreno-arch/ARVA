"""Where ARVA keeps its files, whether each folder is there, and the marker that ties the data folder to the metadata.

Locations: the data folder (ARVA_STORAGE_ROOT: raw, processed, results, reports, logs and the metadata backups), the
database folder (ARVA_DB_DIR, where the Database Manager installs databases), the import folders (ARVA_IMPORT_ROOTS,
read-only) and the external database folders (ARVA_EXTERNAL_DB_ROOTS: existing databases used in place, read-only,
never modified or deleted). scripts/start.sh passes each folder's path on the host and its filesystem as ARVA_HOST_*
variables: untrusted strings, validated here and only shown.

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
# ARVA's own threshold for a "low space" warning (the launcher uses the same).
LOW_SPACE_BYTES = 20 * 1024**3
FAT = {"exfat", "msdos", "vfat", "fat", "fat12", "fat16", "fat32"}
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FS = re.compile(r"[a-z0-9_+-]{1,32}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BACKUP = re.compile(r"arva-metadata-(auto|manual|pre-restore)-(\d{8}T\d{6}Z)\.dump")
_SLOT = re.compile(r"ARVA_HOST_EXTERNAL_DB_(\d{1,10})")

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


@dataclass(frozen=True)
class Location:
    role: str  # data | databases | import | external_databases
    container_path: str
    read_only: bool
    host_path: str | None
    filesystem: str | None
    stores: tuple[str, ...]
    slot: str | None = None


def _external_hosts(environ: Mapping[str, str]) -> dict[str, tuple[str | None, str | None]]:
    out = {}
    for name, value in environ.items():
        if m := _SLOT.fullmatch(name):
            out[m.group(1)] = (host_path(value), filesystem(environ.get(f"{name}_FS")))
    return out


def locations(environ: Mapping[str, str] | None = None) -> list[Location]:
    """Every folder ARVA uses. Running natively (not in a container), a folder's host path is its own path."""
    environ = os.environ if environ is None else environ
    s = get_settings()
    native = not in_container()

    def host(name: str, path: Path) -> tuple[str | None, str | None]:
        given = host_path(environ.get(f"ARVA_HOST_{name}_DIR"))
        return (given or (str(path) if native else None)), filesystem(environ.get(f"ARVA_HOST_{name}_FS"))

    data, databases = s.storage_root.resolve(), s.databases_dir.resolve()
    out = [
        Location("data", str(data), False, *host("DATA", data),
                 ("raw", "processed", "results", "reports", "logs", "backups")),
        Location("databases", str(databases), False, *host("DATABASES", databases), ("downloads",)),
    ]
    for root in s.import_roots:
        given, fs = host("IMPORT", root) if str(root) == "/import" else ((str(root) if native else None), None)
        out.append(Location("import", str(root), True, given, fs, ("import",)))
    hosts = _external_hosts(environ)
    for root in s.external_db_roots:
        slot = root.name if root.name.isdigit() else None
        given, fs = hosts.get(slot or "", (str(root) if native else None, None))
        out.append(Location("external_databases", str(root), True, given, fs, ("external",), slot))
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
    return {"result": result, "kind": kind, "at": at, "detail": detail}


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


def status(loc: Location) -> LocationStatus:
    available = folder_available(loc.container_path)
    free, total = usage(loc.container_path) if available else (None, None)
    warnings = []
    if not available:
        warnings.append("not_connected")
    if loc.filesystem in FAT:
        warnings.append("fat_filesystem")
    if not loc.read_only and free is not None and free < LOW_SPACE_BYTES:
        warnings.append("low_space")
    return LocationStatus(loc, available, free, total, warnings)


def overview(db) -> dict[str, Any]:
    from app.models import ReferenceDatabase

    marker = inspect(db)
    paths = list(db.scalars(select(ReferenceDatabase.path).where(ReferenceDatabase.path.isnot(None))))
    out = []
    for st in map(status, locations()):
        loc = st.location
        root = loc.container_path.rstrip("/")
        out.append({
            "role": loc.role, "container_path": loc.container_path, "host_path": loc.host_path,
            "read_only": loc.read_only, "available": st.available, "free_bytes": st.free_bytes,
            "total_bytes": st.total_bytes, "filesystem": loc.filesystem, "warnings": st.warnings,
            "marker": marker.status if loc.role == "data" else None, "stores": list(loc.stores), "slot": loc.slot,
            "databases": sum(1 for p in paths if p == root or p.startswith(root + "/"))
            if loc.role in ("databases", "external_databases", "import") else None,
        })
    return {"marker": marker, "locations": out, "backups": backups_overview(), "in_container": in_container()}


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
        where = loc["host_path"] or ("volumen de Docker" if es else "Docker volume")
        space = (f"{fmt_bytes(loc['free_bytes'])} libres" if es else f"{fmt_bytes(loc['free_bytes'])} free") \
            if loc["free_bytes"] is not None else ("no disponible" if es else "not available")
        print(f"  {names[loc['role']][es]}: {where} ({space})")
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
