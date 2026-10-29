"""AMRFinderPlus databases: NCBI's dated releases ARVA can download and index, and the copy inside a Bakta database.

NCBI publishes one folder per software minor version and release (database/<minor>/<YYYY-MM-DD.N>/, checked
2026-10-29), each a set of separate files without checksums. ARVA lists the releases for the installed
AMRFinderPlus, shows the files amrfinder_update would fetch (amrfinder_update.cpp: a fixed list, the AMR_DNA pair of
every taxgroup with nucleotide reference genes, changes.txt) and their sizes from the listing, and downloads them only
after the user confirms; the worker (app.tasks.amrfinder_db) records each file's size and SHA-256 and indexes the
folder with amrfinder_index. ARVA never runs amrfinder -u or amrfinder_update, which fetch the latest release.

A Bakta database holds its own copy (amrfinderplus-db/<version>, the one Bakta's AMR expert system reads). When the
installed AMRFinderPlus accepts that copy and it has the files ARVA's searches read, ARVA registers it read-only so AMR
detection can use it too; otherwise the copy is shown with the reason and not offered: AMRFinderPlus 4.2.7 needs data
2025-09-22.2 or later (Bakta's light database 6.0 has 2024-12-18.1), and Bakta's archives keep only the protein BLAST
index and HMMs of a release, while the nucleotide and combined searches run tblastn with AMRProt.fa itself as the
query (amrfinder.cpp).
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arva_tools.amrfinderplus import DATA_VERSION, RELEASE_FILES, RELEASE_LAST, data_version_key
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.messages import render
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase, VersionSource
from app.services import database_detect as detection
from app.services import database_kinds as kinds
from app.services import databases as dbs

KIND = "amrfinderplus"
KEY = "amrfinderplus"
BAKTA_COPY_KEY = "amrfinderplus-bakta"
LISTING_LIMIT = 1 << 20
# Indexed size / downloaded size of release 2026-08-07.1 (128 MB -> 241 MB, measured 2026-10-29), rounded up.
INDEX_FACTOR = 2.0
_ROW = re.compile(r'<a href="([A-Za-z0-9._-]+/?)">[^<]*</a>\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+(\S+)')
_SIZE = re.compile(r"(\d+(?:\.\d+)?)([KMG]?)")
_UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}
_DNA = re.compile(r"AMR_DNA-[A-Za-z_]+\.(?:fa|tsv)")

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "amr_db_tool_missing": "AMRFinderPlus is not installed, so ARVA cannot tell which releases it reads or index one.",
    "amr_db_unreachable": "NCBI's AMRFinderPlus folder could not be read ({detail}).",
    "amr_db_unknown_release": "NCBI lists no release {version} for AMRFinderPlus {minor}.",
    "amr_db_incomplete_release": "Release {version} lacks files AMRFinderPlus needs: {files}.",
    "amr_db_incompatible": "AMRFinderPlus {tool_version} cannot read release {version}: {reason}.",
    "amr_db_confirm": "Confirm the release, its size ({size}) and NCBI's terms first.",
    "amr_db_known": "AMRFinderPlus database {version} is already known to ARVA ({path}); delete that record first.",
}


class AmrDatabaseError(dbs.DatabaseError):
    def __init__(self, code: str, upstream: bool = False, **params):
        super().__init__(render(MESSAGES[code], params), code, **params)
        self.upstream = upstream


def base_url() -> str:
    url = get_settings().amrfinder_db_url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise AmrDatabaseError("amr_db_unreachable", True, detail=f"{url} is not an https address")
    return url


def software_minor(version: str) -> str:
    parts = version.split(".")
    return ".".join(parts[:2])


def _tool() -> tuple[str, str]:
    from arva_tools.registry import detect

    d = detect("amrfinderplus", refresh=True)
    if d.path is None or d.version is None:
        raise AmrDatabaseError("amr_db_tool_missing")
    return d.path, d.version


def _read(url: str) -> str:
    from app.tasks.databases import TaskFailure, _open

    try:
        with _open(url, 0) as resp:
            return resp.read(LISTING_LIMIT).decode("utf-8", "replace")
    except TaskFailure as exc:
        raise AmrDatabaseError("amr_db_unreachable", True, detail=str(exc)) from exc
    except OSError as exc:
        raise AmrDatabaseError("amr_db_unreachable", True, detail=str(getattr(exc, "reason", exc))) from exc


def parse_size(text: str) -> int | None:
    m = _SIZE.fullmatch(text)
    return int(float(m.group(1)) * _UNITS[m.group(2)]) if m else None


def parse_listing(text: str) -> list[dict[str, Any]]:
    """The entries of an Apache folder listing (NCBI's FTP over HTTPS): name, folder or file, modification time and
    the size as the listing rounds it (K, M and G of 1024)."""
    out = []
    for m in _ROW.finditer(html.unescape(text)):
        name = m.group(1)
        folder = name.endswith("/")
        out.append({"name": name.rstrip("/"), "folder": folder, "modified": m.group(2),
                    "approx_bytes": None if folder else parse_size(m.group(3))})
    return out


def releases() -> dict[str, Any]:
    """The dated releases NCBI lists for the installed AMRFinderPlus's minor version, newest first, each with whether
    this AMRFinderPlus reads it."""
    from arva_tools.amrfinderplus import data_compatible

    _exe, version = _tool()
    minor = software_minor(version)
    url = f"{base_url()}/{minor}/"
    rows = [r for r in parse_listing(_read(url)) if r["folder"] and DATA_VERSION.fullmatch(r["name"])]
    rows.sort(key=lambda r: data_version_key(r["name"]), reverse=True)
    return {"tool_version": version, "minor": minor, "url": url,
            "releases": [{"version": r["name"], "modified": r["modified"],
                          "compatibility": data_compatible(version, r["name"], None)["status"]} for r in rows]}


def release_files(listing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The files amrfinder_update fetches from a release folder, in its order, and the required ones it lacks."""
    files = {r["name"]: r for r in listing if not r["folder"]}
    dna = sorted(n for n in files if _DNA.fullmatch(n))
    wanted = [*RELEASE_FILES, *dna, RELEASE_LAST]
    missing = [n for n in (*RELEASE_FILES, RELEASE_LAST) if n not in files]
    return [{"name": n, "approx_bytes": files[n]["approx_bytes"], "modified": files[n]["modified"]}
            for n in wanted if n in files], missing


def _blocker(db: Session, version: str, target: Path) -> tuple[str | None, str | None]:
    for r in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == KIND,
                                                        ReferenceDatabase.version == version)):
        if r.origin is DatabaseOrigin.download and r.status not in (DatabaseStatus.failed, DatabaseStatus.cancelled):
            return render(MESSAGES["amr_db_known"], {"version": version, "path": dbs._shown(r.path or "")}), \
                "already_known"
    if target.exists():
        return (f"{dbs._shown(target)} already exists but ARVA has no record of it. Register it if it is a database, "
                "or choose another folder", "target_exists")
    if any(r.path and Path(r.path) in target.parents for r in db.scalars(select(ReferenceDatabase))):
        return f"{dbs._shown(target)} lies inside another database's folder; choose another folder", "inside_database"
    return None, None


def plan(db: Session, version: str, destination: str | None = None, folder: str | None = None) -> dict[str, Any]:
    """What downloading release `version` would fetch: each file from NCBI's listing (sizes as the listing rounds
    them), the folder it would be installed in, the space needed with the indexes, and whether this AMRFinderPlus
    reads it. Only NCBI's two folder listings are read."""
    from arva_tools.amrfinderplus import data_compatible

    if not DATA_VERSION.fullmatch(version or ""):
        raise AmrDatabaseError("amr_db_unknown_release", version=str(version)[:40], minor="?")
    _exe, tool_version = _tool()
    minor = software_minor(tool_version)
    url = f"{base_url()}/{minor}/{version}/"
    listing = parse_listing(_read(url))
    if not listing:
        raise AmrDatabaseError("amr_db_unknown_release", version=version, minor=minor)
    files, missing = release_files(listing)
    download = sum(f["approx_bytes"] or 0 for f in files)
    root = dbs._destination(destination)
    folder_text = dbs._folder(folder, f"amrfinderplus/{version}")
    target = root / folder_text
    required = int(download * INDEX_FACTOR)
    free = dbs.free_bytes(root)
    available = max(0, free - get_settings().min_free_bytes)
    blocked, code = _blocker(db, version, target)
    compat = data_compatible(tool_version, version, None)
    k = kinds.BY_KEY[KIND]
    return {"version": version, "minor": minor, "tool_version": tool_version, "url": url, "files": files,
            "missing": missing, "download_bytes": download, "required_bytes": required, "db_dir": str(root),
            "folder": folder_text, "target_path": str(target), "host_target_path": dbs._shown(target),
            "free_bytes": free, "available_bytes": available, "enough": required <= available,
            "blocked_by": blocked, "blocked_code": code, "compatibility": compat["status"],
            "needs_data": compat["needs_data"], "licence": k.licence, "checksums_published": False,
            "index_command": "amrfinder_index <folder> --blast_bin <env>/bin --hmmer_bin <env>/bin"}


def start(db: Session, version: str, confirm_bytes: int, accept_terms: bool, destination: str | None = None,
          folder: str | None = None) -> ReferenceDatabase:
    """Plan again (NCBI's folder may have changed), check the confirmation and queue the download and indexing."""
    from app.tasks.amrfinder_db import run_amrfinder_download

    p = plan(db, version, destination, folder)
    if confirm_bytes != p["download_bytes"] or not accept_terms:
        raise AmrDatabaseError("amr_db_confirm", size=f"{p['download_bytes']:,} bytes")
    if p["missing"]:
        raise AmrDatabaseError("amr_db_incomplete_release", version=version, files=", ".join(p["missing"]))
    if p["compatibility"] in ("data_too_old", "software_too_old"):
        raise AmrDatabaseError("amr_db_incompatible", tool_version=p["tool_version"], version=version,
                               reason=f"it needs data {p['needs_data']} or later")
    if p["blocked_by"]:
        raise dbs.DatabaseStateError(p["blocked_by"])
    if not p["enough"]:
        raise dbs.DatabaseSpaceError(p["required_bytes"], p["available_bytes"], Path(p["db_dir"]))
    k = kinds.BY_KEY[KIND]
    record = ReferenceDatabase(
        key=KEY, kind=KIND, name="AMRFinderPlus database", version=version, path=p["target_path"],
        origin=DatabaseOrigin.download, status=DatabaseStatus.downloading, log_text="", source_url=p["url"],
        licence=k.licence, task_id=dbs._task_id(),
        details={"destination": p["db_dir"],
                 "release": {k2: p[k2] for k2 in ("url", "minor", "tool_version", "files", "download_bytes")},
                 "confirmation": {"download_bytes": confirm_bytes, "terms": k.licence, "at": dbs.now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": p["download_bytes"]},
    )
    db.add(record)
    db.commit()
    dbs._enqueue(record, run_amrfinder_download)
    db.refresh(record)
    return record


# --- The copy inside a Bakta database ---------------------------------------------------------------------------

def copy_compatibility(found: detection.Detection) -> kinds.Compatibility:
    return kinds.compatibility(KIND, {"database_format_version": found.facts.get("database_format_version")},
                               version=found.version)


def bakta_copies(db: Session) -> list[dict[str, Any]]:
    """The AMRFinderPlus data inside each usable Bakta database, with whether the installed AMRFinderPlus reads them;
    a compatible copy is registered read-only (once) so that AMR detection can use it."""
    out = []
    for b in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == "bakta",
                                                        ReferenceDatabase.status.in_(dbs.USABLE))):
        latest = Path(b.path or "") / "amrfinderplus-db" / "latest"
        real = Path(os.path.realpath(latest))
        if not latest.is_dir() or not real.is_relative_to(os.path.realpath(b.path or "")):
            continue
        found = next((d for d in detection.detect(real) if d.kind == KIND), None)
        if found is None or found.version is None:
            continue
        compat = copy_compatibility(found)
        complete = found.variant == "release"
        record = db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.path == str(real)))
        if record is None and compat.status == "compatible" and complete and found.ok:
            record = _register_copy(db, b, real, found)
        out.append({"bakta_id": b.id, "bakta_name": b.name, "bakta_version": b.version, "path": str(real),
                    "host_path": dbs._shown(real), "version": found.version, "variant": found.variant,
                    "database_format": found.facts.get("database_format_version"), "complete": complete,
                    "compatibility": asdict(compat), "record_id": record.id if record else None})
    return out


def _register_copy(db: Session, bakta: ReferenceDatabase, path: Path, found: detection.Detection) -> ReferenceDatabase:
    k = kinds.BY_KEY[KIND]
    stamp = dbs.now()
    record = ReferenceDatabase(
        key=BAKTA_COPY_KEY, kind=KIND, name=f"AMRFinderPlus data inside {bakta.name} {bakta.version}",
        version=found.version, version_source=VersionSource.file, path=str(path), source_url=k.source_url,
        licence=k.licence, status=DatabaseStatus.registered, origin=DatabaseOrigin.register,
        verification_level="quick", installed_at=stamp, verified_at=stamp, log_text="",
        size_bytes=dbs._detected_bytes(found),
        details={"detection": dbs._stored_detection(found), "inside_bakta": {"id": bakta.id, "name": bakta.name,
                                                                              "version": bakta.version}},
    )
    dbs.append_log(record, f"Found inside the Bakta database {bakta.name} {bakta.version} ({dbs._shown(path)}): "
                           f"AMRFinderPlus data {found.version}, format {found.facts.get('database_format_version')}, "
                           "read by the installed AMRFinderPlus. ARVA only reads this folder")
    db.add(record)
    db.flush()
    dbs.ensure_default(db, KIND)
    db.commit()
    db.refresh(record)
    return record
