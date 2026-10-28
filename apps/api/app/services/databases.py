"""Database Manager (spec §30): install, register, verify and delete reference databases.

Nothing is downloaded without an explicit confirmation of the archive's size and licence, and only from the
catalogue's official URL. Downloads and verifications run in the worker; this module validates requests, plans the
disk space and records the state. Databases ARVA installed live in ARVA_DB_DIR and may be deleted by ARVA; a
registered folder is only read and never deleted.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import AnalysisJob, DatabaseOrigin, DatabaseStatus, ReferenceDatabase
from app.services import jobs as jobs_service
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
BUSY = (DatabaseStatus.downloading, DatabaseStatus.verifying)
USABLE = (DatabaseStatus.installed, DatabaseStatus.registered)
_MAX_PATH = 4096
# Task-queue states of a task no worker executes (yet, or any more).
_WAITING = {"queued", "deferred", "scheduled"}
_NOT_EXECUTING = {"finished", "failed", "stopped", "canceled", "missing"}


class DatabaseError(ValueError):
    """The request is invalid (400)."""


class DatabaseStateError(RuntimeError):
    """The database's state does not allow the request (409)."""


class DatabaseSpaceError(ValueError):
    """Not enough free space in ARVA_DB_DIR (507)."""

    def __init__(self, needed: int, available: int, db_dir: Path):
        self.needed, self.available = needed, available
        super().__init__(f"Not enough free space in the database folder {db_dir}: {fmt_bytes(needed)} ({needed:,} "
                         f"bytes) needed but only {fmt_bytes(available)} can be used (free space minus the "
                         "ARVA_MIN_FREE_BYTES reserve)")


def now() -> datetime:
    return datetime.now(UTC)


def databases_dir() -> Path:
    root = get_settings().databases_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def downloads_dir(record_id: str) -> Path:
    return databases_dir() / DOWNLOADS / record_id


def staging_dir(record_id: str) -> Path:
    return databases_dir() / STAGING / record_id


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


# --- Catalogue and plans ----------------------------------------------------------------------------------------

def catalogue_snapshot(e: CatalogueEntry) -> dict:
    return {k: v for k, v in asdict(e).items() if v not in (None, (), {})}


def _same_version(db: Session, key: str, version: str | None) -> list[ReferenceDatabase]:
    return list(db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.key == key,
                                                           ReferenceDatabase.version == version)))


def _resumable(db: Session, e: CatalogueEntry) -> ReferenceDatabase | None:
    return next((r for r in _same_version(db, e.key, e.version) if r.origin is DatabaseOrigin.download
                 and r.status in (DatabaseStatus.failed, DatabaseStatus.cancelled)), None)


def partial_bytes(record_id: str, e: CatalogueEntry) -> int:
    part = downloads_dir(record_id) / f"{e.filename}.part"
    try:
        size = part.stat().st_size
    except OSError:
        return 0
    return size if size <= (e.archive_bytes or 0) else 0


@dataclass(frozen=True)
class DownloadPlan:
    entry: CatalogueEntry
    db_dir: str
    target_path: str
    partial_bytes: int
    download_bytes: int
    required_bytes: int
    free_bytes: int
    reserve_bytes: int
    available_bytes: int
    enough: bool
    resume_record_id: str | None
    blocked_by: str | None


def plan_download(db: Session, key: str) -> DownloadPlan:
    """What a download would need: the bytes still to fetch (a partial download is resumed), plus room for the
    unpacked database (the publisher's size, read in the larger unit) while the archive is still on disk."""
    e = entry(key)
    if e.status != "available":
        raise DatabaseError(f"{e.name} is planned: ARVA cannot install it yet")
    root = databases_dir()
    resume = _resumable(db, e)
    partial = partial_bytes(resume.id, e) if resume else 0
    download = (e.archive_bytes or 0) - partial
    required = download + (e.extracted_bytes_estimate or 0)
    free = free_bytes(root)
    reserve = get_settings().min_free_bytes
    available = max(0, free - reserve)
    return DownloadPlan(e, str(root), str(root / e.install_dir), partial, download, required, free, reserve, available,
                        required <= available, resume.id if resume else None, _blocker(db, e, resume))


def _blocker(db: Session, e: CatalogueEntry, resume: ReferenceDatabase | None) -> str | None:
    for r in _same_version(db, e.key, e.version):
        if r is not resume:
            return (f"{e.name} {e.version} is already known to ARVA (status '{r.status.value}', {r.path}); delete "
                    "that record first to install it again")
    target = databases_dir() / e.install_dir
    if target.exists() and not (resume and resume.path == str(target)):
        return (f"{target} already exists but ARVA has no record of it. Register it if it is a database, or remove "
                "it yourself")
    return None


def _task_id() -> str:
    return f"arva-db-{new_uuid()}"


def _enqueue(record: ReferenceDatabase, func) -> None:
    jobs_service.get_queue().enqueue(func, record.id, job_id=record.task_id)


def start_download(db: Session, key: str, confirm_bytes: int, accept_licence: bool) -> ReferenceDatabase:
    """Queue the download of a catalogue database; the caller must repeat the archive size shown to the user and
    accept its licence. A failed or cancelled download of the same version is resumed."""
    from app.tasks.databases import run_database_download

    plan = plan_download(db, key)
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
        record = ReferenceDatabase(key=e.key, origin=DatabaseOrigin.download, log_text="")
        db.add(record)
    record.name, record.version, record.path = e.name, e.version, plan.target_path
    record.source_url, record.licence = e.source_url, e.licence
    record.status = DatabaseStatus.downloading
    record.error_message = record.cancel_requested_at = None
    record.task_id = _task_id()
    record.details = {**(record.details or {}), "catalogue": catalogue_snapshot(e),
                      "confirmation": {"archive_bytes": confirm_bytes, "licence": e.licence, "at": now().isoformat()}}
    record.progress = {"phase": "queued", "bytes_done": plan.partial_bytes, "bytes_total": e.archive_bytes}
    db.commit()
    _enqueue(record, run_database_download)
    db.refresh(record)
    return record


# --- Registration -----------------------------------------------------------------------------------------------

def _allowed_roots() -> list[Path]:
    return [databases_dir(), *(Path(os.path.realpath(p)) for p in get_settings().import_roots)]


def resolve_registration_path(raw: str) -> Path:
    if not raw or len(raw) > _MAX_PATH or "\x00" in raw or not os.path.isabs(raw):
        raise DatabaseError("give the absolute path of the database folder")
    path = Path(os.path.realpath(raw))
    roots = _allowed_roots()
    if not any(path == r or r in path.parents for r in roots):
        raise DatabaseError(f"{path} is outside the folders ARVA may read databases from: "
                            f"{', '.join(str(r) for r in roots)} (ARVA_DB_DIR and ARVA_IMPORT_ROOTS)")
    internal = databases_dir()
    if any(path == internal / d or internal / d in path.parents for d in (DOWNLOADS, STAGING)):
        raise DatabaseError("that folder holds ARVA's partial downloads")
    if not path.is_dir():
        raise DatabaseError(f"{path} is not a folder")
    return path


def register(db: Session, raw_path: str) -> ReferenceDatabase:
    """Record an existing Bakta database folder after Bakta's own checks; the worker then computes the checksum of
    every file (the manifest later verifications compare with). The folder is never modified."""
    from app.tasks.databases import run_database_verify

    path = resolve_registration_path(raw_path)
    info = check_bakta_dir(path)
    if db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.path == str(path))) is not None:
        raise DatabaseStateError(f"{path} is already registered or installed")
    e = bakta_entry_for(info["type"])
    if e is None:
        raise DatabaseError(f"no catalogue entry for Bakta databases of type {info['type']!r}")
    version = bakta_version(info)
    note = None if version == e.version else (f"Version {version} differs from the catalogue's {e.version}; the "
                                              "catalogue's facts (size, checksum, licence) describe that version only.")
    record = ReferenceDatabase(
        key=e.key, name=e.name, version=version, path=str(path), source_url=e.source_url if note is None else None,
        licence=e.licence if note is None else None, status=DatabaseStatus.verifying, origin=DatabaseOrigin.register,
        notes=note, log_text="", task_id=_task_id(),
        details={"version_json": info, "catalogue": catalogue_snapshot(e) if note is None else None,
                 "published_checksum_comparable": False},
        progress={"phase": "queued", "return_status": DatabaseStatus.cancelled.value},
    )
    db.add(record)
    db.commit()
    _enqueue(record, run_database_verify)
    db.refresh(record)
    return record


# --- Verification, cancellation, deletion -----------------------------------------------------------------------

def start_verify(db: Session, record_id: str) -> ReferenceDatabase:
    from app.tasks.databases import run_database_verify

    record = _get(db, record_id, lock=True)
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


def _get(db: Session, record_id: str, lock: bool = False) -> ReferenceDatabase:
    record = db.get(ReferenceDatabase, record_id, with_for_update=lock, populate_existing=lock)
    if record is None:
        raise LookupError(record_id)
    return record


def end_status(record: ReferenceDatabase) -> DatabaseStatus:
    """The status a stopped task leaves: a download ends cancelled; a verification returns to where it started."""
    if record.status is DatabaseStatus.verifying:
        return DatabaseStatus((record.progress or {}).get("return_status") or DatabaseStatus.cancelled.value)
    return DatabaseStatus.cancelled


def append_log(record: ReferenceDatabase, line: str) -> None:
    stamp = now().isoformat(timespec="seconds")
    record.log_text = ((record.log_text + "\n") if record.log_text else "") + f"[{stamp}] {line}"


def cancel(db: Session, record_id: str) -> ReferenceDatabase:
    """Stop a download or verification. A task no worker runs is stopped at once; a running one stops within a
    second or two. A cancelled download keeps its partial file, so downloading again resumes it."""
    record = _get(db, record_id, lock=True)
    if record.status not in BUSY:
        raise DatabaseStateError(f"nothing to cancel: this database is {record.status.value}")
    if record.cancel_requested_at is None:
        record.cancel_requested_at = now()
    state = jobs_service.task_status(record.task_id) if record.task_id else "missing"
    if state in _WAITING or state in _NOT_EXECUTING:
        if state in _WAITING:
            jobs_service.cancel_task(record.task_id)
        shutil.rmtree(staging_dir(record.id), ignore_errors=True)
        append_log(record, f"Cancelled at the user's request; no worker was running it (task queue: {state})")
        record.status = end_status(record)
        record.progress = {**(record.progress or {}), "phase": "cancelled"}
    db.commit()
    db.refresh(record)
    return record


def jobs_using(db: Session, record_id: str) -> int:
    return db.scalar(select(func.count()).select_from(AnalysisJob).where(
        AnalysisJob.reference_database_id == record_id, AnalysisJob.status.in_(jobs_service.ACTIVE))) or 0


def _owned_folder(path: str | None) -> Path | None:
    """The folder of an ARVA-installed database, only if it lies strictly inside ARVA_DB_DIR."""
    if not path:
        return None
    p = Path(path)
    root = databases_dir()
    if p.is_symlink() or root not in Path(os.path.realpath(p)).parents:
        return None
    return p


def delete(db: Session, record_id: str) -> None:
    """Delete an installed database's files (only inside ARVA_DB_DIR) and its record, or only the record of a
    registered folder. Refused while it is busy or a queued or running job uses it."""
    record = _get(db, record_id, lock=True)
    if record.status in BUSY:
        raise DatabaseStateError(f"this database is {record.status.value}; cancel that first")
    if n := jobs_using(db, record.id):
        raise DatabaseStateError(f"{n} queued or running job(s) use this database; wait for them or cancel them")
    if record.origin is DatabaseOrigin.download:
        if (folder := _owned_folder(record.path)) is not None:
            if folder.exists():
                shutil.rmtree(folder)
            try:
                folder.parent.rmdir()
            except OSError:
                pass
        for d in (downloads_dir(record.id), staging_dir(record.id)):
            shutil.rmtree(d, ignore_errors=True)
    db.delete(record)
    db.commit()


# --- Disk usage and use by jobs ---------------------------------------------------------------------------------

def usage(db: Session) -> dict:
    root = databases_dir()
    total = shutil.disk_usage(root)
    records = list(db.scalars(select(ReferenceDatabase)))
    installed = sum(r.size_bytes or 0 for r in records if r.origin is DatabaseOrigin.download and r.size_bytes)
    registered = sum(r.size_bytes or 0 for r in records if r.origin is DatabaseOrigin.register and r.size_bytes)
    return {
        "db_dir": str(root), "free_bytes": free_bytes(root), "total_bytes": total.total,
        "reserve_bytes": get_settings().min_free_bytes, "installed_bytes": installed, "registered_bytes": registered,
        "partial_bytes": tree_bytes(root / DOWNLOADS), "staging_bytes": tree_bytes(root / STAGING),
    }


def usable(db: Session, key: str) -> ReferenceDatabase | None:
    """The most recently verified installed or registered database of a catalogue key."""
    return db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.key == key,
                                                      ReferenceDatabase.status.in_(USABLE))
                      .order_by(ReferenceDatabase.verified_at.desc().nulls_last())).first()


def record_use(job: AnalysisJob, record: ReferenceDatabase) -> None:
    """Record on a job the database it reads: key, name, version and content checksum (kept after deletion)."""
    if record.status not in USABLE or not record.checksum:
        raise DatabaseStateError(f"{record.name} cannot be used: it is {record.status.value}")
    job.reference_database_id = record.id
    job.database_key, job.database_name = record.key, record.name
    job.database_version, job.database_checksum = record.version, record.checksum

