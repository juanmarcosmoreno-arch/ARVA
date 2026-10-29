"""Database Manager (spec §30): download, register, verify, choose and delete reference databases of every kind
(database_kinds.py; the downloadable versions are in database_catalogue.py).

Nothing is downloaded without an explicit confirmation of the archive's size and licence, and only from the
catalogue's official URL, into a database folder ARVA may write (scripts/start.sh --databases-dir). Downloads, copies
extracted from an archive and full verifications run in the worker; this module validates requests, plans the disk
space and records the state. Databases ARVA installed or extracted may be deleted by ARVA; a registered folder or file
(in a database folder, an import folder or an added database folder, ARVA_EXTERNAL_DB_ROOTS) is only read, never
written, and never deleted. A database whose folder is on a disk that is not connected is shown as unavailable: it
is neither verified nor used nor deleted until the disk is back, and is available again as soon as it is.

Verification has two levels: quick (the kind's files are there with the sizes recorded at registration and the
version file still says the same) runs at once; full (the SHA-256 of every file, compared with the manifest recorded
the first time, and with the publisher's per-file checksums where it publishes them) is a background job.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.messages import render
from app.db.base import new_uuid
from app.models import AnalysisJob, DatabaseOrigin, DatabaseStatus, ReferenceDatabase, VersionSource
from app.services import database_detect as detection
from app.services import database_kinds as kinds
from app.services import jobs as jobs_service
from app.services import reference_collections as rc
from app.services.capacity import fmt_bytes
from app.services.database_catalogue import (
    BAKTA_REQUIRED_FILES,
    BAKTA_SCHEMA_MAJOR,
    BAKTA_TYPE_FILE,
    BAKTA_VERSION_KEYS,
    CatalogueEntry,
    bakta_entry_for,
    entry,
)

DOWNLOADS = ".arva-downloads"
STAGING = ".arva-staging"
BUSY = (DatabaseStatus.downloading, DatabaseStatus.extracting, DatabaseStatus.verifying)
USABLE = (DatabaseStatus.installed, DatabaseStatus.registered)
OWNED = (DatabaseOrigin.download, DatabaseOrigin.extract)
_MAX_PATH = 4096
_FOLDER_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_DECLARED = re.compile(r"[\w.,:;()#+/ -]{1,100}")
_BROWSE_LIMIT = 2000
# Task-queue states of a task no worker executes (yet, or any more).
_WAITING = {"queued", "deferred", "scheduled"}
_NOT_EXECUTING = {"finished", "failed", "stopped", "canceled", "missing"}

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "not_recognised": "ARVA does not recognise {path} as a database of a kind it knows. Choose the folder (or file) "
                      "that holds the database itself.",
    "ambiguous_kind": "{path} matches several kinds ({kinds}); choose one.",
    "kind_mismatch": "{path} is not a {kind} database.",
    "detection_failed": "{path} cannot be registered: {problems}",
    "version_needed": "The files of {path} do not state its version: declare it.",
    "version_invalid": "The declared version must be 1 to 100 letters, digits, spaces or . , : ; ( ) # + / -",
    "date_needed": "Give the date of this reference collection (YYYY-MM-DD), for example the day you downloaded it.",
    "zip_needs_extraction": "{path} is a zip archive, which FastANI cannot read: extract a copy into a database "
                            "folder instead (the zip is left as it is).",
    "already_registered": "{path} is already registered or installed.",
    "outside_roots": "{path} is outside the folders ARVA may read databases from: {roots} (the database folder, the "
                     "import folders and the folders added with scripts/start.sh --add-databases).",
    "not_found": "{path} does not exist or cannot be read.",
    "arva_partial": "That folder holds ARVA's partial downloads.",
    "bad_destination": "{path} is not a database folder ARVA may write to ({allowed}).",
    "bad_folder": "The folder name must be a relative path of letters, digits, . _ and - (for example "
                  "bakta-light/6.0), without .. or a leading dot.",
    "target_exists": "{path} already exists; choose another folder name.",
    "not_usable": "{name} cannot be the default: it is {status}.",
    "incompatible": "{name} {version} cannot be used by {tool} {tool_version} (it needs database schema {schema}).",
    "bundled_only": "{path} holds {kind}, which ARVA reads only where {tool}'s own environment installed it; it is "
                    "listed by itself when {tool} is installed.",
    "bundled_read_only": "{name} is part of {tool}'s own package: ARVA reads it where it is and cannot remove it (it "
                         "goes with the tool's environment).",
    "mobsuite_taxonomy_unreachable": "NCBI's dated taxonomy archives could not be read ({detail}).",
    "mobsuite_taxonomy_unknown": "NCBI lists no taxonomy archive {name}.",
    "mobsuite_taxonomy_confirm": "Confirm the NCBI taxonomy archive ({name}) MOB-suite's host-range predictions will "
                                 "use.",
}


class DatabaseError(ValueError):
    """The request is invalid (400); `code` and `params` name it for the interface when it is a coded refusal."""

    def __init__(self, message: str, code: str | None = None, **params):
        super().__init__(render(MESSAGES[code], params) if code and not message else message)
        self.code, self.params = code, params


def refusal(code: str, **params) -> DatabaseError:
    return DatabaseError("", code, **params)


class DatabaseStateError(RuntimeError):
    """The database's state does not allow the request (409)."""

    def __init__(self, message: str, code: str | None = None, **params):
        super().__init__(render(MESSAGES[code], params) if code and not message else message)
        self.code, self.params = code, params


class DatabaseUnavailableError(DatabaseStateError):
    """The database's folder cannot be read now (409), most often because its disk is not connected."""

    def __init__(self, record: ReferenceDatabase, reason: str):
        from app.services.locations import to_host

        shown = to_host(record.path) or record.path or "?"
        cause = "its disk is not connected" if reason == "disk_not_connected" else "the folder is missing"
        super().__init__(f"{record.name} cannot be used now: {cause} ({shown}). Connect the disk and start ARVA "
                         "again; the database is kept as it is.")
        self.code = "database_unavailable"
        self.params = {"name": record.name, "path": shown, "reason": reason}


class DatabaseFolderUnavailable(DatabaseError):
    """The database folder (ARVA_DB_DIR) cannot be used now (503): its disk is not connected."""

    def __init__(self, root: Path):
        from app.services.locations import to_host

        path = to_host(str(root)) or str(root)
        super().__init__(f"The database folder {path} is not available: its disk is probably not connected. Connect "
                         "it and start ARVA again (scripts/start.sh); nothing was written.")
        self.code, self.params = "databases_unavailable", {"path": path}


class DatabaseSpaceError(ValueError):
    """Not enough free space in the chosen database folder (507)."""

    def __init__(self, needed: int, available: int, db_dir: Path):
        self.needed, self.available = needed, available
        super().__init__(f"Not enough free space in the database folder {db_dir}: {fmt_bytes(needed)} ({needed:,} "
                         f"bytes) needed but only {fmt_bytes(available)} can be used (free space minus the "
                         "ARVA_MIN_FREE_BYTES reserve)")


def now() -> datetime:
    return datetime.now(UTC)


def databases_dir() -> Path:
    """ARVA_DB_DIR, created only when its parent exists (a folder on a disk that is not connected must not be
    created on the internal disk instead)."""
    root = get_settings().databases_dir.resolve()
    try:
        if not root.is_dir():
            if not root.parent.is_dir():
                raise DatabaseFolderUnavailable(root)
            root.mkdir(exist_ok=True)
        os.stat(root)
    except OSError as exc:
        raise DatabaseFolderUnavailable(root) from exc
    return root


def destination_root(record: ReferenceDatabase) -> Path:
    """The database folder a download or extraction writes into (recorded when it was planned)."""
    given = (record.details or {}).get("destination")
    return Path(given) if given else databases_dir()


def downloads_dir(record_id: str, root: Path | None = None) -> Path:
    return (root or databases_dir()) / DOWNLOADS / record_id


def staging_dir(record_id: str, root: Path | None = None) -> Path:
    return (root or databases_dir()) / STAGING / record_id


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def available_bytes(path: Path) -> int:
    """Free space that may be filled, keeping the ARVA_MIN_FREE_BYTES reserve."""
    return max(0, free_bytes(path) - get_settings().min_free_bytes)


def tree_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


# --- Bakta's own folder check -----------------------------------------------------------------------------------

def check_bakta_dir(path: Path) -> dict:
    """The checks Bakta 1.12.2 makes before using a database folder (bakta/db.py check()): a readable version.json
    with date, major, minor and type, the schema version it requires, and every required file. Returns the
    version.json content."""
    import json

    version_path = path / "version.json"
    if not version_path.is_file():
        raise DatabaseError(f"{path} has no version.json, so it is not a Bakta database folder (is the database in "
                            "a db/ or db-light/ subfolder?)")
    try:
        info = json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatabaseError(f"version.json in {path} could not be read: {exc}") from exc
    if not isinstance(info, dict) or (missing := [k for k in BAKTA_VERSION_KEYS if k not in info]):
        raise DatabaseError(f"version.json in {path} lacks {', '.join(missing) if isinstance(info, dict) else 'keys'}"
                            " (Bakta needs date, major, minor and type)")
    if not isinstance(info["major"], int) or not isinstance(info["minor"], int) or info["type"] not in BAKTA_TYPE_FILE:
        raise DatabaseError(f"version.json in {path} has an unexpected major, minor or type: "
                            f"{info['major']!r}, {info['minor']!r}, {info['type']!r}")
    if info["major"] != BAKTA_SCHEMA_MAJOR:
        raise DatabaseError(f"this is Bakta database {info['major']}.{info['minor']}; the Bakta versions ARVA "
                            f"supports need database schema {BAKTA_SCHEMA_MAJOR}.x")
    required = (*BAKTA_REQUIRED_FILES, BAKTA_TYPE_FILE[info["type"]])
    if missing := [f for f in required if not (path / f).is_file() or not os.access(path / f, os.R_OK)]:
        raise DatabaseError(f"{path} lacks the Bakta database file(s) {', '.join(missing)}")
    return info


def bakta_version(info: dict) -> str:
    return f"{info['major']}.{info['minor']}"


# --- Locations ARVA may read and write databases in -------------------------------------------------------------

def writable_locations() -> list[dict]:
    """The database folders ARVA may download and extract into (today the one chosen with scripts/start.sh
    --databases-dir), with their free space."""
    from app.services.locations import folder_available, locations, usage

    out = []
    for loc in locations():
        if loc.role == "databases" and not loc.read_only:
            ok = folder_available(loc.container_path)
            free, total = usage(loc.container_path) if ok else (None, None)
            out.append({"path": loc.container_path, "host_path": loc.host_path, "available": ok, "free_bytes": free,
                        "total_bytes": total, "reserve_bytes": get_settings().min_free_bytes})
    return out


def browse_roots() -> list[dict]:
    """The folders the registration browser shows: the database folder and the added (read-only) database folders."""
    from app.services.locations import folder_available, locations

    return [{"path": loc.container_path, "host_path": loc.host_path, "read_only": loc.read_only,
             "role": loc.role, "available": folder_available(loc.container_path)}
            for loc in locations() if loc.role in ("databases", "external_databases")]


def _allowed_roots() -> list[Path]:
    s = get_settings()
    return [databases_dir(), *(Path(os.path.realpath(p)) for p in (*s.import_roots, *s.external_db_roots))]


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def list_context() -> rc.ListContext:
    from app.services.locations import from_host

    roots = _allowed_roots()
    return rc.ListContext(from_host=from_host, allowed=lambda p: _inside(p, roots))


def _shown(path: Path | str) -> str:
    from app.services.locations import to_host

    return to_host(str(path)) or str(path)


def resolve_registration_path(raw: str) -> Path:
    """The folder or file to register: an absolute path inside a database folder, an import folder or an added
    database folder, given as ARVA sees it or as on this computer (scripts/start.sh passes the host paths), links
    resolved."""
    from app.services.locations import from_host, to_host

    if not raw or len(raw) > _MAX_PATH or "\x00" in raw or not os.path.isabs(raw):
        raise DatabaseError("give the absolute path of the database folder")
    path = Path(os.path.realpath(from_host(raw)))
    roots = _allowed_roots()
    if not _inside(path, roots):
        raise refusal("outside_roots", path=raw, roots=", ".join(to_host(str(r)) or str(r) for r in roots))
    for root in roots:
        if any(path == root / d or root / d in path.parents for d in (DOWNLOADS, STAGING)):
            raise refusal("arva_partial")
    if not (path.is_dir() or path.is_file()) or not os.access(path, os.R_OK):
        raise refusal("not_found", path=raw)
    return path


def browse(root: str, rel: str = "") -> dict:
    """The folders and files under one of the browse roots (links followed only when they stay inside it)."""
    roots = {r["path"]: r for r in browse_roots()}
    if root not in roots:
        raise refusal("outside_roots", path=root, roots=", ".join(r["host_path"] or p for p, r in roots.items()))
    parts = PurePosixPath(rel or ".").parts
    if rel.startswith("/") or ".." in parts or "\x00" in rel or len(rel) > _MAX_PATH:
        raise DatabaseError("give a folder inside the chosen location")
    base = Path(os.path.realpath(root))
    folder = Path(os.path.realpath(base / rel)) if rel else base
    if not _inside(folder, [base]) or not folder.is_dir():
        raise refusal("not_found", path=_shown(base / rel))
    entries = []
    with os.scandir(folder) as it:
        for e in sorted(it, key=lambda e: (not e.is_dir(), e.name.lower())):
            if e.name.startswith(".arva-") or len(entries) >= _BROWSE_LIMIT:
                continue
            link = e.is_symlink()
            target = Path(os.path.realpath(e.path))
            if link and not _inside(target, [base]):
                continue
            is_dir = target.is_dir()
            try:
                size = None if is_dir else target.stat().st_size
            except OSError:
                continue
            entries.append({"name": e.name, "type": "folder" if is_dir else "file", "size_bytes": size, "link": link,
                            "path": str(Path(e.path))})
    here = folder.relative_to(base).as_posix()
    parent = None if folder == base else "" if folder.parent == base else folder.parent.relative_to(base).as_posix()
    return {"root": root, "path": "" if here == "." else here, "host_path": _shown(folder),
            "container_path": str(folder), "entries": entries, "truncated": len(entries) >= _BROWSE_LIMIT,
            "parent": parent}


# --- Detection and registration ---------------------------------------------------------------------------------

def detect(raw_path: str) -> tuple[Path, list[detection.Detection]]:
    path = resolve_registration_path(raw_path)
    return path, detection.detect(path, list_context())


def _choose(path: Path, found: list[detection.Detection], kind: str | None, raw: str) -> detection.Detection:
    if kind is not None:
        if kind not in kinds.BY_KEY:
            raise DatabaseError(f"unknown database kind {kind!r}")
        chosen = next((d for d in found if d.kind == kind), None)
        if chosen is None:
            raise refusal("kind_mismatch", path=raw, kind=kinds.BY_KEY[kind].name)
        return chosen
    real = [d for d in found if d.kind != "unknown"]
    if not real:
        if found and found[0].problems:
            raise refusal("detection_failed", path=raw, problems=found[0].problems[0].text)
        raise refusal("not_recognised", path=raw)
    if len(real) > 1:
        raise refusal("ambiguous_kind", path=raw, kinds=", ".join(kinds.BY_KEY[d.kind].name for d in real))
    return real[0]


def _declared(text: str | None) -> str | None:
    if text is None or not text.strip():
        return None
    text = " ".join(text.split())
    if not _DECLARED.fullmatch(text):
        raise refusal("version_invalid")
    return text


def _stored_detection(d: detection.Detection) -> dict:
    out = d.as_dict()
    out["facts"] = {k: v for k, v in out["facts"].items() if k != "genomes"}
    return out


def record_name(d: detection.Detection) -> tuple[str, str]:
    """(catalogue key or kind, display name) of a detected database."""
    if d.kind == "bakta" and d.catalogue_key and (e := bakta_entry_for(d.variant or "")):
        return e.key, e.name
    k = kinds.BY_KEY[d.kind]
    variant = {"ncbi_package": "NCBI Datasets package", "fastani_list": "FastANI list",
               "fasta_folder": "FASTA folder"}.get(d.variant or "") if d.kind == "reference_genomes" else d.variant
    return d.kind, f"{k.name} ({variant})" if variant and d.kind != "busco" else k.name


def collection_version(d: detection.Detection, day: str | None) -> str:
    facts = d.facts.get("collection") or {}
    variant = d.variant or ""
    with_package = (facts.get("with_metadata") or {}).get("package", 0)
    if variant == "fastani_list" and facts.get("genomes") and with_package == facts["genomes"]:
        variant = "ncbi_package"
    return rc.version_string(variant, day, facts.get("fingerprint", ""))


def register(db: Session, raw_path: str, kind: str | None = None, declared_version: str | None = None,
             collection_date: str | None = None, full_checksum: bool = False) -> ReferenceDatabase:
    """Record an existing database folder or file after the quick verification (its kind's files, their sizes and
    its version). The folder is never modified; with `full_checksum` the worker then computes the SHA-256 of every
    file, otherwise that can be asked for later."""
    path, found = detect(raw_path)
    if db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.path == str(path))) is not None:
        raise DatabaseStateError("", "already_registered", path=raw_path)
    d = _choose(path, found, kind, raw_path)
    if kinds.BY_KEY.get(d.kind) and kinds.BY_KEY[d.kind].download == "bundled":
        raise refusal("bundled_only", path=raw_path, kind=kinds.BY_KEY[d.kind].name, tool=kinds.BY_KEY[d.kind].tools[0].tool)
    if d.variant == "abricate":
        raise refusal("bundled_only", path=raw_path, kind=kinds.BY_KEY[d.kind].name, tool="ABRicate")
    if d.path_type == "zip":
        raise refusal("zip_needs_extraction", path=raw_path)
    if not d.ok:
        raise refusal("detection_failed", path=raw_path,
                      problems="; ".join(p.text for p in d.problems if p.blocking))
    version, source = d.version, VersionSource.file if d.version else None
    if d.kind == "reference_genomes":
        day = rc.valid_date(collection_date)
        if day is None:
            raise refusal("date_needed")
        version, source = collection_version(d, day), VersionSource.declared
    elif version is None:
        declared = _declared(declared_version)
        if declared is not None:
            version, source = declared, VersionSource.declared
        elif not d.version_by_checksum:
            raise refusal("version_needed", path=raw_path, suggested=d.suggested_version or "")
    key, name = record_name(d)
    k = kinds.BY_KEY[d.kind]
    catalogue = bakta_entry_for(d.variant or "") if d.kind == "bakta" else None
    same = catalogue is not None and catalogue.version == version
    stamp = now()
    record = ReferenceDatabase(
        key=key, kind=d.kind, name=name, version=version, version_source=source, path=str(path),
        source_url=catalogue.source_url if same else k.source_url,
        licence=catalogue.licence if same else None if catalogue else k.licence,
        status=DatabaseStatus.registered, origin=DatabaseOrigin.register, verification_level="quick",
        installed_at=stamp, verified_at=stamp, log_text="", size_bytes=_detected_bytes(d),
        notes=None if same or catalogue is None else (f"Version {version} differs from the catalogue's "
                                                      f"{catalogue.version}; the catalogue's facts (size, checksum, "
                                                      "licence) describe that version only."),
        details={"detection": _stored_detection(d), "version_json": d.facts.get("version_json"),
                 "collection": d.facts.get("collection"),
                 "catalogue": catalogue_snapshot(catalogue) if same else None},
        inventory=d.facts.get("genomes") if d.kind == "reference_genomes" else None,
    )
    known = {VersionSource.file: f"version read from {d.version_file}", VersionSource.declared: "version declared by the "
             "user", None: "version to be identified by the full checksum"}[source]
    append_log(record, f"Registered {_shown(path)} as {name} {version or ''} ({known}); quick verification passed. ARVA "
                       "only reads this folder and never changes or deletes it")
    db.add(record)
    db.flush()
    ensure_default(db, record.kind)
    db.commit()
    if full_checksum:
        return start_verify(db, record.id, "full")
    db.refresh(record)
    return record


def _detected_bytes(d: detection.Detection) -> int | None:
    if d.kind == "reference_genomes":
        return (d.facts.get("collection") or {}).get("bytes")
    sizes = [f.size for f in d.files if f.present and f.size is not None]
    return sum(sizes) if sizes else None


# --- Catalogue and plans ----------------------------------------------------------------------------------------

def catalogue_snapshot(e: CatalogueEntry) -> dict:
    return {k: v for k, v in asdict(e).items() if v not in (None, (), {})}


def entry_compatibility(e: CatalogueEntry) -> kinds.Compatibility:
    info = {"major": int(e.version.split(".")[0])} if e.kind == "bakta" else None
    return kinds.compatibility(e.kind, info)


def _same_version(db: Session, key: str, version: str | None) -> list[ReferenceDatabase]:
    return list(db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.key == key,
                                                           ReferenceDatabase.version == version)))


def _resumable(db: Session, e: CatalogueEntry) -> ReferenceDatabase | None:
    return next((r for r in _same_version(db, e.key, e.version) if r.origin is DatabaseOrigin.download
                 and r.status in (DatabaseStatus.failed, DatabaseStatus.cancelled)), None)


def partial_bytes(record: ReferenceDatabase, e: CatalogueEntry) -> int:
    part = downloads_dir(record.id, destination_root(record)) / f"{e.filename}.part"
    try:
        size = part.stat().st_size
    except OSError:
        return 0
    return size if size <= e.archive_bytes else 0


def _destination(destination: str | None) -> Path:
    if destination is None:
        return databases_dir()
    writable = writable_locations()
    real = os.path.realpath(destination) if os.path.isabs(destination) else None
    for loc in writable:
        if real is not None and real == os.path.realpath(loc["path"]):
            if not loc["available"]:
                raise DatabaseFolderUnavailable(Path(loc["path"]))
            return Path(real)
    raise refusal("bad_destination", path=destination, allowed=", ".join(loc["host_path"] or loc["path"]
                                                                          for loc in writable))


def _folder(folder: str | None, default: str) -> str:
    text = (folder or default).strip().strip("/")
    parts = text.split("/")
    if not text or len(parts) > 4 or any(not _FOLDER_PART.fullmatch(p) or p in (".", "..") for p in parts):
        raise refusal("bad_folder")
    return text


@dataclass(frozen=True)
class DownloadPlan:
    entry: CatalogueEntry
    db_dir: str
    target_path: str
    host_target_path: str
    folder: str
    partial_bytes: int
    download_bytes: int
    required_bytes: int
    free_bytes: int
    reserve_bytes: int
    available_bytes: int
    enough: bool
    resume_record_id: str | None
    blocked_by: str | None
    blocked_code: str | None
    compatibility: kinds.Compatibility
    # MOB-suite: the NCBI taxonomy archive it also needs and whether the reference plasmids' FASTA is kept.
    extras: dict | None = None


def plan_download(db: Session, key: str, destination: str | None = None, folder: str | None = None,
                  keep_plasmid_fasta: bool = False, taxonomy_archive: str | None = None) -> DownloadPlan:
    """What a download would need: the bytes still to fetch (a partial download is resumed, where it was started),
    plus room for the unpacked database (the publisher's size, read in the larger unit) while the archive is still on
    disk, in the chosen database folder. MOB-suite also needs a dated NCBI taxonomy archive (its listing is read)."""
    from app.services import mobsuite_db

    e = entry(key)
    extras = mobsuite_db.plan_extras(keep_plasmid_fasta, taxonomy_archive) if e.kind == mobsuite_db.KIND else None
    resume = _resumable(db, e)
    if resume is not None and destination is None and folder is None:
        root, target = destination_root(resume), Path(resume.path or "")
        folder_text = target.relative_to(root).as_posix() if root in target.parents else e.install_dir
    else:
        root = _destination(destination)
        folder_text = _folder(folder, e.install_dir)
        target = root / folder_text
    partial = partial_bytes(resume, e) if resume and Path(resume.path or "") == target else 0
    download = e.archive_bytes - partial
    required = download + e.extracted_bytes_estimate + (extras["extra_bytes"] if extras else 0)
    free = free_bytes(root)
    reserve = get_settings().min_free_bytes
    available = max(0, free - reserve)
    compat = entry_compatibility(e)
    blocked, code = _blocker(db, e, resume, target, compat)
    return DownloadPlan(e, str(root), str(target), _shown(target), folder_text, partial, download, required, free,
                        reserve, available, required <= available,
                        resume.id if resume and Path(resume.path or "") == target else None, blocked, code, compat,
                        extras)


def _blocker(db: Session, e: CatalogueEntry, resume: ReferenceDatabase | None, target: Path,
             compat: kinds.Compatibility) -> tuple[str | None, str | None]:
    if compat.status == "incompatible":
        return (f"{e.name} {e.version} cannot be read by the installed {compat.params.get('tool')} "
                f"{compat.params.get('version')}", "incompatible")
    for r in _same_version(db, e.key, e.version):
        if r is not resume:
            return (f"{e.name} {e.version} is already known to ARVA (status '{r.status.value}', {_shown(r.path or '')});"
                    " delete that record first to install it again", "already_known")
    if resume is not None and Path(resume.path or "") != target:
        return (f"A partial download of {e.name} {e.version} is kept in {_shown(resume.path or '')}; resume it there or "
                "delete it first", "partial_elsewhere")
    if target.exists() and not (resume and resume.path == str(target)):
        return (f"{_shown(target)} already exists but ARVA has no record of it. Register it if it is a database, or "
                "choose another folder", "target_exists")
    if any(r.path and Path(r.path) in target.parents for r in db.scalars(select(ReferenceDatabase))):
        return f"{_shown(target)} lies inside another database's folder; choose another folder", "inside_database"
    return None, None


def _task_id() -> str:
    return f"arva-db-{new_uuid()}"


def _enqueue(record: ReferenceDatabase, func) -> None:
    jobs_service.get_queue().enqueue(func, record.id, job_id=record.task_id)


def start_download(db: Session, key: str, confirm_bytes: int, accept_licence: bool, destination: str | None = None,
                   folder: str | None = None, keep_plasmid_fasta: bool = False,
                   taxonomy_archive: str | None = None) -> ReferenceDatabase:
    """Queue the download of a catalogue database into the chosen database folder; the caller must repeat the
    archive size shown to the user and accept its licence (for MOB-suite, also name the NCBI taxonomy archive shown).
    A failed or cancelled download of the same version is resumed where it was."""
    from app.tasks.databases import run_database_download

    plan = plan_download(db, key, destination, folder, keep_plasmid_fasta, taxonomy_archive)
    if plan.extras is not None and taxonomy_archive != plan.extras["taxonomy"]["name"]:
        raise refusal("mobsuite_taxonomy_confirm", name=plan.extras["taxonomy"]["name"])
    e = plan.entry
    if confirm_bytes != e.archive_bytes:
        raise DatabaseError(f"confirm the download size: the archive is {e.archive_bytes:,} bytes, the request "
                            f"confirmed {confirm_bytes:,}")
    if not accept_licence:
        raise DatabaseError(f"the licence ({e.licence}) must be accepted before {e.name} is downloaded")
    if plan.blocked_by:
        raise DatabaseStateError(plan.blocked_by)
    if not plan.enough:
        raise DatabaseSpaceError(plan.required_bytes, plan.available_bytes, Path(plan.db_dir))
    record = db.get(ReferenceDatabase, plan.resume_record_id) if plan.resume_record_id else None
    if record is None:
        record = ReferenceDatabase(key=e.key, kind=e.kind, origin=DatabaseOrigin.download, log_text="")
        db.add(record)
    record.name, record.version, record.path = e.name, e.version, plan.target_path
    record.source_url, record.licence = e.source_url, e.licence
    record.status = DatabaseStatus.downloading
    record.error_message = record.error_detail = record.cancel_requested_at = None
    record.task_id = _task_id()
    record.details = {**(record.details or {}), "catalogue": catalogue_snapshot(e), "destination": plan.db_dir,
                      "confirmation": {"archive_bytes": confirm_bytes, "licence": e.licence, "at": now().isoformat()}}
    if plan.extras is not None:
        record.details["options"] = {"keep_plasmid_fasta": keep_plasmid_fasta}
        record.details["taxonomy"] = plan.extras["taxonomy"]
    record.progress = {"phase": "queued", "bytes_done": plan.partial_bytes, "bytes_total": e.archive_bytes}
    db.commit()
    _enqueue(record, run_database_download)
    db.refresh(record)
    return record


# --- A copy extracted from a package zip ------------------------------------------------------------------------

@dataclass(frozen=True)
class ExtractPlan:
    source: str
    host_source: str
    detection: detection.Detection
    db_dir: str
    target_path: str
    host_target_path: str
    folder: str
    required_bytes: int
    free_bytes: int
    reserve_bytes: int
    available_bytes: int
    enough: bool
    blocked_by: str | None


def plan_extract(db: Session, raw_path: str, destination: str | None = None, folder: str | None = None) -> ExtractPlan:
    """What extracting a copy of an NCBI Datasets package zip into a database folder needs (the zip's own sizes)."""
    path = resolve_registration_path(raw_path)
    d = next((x for x in detection.detect(path) if x.path_type == "zip"), None)
    if d is None:
        raise refusal("not_recognised", path=raw_path)
    root = _destination(destination)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-.") or "collection"
    folder_text = _folder(folder, f"reference-genomes/{stem}")
    target = root / folder_text
    zip_facts = d.facts["zip"]
    required = zip_facts["uncompressed_bytes"]
    free = free_bytes(root)
    reserve = get_settings().min_free_bytes
    available = max(0, free - reserve)
    blocked = next((p.text for p in d.problems if p.code == "zip_unsafe"), None)
    if blocked is None and target.exists():
        blocked = render(MESSAGES["target_exists"], {"path": _shown(target)})
    return ExtractPlan(str(path), _shown(path), d, str(root), str(target), _shown(target), folder_text, required, free,
                       reserve, available, required <= available, blocked)


def start_extract(db: Session, raw_path: str, confirm_bytes: int, collection_date: str | None,
                  destination: str | None = None, folder: str | None = None) -> ReferenceDatabase:
    from app.tasks.databases import run_database_extract

    plan = plan_extract(db, raw_path, destination, folder)
    day = rc.valid_date(collection_date)
    if day is None:
        raise refusal("date_needed")
    if confirm_bytes != plan.required_bytes:
        raise DatabaseError(f"confirm the size: the copy needs {plan.required_bytes:,} bytes, the request confirmed "
                            f"{confirm_bytes:,}")
    if plan.blocked_by:
        raise DatabaseStateError(plan.blocked_by)
    if not plan.enough:
        raise DatabaseSpaceError(plan.required_bytes, plan.available_bytes, Path(plan.db_dir))
    k = kinds.BY_KEY["reference_genomes"]
    record = ReferenceDatabase(
        key="reference_genomes", kind="reference_genomes", name=f"{k.name} (NCBI Datasets package)",
        path=plan.target_path, origin=DatabaseOrigin.extract, status=DatabaseStatus.extracting, log_text="",
        source_url=k.source_url, licence=k.licence, task_id=_task_id(),
        details={"destination": plan.db_dir, "source_zip": plan.source, "zip": plan.detection.facts["zip"],
                 "collection_date": day, "confirmation": {"bytes": confirm_bytes, "at": now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": plan.required_bytes},
    )
    db.add(record)
    db.commit()
    _enqueue(record, run_database_extract)
    db.refresh(record)
    return record


# --- Verification, defaults, cancellation, deletion -------------------------------------------------------------

def _readable(path: str) -> bool:
    from app.services.locations import folder_available

    try:
        return folder_available(path) or (os.path.isfile(path) and os.access(path, os.R_OK))
    except OSError:
        return False


def availability(record: ReferenceDatabase) -> tuple[bool, str | None]:
    """Whether an installed or registered database's folder (or file) can be read now, and if not why
    (disk_not_connected or folder_missing). Other states have no folder to check."""
    from app.services.locations import unavailable_reason

    if record.status not in (*USABLE, DatabaseStatus.failed) or not record.path:
        return True, None
    if _readable(record.path):
        return True, None
    return False, unavailable_reason(record.path)


def require_available(record: ReferenceDatabase) -> None:
    available, reason = availability(record)
    if not available:
        raise DatabaseUnavailableError(record, reason or "folder_missing")


def record_compatibility(record: ReferenceDatabase) -> kinds.Compatibility:
    details = record.details or {}
    facts = (details.get("detection") or {}).get("facts") or {}
    info = details.get("version_json") or facts.get("version_json")
    if record.kind == "amrfinderplus":
        info = {"database_format_version": facts.get("database_format_version")}
    if record.kind in ("vfdb", "plasmidfinder"):
        info = {"variant": (details.get("detection") or {}).get("variant")}
    return kinds.compatibility(record.kind, info, version=record.version)


def _get(db: Session, record_id: str, lock: bool = False) -> ReferenceDatabase:
    record = db.get(ReferenceDatabase, record_id, with_for_update=lock, populate_existing=lock)
    if record is None:
        raise LookupError(record_id)
    return record


def end_status(record: ReferenceDatabase) -> DatabaseStatus:
    """The status a stopped task leaves: a download or extraction ends cancelled; a verification returns to where it
    started."""
    if record.status is DatabaseStatus.verifying:
        return DatabaseStatus((record.progress or {}).get("return_status") or DatabaseStatus.cancelled.value)
    return DatabaseStatus.cancelled


def append_log(record: ReferenceDatabase, line: str) -> None:
    stamp = now().isoformat(timespec="seconds")
    record.log_text = ((record.log_text + "\n") if record.log_text else "") + f"[{stamp}] {line}"


def quick_verify(db: Session, record_id: str) -> ReferenceDatabase:
    """Check again, at once, the kind's files, their sizes and the version file; never reads the files' contents
    beyond the kind's marker and version files."""
    record = _get(db, record_id, lock=True)
    require_available(record)
    if record.status in BUSY:
        raise DatabaseStateError(f"this database is {record.status.value}; wait or cancel first")
    if record.status is DatabaseStatus.cancelled:
        raise DatabaseStateError("this database was never completely installed; download or register it again")
    recorded = (record.details or {}).get("detection") or {}
    found = detection.quick_check(record.kind, Path(record.path or ""), recorded, list_context())
    problem = None
    if found is None:
        problem = f"ARVA no longer recognises it as a {kinds.BY_KEY[record.kind].name}"
    elif blocking := [p.text for p in found.problems if p.blocking]:
        problem = "; ".join(blocking)
    elif record.version_source is VersionSource.file and found.version != record.version:
        problem = f"its version file now says {found.version}; it was recorded as {record.version}"
    elif record.kind == "reference_genomes" and \
            (found.facts.get("collection") or {}).get("fingerprint") != (record.details or {}).get(
                "collection", {}).get("fingerprint"):
        problem = "its genomes are not the ones recorded at registration (the accession fingerprint changed)"
    elif found.facts["quick"]["changed"] or found.facts["quick"]["missing"]:
        q = found.facts["quick"]
        problem = (f"{len(q['changed'])} file(s) changed size and {len(q['missing'])} missing since registration "
                   f"({', '.join((q['changed'] + q['missing'])[:5])})")
    stamp = now()
    record.details = {**(record.details or {}), "last_quick_check": {"at": stamp.isoformat(), "ok": problem is None}}
    if problem:
        record.status = DatabaseStatus.failed
        record.error_message = f"Quick verification failed: {problem}"
        record.error_detail = {"code": "quick_failed", "params": {"detail": problem}}
        append_log(record, record.error_message)
    else:
        record.status = DatabaseStatus.installed if record.origin in OWNED else DatabaseStatus.registered
        record.error_message = record.error_detail = None
        record.verified_at = stamp
        record.verification_level = record.verification_level or "quick"
        append_log(record, "Quick verification passed: the kind's files are there with the recorded sizes"
                           + (" and the version file says the same" if record.version_source is VersionSource.file
                              else ""))
    db.flush()
    ensure_default(db, record.kind)
    db.commit()
    db.refresh(record)
    return record


def start_verify(db: Session, record_id: str, level: str = "full") -> ReferenceDatabase:
    from app.tasks.databases import run_database_verify

    if level == "quick":
        return quick_verify(db, record_id)
    record = _get(db, record_id, lock=True)
    require_available(record)
    if record.status in BUSY:
        raise DatabaseStateError(f"this database is {record.status.value}; wait or cancel first")
    if record.status is DatabaseStatus.cancelled and not record.checksum:
        raise DatabaseStateError("this database was never completely installed; download or register it again")
    record.progress = {"phase": "queued", "return_status": record.status.value}
    record.status = DatabaseStatus.verifying
    record.cancel_requested_at = None
    record.task_id = _task_id()
    db.commit()
    _enqueue(record, run_database_verify)
    db.refresh(record)
    return record


def usable_now(record: ReferenceDatabase) -> bool:
    return record.status in USABLE and availability(record)[0] and \
        record_compatibility(record).status != "incompatible"


def ensure_default(db: Session, kind: str) -> None:
    """Keep one default per kind: when none of a kind's usable databases is the default, the most recently verified
    becomes it. An explicit choice is never replaced while that database is usable."""
    rows = list(db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == kind)
                           .order_by(ReferenceDatabase.verified_at.desc().nulls_last(),
                                     ReferenceDatabase.created_at.desc())))
    current = [r for r in rows if r.is_default]
    if any(r.status in USABLE for r in current):
        return
    for r in current:
        r.is_default = False
    db.flush()
    pick = next((r for r in rows if r.status in USABLE and record_compatibility(r).status != "incompatible"), None)
    if pick is not None:
        pick.is_default = True
        db.flush()


def set_default(db: Session, record_id: str) -> ReferenceDatabase:
    record = _get(db, record_id, lock=True)
    if record.status not in USABLE:
        raise DatabaseStateError("", "not_usable", name=record.name, status=record.status.value)
    compat = record_compatibility(record)
    if compat.status == "incompatible":
        raise DatabaseStateError("", "incompatible", name=record.name, version=record.version or "?",
                                 tool=compat.params.get("tool", "?"), tool_version=compat.params.get("version", "?"),
                                 schema=compat.params.get("schema", "?"))
    db.execute(update(ReferenceDatabase).where(ReferenceDatabase.kind == record.kind,
                                               ReferenceDatabase.id != record.id).values(is_default=False))
    db.flush()
    record.is_default = True
    append_log(record, "Made the default database of its kind")
    db.commit()
    db.refresh(record)
    return record


def default_for(db: Session, kind: str) -> ReferenceDatabase | None:
    """The database analyses of this kind use when none is chosen: the default, if it can be used now."""
    record = db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.kind == kind, ReferenceDatabase.is_default))
    return record if record is not None and usable_now(record) else None


def cancel(db: Session, record_id: str) -> ReferenceDatabase:
    """Stop a download, extraction or verification. A task no worker runs is stopped at once; a running one stops
    within a second or two. A cancelled download keeps its partial file, so downloading again resumes it."""
    record = _get(db, record_id, lock=True)
    if record.status not in BUSY:
        raise DatabaseStateError(f"nothing to cancel: this database is {record.status.value}")
    if record.cancel_requested_at is None:
        record.cancel_requested_at = now()
    state = jobs_service.task_status(record.task_id) if record.task_id else "missing"
    if state in _WAITING or state in _NOT_EXECUTING:
        if state in _WAITING:
            jobs_service.cancel_task(record.task_id)
        if record.status is not DatabaseStatus.verifying:
            shutil.rmtree(staging_dir(record.id, destination_root(record)), ignore_errors=True)
        append_log(record, f"Cancelled at the user's request; no worker was running it (task queue: {state})")
        record.status = end_status(record)
        record.progress = {**(record.progress or {}), "phase": "cancelled"}
    db.commit()
    db.refresh(record)
    return record


def jobs_using(db: Session, record_id: str) -> int:
    return db.scalar(select(func.count()).select_from(AnalysisJob).where(
        AnalysisJob.reference_database_id == record_id, AnalysisJob.status.in_(jobs_service.ACTIVE))) or 0


def _owned_folder(record: ReferenceDatabase) -> Path | None:
    """The folder of a database ARVA installed or extracted, only if it lies strictly inside the database folder it
    was put in."""
    if not record.path:
        return None
    p = Path(record.path)
    root = Path(os.path.realpath(destination_root(record)))
    if p.is_symlink() or root not in Path(os.path.realpath(p)).parents:
        return None
    return p


def delete(db: Session, record_id: str) -> None:
    """Delete an installed or extracted database's files (only inside its database folder) and its record, or only
    the record of a registered folder. Refused while it is busy or a queued or running job uses it."""
    record = _get(db, record_id, lock=True)
    if record.status in BUSY:
        raise DatabaseStateError(f"this database is {record.status.value}; cancel that first")
    if n := jobs_using(db, record.id):
        raise DatabaseStateError(f"{n} queued or running job(s) use this database; wait for them or cancel them")
    if record.origin is DatabaseOrigin.bundled:
        raise DatabaseStateError("", "bundled_read_only", name=record.name,
                                 tool=kinds.BY_KEY[record.kind].tools[0].tool)
    kind = record.kind
    if record.origin in OWNED:
        # Deleting the record of an installed database whose disk is missing would leave its files behind unseen.
        require_available(record)
        root = destination_root(record)
        if (folder := _owned_folder(record)) is not None:
            if folder.exists():
                shutil.rmtree(folder)
            try:
                if folder.parent != root:
                    folder.parent.rmdir()
            except OSError:
                pass
        for d in (downloads_dir(record.id, root), staging_dir(record.id, root)):
            shutil.rmtree(d, ignore_errors=True)
    db.delete(record)
    db.flush()
    ensure_default(db, kind)
    db.commit()


# --- Disk usage and use by jobs ---------------------------------------------------------------------------------

def usage(db: Session) -> dict:
    root = databases_dir()
    total = shutil.disk_usage(root)
    records = list(db.scalars(select(ReferenceDatabase)))
    installed = sum(r.size_bytes or 0 for r in records if r.origin in OWNED and r.size_bytes)
    registered = sum(r.size_bytes or 0 for r in records if r.origin is DatabaseOrigin.register and r.size_bytes)
    return {
        "db_dir": str(root), "host_db_dir": _shown(root), "free_bytes": free_bytes(root), "total_bytes": total.total,
        "reserve_bytes": get_settings().min_free_bytes, "installed_bytes": installed, "registered_bytes": registered,
        "partial_bytes": tree_bytes(root / DOWNLOADS), "staging_bytes": tree_bytes(root / STAGING),
    }


def usable(db: Session, key: str) -> ReferenceDatabase | None:
    """The most recently verified installed or registered database of a catalogue key."""
    return db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.key == key,
                                                      ReferenceDatabase.status.in_(USABLE))
                      .order_by(ReferenceDatabase.verified_at.desc().nulls_last())).first()


def record_use(job: AnalysisJob, record: ReferenceDatabase) -> None:
    """Record on a job the database it reads: kind, key, name, version and how the version was known, the content
    checksum when the full verification computed one, and the path (all kept after the database's deletion)."""
    if record.status not in USABLE:
        raise DatabaseStateError(f"{record.name} cannot be used: it is {record.status.value}")
    require_available(record)
    job.reference_database_id = record.id
    job.database_kind, job.database_key, job.database_name = record.kind, record.key, record.name
    job.database_version = record.version
    job.database_version_source = record.version_source.value if record.version_source else None
    job.database_checksum, job.database_path = record.checksum, record.path
