"""VFDB's full dataset (set B) as an ABRicate database for the virulence screen, downloaded only after the user confirms
it, or built from a VFDB_setB_nt.fas(.gz) the user already has.

What VFDB publishes (checked 2026-11-06, database_kinds.py kind vfdb): its download page links the nucleotides of the
core dataset (Down/VFDB_setA_nt.fas.gz, "DNA sequences of core dataset": genes of experimentally verified virulence
factors only) and of the full dataset (Down/VFDB_setB_nt.fas.gz, "DNA sequences of full dataset": also genes of
predicted virulence factors), over HTTPS (http:// redirects there). Only the current files exist; VFDB rebuilds them
often, publishes no checksum or version file, and the files state no release, so the version ARVA records is the
day of the server's Last-Modified (the same time gzip stores in the file). The data are licensed CC BY-NC 4.0 (VFDB's
terms of use). The site has a security filter that can answer with a web page (status 200) instead of a file, so
ARVA checks the type of the answer here and the gzip header and FASTA content in the worker.

The plan reads only the file's HTTP headers (HEAD). After the user confirms the file, its size and date, the source
and the licence and citation, the worker (app.tasks.vfdb_db) downloads it, converts it as abricate-get_db converts
set A (arva_tools.abricate_vfdb), indexes it with ABRicate's makeblastdb as abricate-get_db does, checks the index
(sequence count) and records the SHA-256 of the downloaded file, of the FASTA inside and of the database built
(ARVA_DATABASE.json and the record). A file the user has is only read: ARVA builds its own database from it, in a
database folder ARVA may write.

The bundled core set A stays the default VFDB of the virulence screen unless the user makes another one the default
in the Database Manager.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arva_tools import abricate_vfdb as conv
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.messages import render
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase, VersionSource
from app.services import database_detect as detection
from app.services import database_kinds as kinds
from app.services import databases as dbs

KIND = "vfdb"
SET_KEYS = {"A": "vfdb-setA", "B": "vfdb-setB"}
SET_NAMES = {"A": "VFDB core (set A)", "B": "VFDB full (set B)"}
DATASETS = {"A": "core", "B": "full"}
FILE = conv.SETS["B"] + ".gz"
# The folder ABRicate is pointed at with --db (inside the dated folder, which is its --datadir).
DB_FOLDER = {"A": "vfdb_setA", "B": "vfdb_setB"}
# The database ARVA builds holds about 6.9 times the compressed size (2026-11-06 set B: 10,685,329 bytes compressed,
# 55,414,000 bytes of sequences and 22,104,507 of BLAST index); the plan asks for the downloaded file plus 7 times it,
# and 7.5 times a plain FASTA's size for one built from a file (the FASTA is read into memory, never copied).
BUILT_PER_COMPRESSED = 7
BUILT_PER_PLAIN = 1.5
HEAD_TIMEOUT = 30
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

MESSAGES = {
    "vfdb_unreachable": "VFDB's download folder could not be read ({detail}).",
    "vfdb_not_a_file": "VFDB's server answered with a web page instead of {file} (its security filter may have "
                       "stopped the request); try again later.",
    "vfdb_undated": "VFDB's server gives no Last-Modified date for {file}, so ARVA cannot record which version it is.",
    "vfdb_confirm": "Confirm the file ({file}, {size}, {version}), VFDB's licence and the citation first.",
    "vfdb_changed": "VFDB's current {file} is now dated {version} ({size}), not the {confirmed} you confirmed; look at "
                    "the plan again.",
    "vfdb_known": "{name} {version} is already known to ARVA ({path}); delete that record first.",
    "vfdb_not_vfdb_file": "{path} is not one of VFDB's nucleotide files (VFDB_setA_nt.fas or VFDB_setB_nt.fas, also "
                          ".gz); say which set it is.",
    "vfdb_set_needed": "Say which VFDB set {path} is (A, the core dataset, or B, the full dataset).",
    "vfdb_version_needed": "{path} states no date: give the day you downloaded it from VFDB (YYYY-MM-DD).",
    "vfdb_no_abricate": "ABRicate is not installed, so ARVA cannot index a VFDB database for it.",
}


class VfdbError(dbs.DatabaseError):
    def __init__(self, code: str, upstream: bool = False, **params):
        super().__init__(render(MESSAGES[code], params), code, **params)
        self.upstream = upstream


# --- What each record is ----------------------------------------------------------------------------------------

def variant(record: ReferenceDatabase) -> str | None:
    return ((record.details or {}).get("detection") or {}).get("variant")


def abricate_ready(record: ReferenceDatabase) -> bool:
    """Whether ABRicate can search this VFDB record: its own bundled copy or a folder in ABRicate's format."""
    return record.kind == KIND and variant(record) in ("abricate", *kinds.ABRICATE_FOLDERS)


def set_of(record: ReferenceDatabase | None) -> str | None:
    """A (core) or B (full) for a VFDB record ABRicate can search; None when it is not known."""
    if record is None:
        return None
    if variant(record) == "abricate":
        return "A"
    info = (record.details or {}).get("vfdb") or {}
    facts = (((record.details or {}).get("detection") or {}).get("facts") or {}).get("abricate") or {}
    s = info.get("set") or facts.get("set")
    return s if s in SET_KEYS else None


def provenance(record: ReferenceDatabase) -> dict[str, Any]:
    """What a run records about the VFDB it searched: the set, the dataset (core or full), the version and how it was
    known, where it came from and the checksums ARVA recorded."""
    s = set_of(record)
    info = (record.details or {}).get("vfdb") or {}
    out: dict[str, Any] = {"set": s, "dataset": DATASETS.get(s or ""), "name": record.name, "version": record.version,
                           "version_source": record.version_source.value if record.version_source else None,
                           "bundled": record.origin is DatabaseOrigin.bundled, "checksum": record.checksum}
    for k in ("source", "fasta", "sequences", "built_by"):
        if info.get(k):
            out[k] = info[k]
    return out


def terms(record: ReferenceDatabase) -> dict[str, Any]:
    k = kinds.BY_KEY[KIND]
    return {"licence": k.licence, "licence_url": k.licence_url, "citation": k.citation,
            "unconfirmed": list(k.unconfirmed)}


# --- The current file on VFDB's server ---------------------------------------------------------------------------

def base_url() -> str:
    url = get_settings().vfdb_url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise VfdbError("vfdb_unreachable", True, detail=f"{url} is not an https address")
    return url


def head(url: str) -> dict[str, Any]:
    """The facts of the current file from a HEAD request: size, Last-Modified (the version), ETag and type."""
    import urllib.error
    import urllib.request

    from app.tasks.databases import USER_AGENT, _SameOriginRedirect

    opener = urllib.request.build_opener(_SameOriginRedirect)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT,
                                                              "Accept-Encoding": "identity"})
    try:
        with opener.open(req, timeout=HEAD_TIMEOUT) as resp:
            headers = resp.headers
    except urllib.error.HTTPError as exc:
        raise VfdbError("vfdb_unreachable", True, detail=f"HTTP {exc.code} {exc.reason}") from exc
    except OSError as exc:
        raise VfdbError("vfdb_unreachable", True, detail=str(getattr(exc, "reason", exc))) from exc
    except Exception as exc:  # TaskFailure from a redirect off the official host
        raise VfdbError("vfdb_unreachable", True, detail=str(exc)) from exc
    kind = (headers.get("Content-Type") or "").lower()
    length = headers.get("Content-Length") or ""
    if "html" in kind or not length.isdigit() or int(length) <= 0:
        raise VfdbError("vfdb_not_a_file", True, file=FILE)
    modified = headers.get("Last-Modified")
    try:
        when = parsedate_to_datetime(modified).astimezone(UTC) if modified else None
    except (TypeError, ValueError):
        when = None
    if when is None:
        raise VfdbError("vfdb_undated", True, file=FILE)
    return {"bytes": int(length), "last_modified": modified, "last_modified_utc": when.isoformat(),
            "version": when.date().isoformat(), "etag": headers.get("ETag"), "content_type": kind or None}


def _blocker(db: Session, key: str, version: str, target: Path) -> tuple[str | None, str | None]:
    for r in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.key == key,
                                                        ReferenceDatabase.version == version)):
        if r.status not in (DatabaseStatus.failed, DatabaseStatus.cancelled):
            return render(MESSAGES["vfdb_known"], {"name": r.name, "version": version,
                                                   "path": dbs._shown(r.path or "")}), "already_known"
    if target.parent.exists():
        return (f"{dbs._shown(target.parent)} already exists but ARVA has no record of it. Register it if it is a "
                "database, or choose another folder", "target_exists")
    if any(r.path and Path(r.path) in target.parents for r in db.scalars(select(ReferenceDatabase))):
        return f"{dbs._shown(target)} lies inside another database's folder; choose another folder", "inside_database"
    return None, None


def _place(destination: str | None, folder: str | None, key: str, version: str, s: str) -> tuple[Path, str, Path]:
    root = dbs._destination(destination)
    folder_text = dbs._folder(folder, f"{key}/{version}")
    return root, folder_text, root / folder_text / DB_FOLDER[s]


def _space(root: Path, required: int) -> dict[str, Any]:
    free = dbs.free_bytes(root)
    available = max(0, free - get_settings().min_free_bytes)
    return {"required_bytes": required, "free_bytes": free, "reserve_bytes": get_settings().min_free_bytes,
            "available_bytes": available, "enough": required <= available}


def _common(root: Path, folder_text: str, target: Path) -> dict[str, Any]:
    k = kinds.BY_KEY[KIND]
    return {"db_dir": str(root), "folder": folder_text, "target_path": str(target),
            "host_target_path": dbs._shown(target), "abricate_db": target.name,
            "destinations": dbs.writable_locations(), "licence": k.licence, "licence_url": k.licence_url,
            "citation": k.citation, "terms_url": "https://www.mgc.ac.cn/VFs/main.htm#termofuse",
            "source_page": k.source_url, "no_checksum": True}


def plan_download(db: Session, destination: str | None = None, folder: str | None = None) -> dict[str, Any]:
    """What downloading the current full set B would do: the file, its size and date as VFDB's server states them
    (one HEAD request), the source, the licence and citation, the folder and the space needed."""
    url = f"{base_url()}/{FILE}"
    facts = head(url)
    key = SET_KEYS["B"]
    root, folder_text, target = _place(destination, folder, key, facts["version"], "B")
    blocked, code = _blocker(db, key, facts["version"], target)
    return {**facts, **_common(root, folder_text, target), **_space(root, facts["bytes"] * (1 + BUILT_PER_COMPRESSED)),
            "url": url, "file": FILE, "set": "B", "dataset": "full", "name": SET_NAMES["B"], "key": key,
            "blocked_by": blocked, "blocked_code": code, "only_current": True}


def start_download(db: Session, confirm_version: str, confirm_bytes: int, accept_terms: bool,
                   destination: str | None = None, folder: str | None = None) -> ReferenceDatabase:
    """Plan again (VFDB may have rebuilt the file since), check the confirmation and queue the download."""
    from app.tasks.vfdb_db import run_vfdb_download

    p = plan_download(db, destination, folder)
    if not accept_terms or confirm_bytes <= 0 or not confirm_version:
        raise VfdbError("vfdb_confirm", file=FILE, size=f"{p['bytes']:,} bytes", version=p["version"])
    if confirm_bytes != p["bytes"] or confirm_version != p["version"]:
        raise VfdbError("vfdb_changed", file=FILE, version=p["version"], size=f"{p['bytes']:,} bytes",
                        confirmed=f"{confirm_version[:20]} ({confirm_bytes:,} bytes)")
    if p["blocked_by"]:
        raise dbs.DatabaseStateError(p["blocked_by"])
    if not p["enough"]:
        raise dbs.DatabaseSpaceError(p["required_bytes"], p["available_bytes"], Path(p["db_dir"]))
    k = kinds.BY_KEY[KIND]
    record = ReferenceDatabase(
        key=p["key"], kind=KIND, name=SET_NAMES["B"], version=p["version"], path=p["target_path"],
        origin=DatabaseOrigin.download, status=DatabaseStatus.downloading, log_text="", source_url=p["url"],
        licence=k.licence, task_id=dbs._task_id(),
        details={"destination": p["db_dir"],
                 "vfdb": {"set": "B", "dataset": "full",
                          "source": {"url": p["url"], "file": FILE, "bytes": p["bytes"],
                                     "last_modified": p["last_modified"], "last_modified_utc": p["last_modified_utc"],
                                     "etag": p["etag"]}},
                 "confirmation": {"version": confirm_version, "bytes": confirm_bytes, "licence": k.licence,
                                  "citation": k.citation, "at": dbs.now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": p["bytes"]},
    )
    db.add(record)
    db.commit()
    dbs._enqueue(record, run_vfdb_download)
    db.refresh(record)
    return record


# --- A database built from a file the user has -------------------------------------------------------------------

def file_facts(path: Path) -> dict[str, Any]:
    """What a VFDB nucleotide file says about itself: its set by VFDB's own file name (or the name gzip stored), and
    for a .gz file the time gzip stored, which is when VFDB rebuilt it."""
    gz = conv.gzip_header(path)
    stamp = (gz or {}).get("mtime")
    return {"set": conv.sniff_set(path), "compressed": gz is not None, "gzip_name": (gz or {}).get("name"),
            "gzip_mtime": stamp, "version": stamp[:10] if stamp else None, "bytes": path.stat().st_size}


def plan_build(db: Session, raw_path: str, vfdb_set: str | None = None, declared_version: str | None = None,
               destination: str | None = None, folder: str | None = None) -> dict[str, Any]:
    """What building an ABRicate database from a VFDB nucleotide file the user has would do (the file is only read)."""
    path = dbs.resolve_registration_path(raw_path)
    if not path.is_file():
        raise VfdbError("vfdb_not_vfdb_file", path=raw_path)
    facts = file_facts(path)
    s = facts["set"] or vfdb_set
    if s not in SET_KEYS:
        raise VfdbError("vfdb_set_needed" if vfdb_set is None else "vfdb_not_vfdb_file", path=raw_path)
    if vfdb_set and facts["set"] and vfdb_set != facts["set"]:
        raise VfdbError("vfdb_not_vfdb_file", path=raw_path)
    version, source = facts["version"], VersionSource.file
    if version is None:
        declared = (declared_version or "").strip()
        if not _DATE.fullmatch(declared):
            raise VfdbError("vfdb_version_needed", path=raw_path)
        version, source = declared, VersionSource.declared
    key = SET_KEYS[s]
    root, folder_text, target = _place(destination, folder, key, version, s)
    blocked, code = _blocker(db, key, version, target)
    built = facts["bytes"] * (BUILT_PER_COMPRESSED if facts["compressed"] else BUILT_PER_PLAIN)
    return {**facts, **_common(root, folder_text, target), **_space(root, int(built)), "source": str(path),
            "host_source": dbs._shown(path), "set": s, "dataset": DATASETS[s], "name": SET_NAMES[s], "key": key,
            "version": version, "version_source": source.value, "blocked_by": blocked, "blocked_code": code}


def start_build(db: Session, raw_path: str, confirm_bytes: int, accept_terms: bool, vfdb_set: str | None = None,
                declared_version: str | None = None, destination: str | None = None,
                folder: str | None = None) -> ReferenceDatabase:
    from app.tasks.vfdb_db import run_vfdb_build

    p = plan_build(db, raw_path, vfdb_set, declared_version, destination, folder)
    if not accept_terms or confirm_bytes != p["bytes"]:
        raise VfdbError("vfdb_confirm", file=Path(p["source"]).name, size=f"{p['bytes']:,} bytes",
                        version=p["version"])
    if p["blocked_by"]:
        raise dbs.DatabaseStateError(p["blocked_by"])
    if not p["enough"]:
        raise dbs.DatabaseSpaceError(p["required_bytes"], p["available_bytes"], Path(p["db_dir"]))
    k = kinds.BY_KEY[KIND]
    st = os.stat(p["source"])
    record = ReferenceDatabase(
        key=p["key"], kind=KIND, name=p["name"], version=p["version"], version_source=VersionSource(p["version_source"]),
        path=p["target_path"], origin=DatabaseOrigin.extract, status=DatabaseStatus.extracting, log_text="",
        source_url=k.source_url, licence=k.licence, task_id=dbs._task_id(),
        details={"destination": p["db_dir"],
                 "vfdb": {"set": p["set"], "dataset": p["dataset"],
                          "source": {"path": p["source"], "host_path": p["host_source"], "file": Path(p["source"]).name,
                                     "bytes": p["bytes"], "gzip_name": p["gzip_name"], "gzip_mtime": p["gzip_mtime"],
                                     "modified": datetime.fromtimestamp(st.st_mtime, UTC).isoformat()}},
                 "confirmation": {"version": p["version"], "bytes": confirm_bytes, "licence": k.licence,
                                  "citation": k.citation, "at": dbs.now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": p["bytes"]},
    )
    db.add(record)
    db.commit()
    dbs._enqueue(record, run_vfdb_build)
    db.refresh(record)
    return record


def registered_details(found: detection.Detection, vfdb_set: str | None) -> dict[str, Any]:
    """The `vfdb` details of a registered VFDB folder in ABRicate's format: the set from ARVA_DATABASE.json, else the
    one the user declared."""
    info = (found.facts.get("abricate") or {}).get("vfdb") or {}
    s = info.get("set") or vfdb_set
    if s not in SET_KEYS:
        raise VfdbError("vfdb_set_needed", path=dbs._shown(found.path))
    return {**info, "set": s, "dataset": DATASETS[s], "set_source": "file" if info.get("set") else "declared"}
