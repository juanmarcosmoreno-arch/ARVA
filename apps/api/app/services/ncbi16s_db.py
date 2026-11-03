"""NCBI's 16S ribosomal RNA BLAST database: the current build, downloaded only after the user confirms it.

NCBI keeps one build of each BLAST database on its FTP site and no older ones (BLAST databases README: "There is no
established incremental update scheme"; listing of https://ftp.ncbi.nlm.nih.gov/blast/db/ on 2026-11-03). For
16S_ribosomal_RNA it publishes the archive, its MD5 file and a metadata file (16S_ribosomal_RNA-nucl-metadata.json:
description, sequence and letter counts, "last-updated", compressed size). ARVA reads the metadata and the MD5 file
to plan, and after the user confirms the size and the date the worker (app.tasks.ncbi16s_db) downloads the archive
over HTTPS, checks its MD5 and SHA-256, and extracts only the database files, with NCBI's taxonomy files only when
asked. It never runs update_blastdb.pl. The build's date is its version (database_kinds.py, kind ncbi_16s).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.messages import render
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase
from app.services import database_kinds as kinds
from app.services import databases as dbs
from app.services.database_detect import (
    NCBI_16S,
    NCBI_16S_FILES,
    NCBI_16S_METADATA,
    NCBI_16S_TAXONOMY,
)

KIND = KEY = "ncbi_16s"
ARCHIVE = f"{NCBI_16S}.tar.gz"
MD5_FILE = f"{ARCHIVE}.md5"
READ_LIMIT = 1 << 16
# The 2026-10-29 build unpacked: the database files 18,413,401 bytes ("bytes-total" of the metadata); NCBI's
# taxonomy files in the same archive about 295 MB (taxdb.btd 177 MB, taxdb.bti 18.5 MB, taxonomy4blast.sqlite3
# 99 MB; docs/sanger-design-notes.md section 3). ARVA asks for the archive plus this much free space.
TAXONOMY_BYTES_ESTIMATE = 300 * 1024 * 1024
_MD5 = re.compile(r"^([0-9a-f]{32})\s+\*?(\S+)\s*$")

MESSAGES = {
    "ncbi16s_unreachable": "NCBI's BLAST database folder could not be read ({detail}).",
    "ncbi16s_metadata": "NCBI's description of the 16S database could not be read: {detail}",
    "ncbi16s_confirm": "Confirm the build ({version}), its size ({size}) and NCBI's terms first.",
    "ncbi16s_changed": "NCBI's current build is {version}, not the {confirmed} you confirmed; look at the plan again.",
    "ncbi16s_known": "The NCBI 16S build {version} is already known to ARVA ({path}); delete that record first.",
}


class Ncbi16sError(dbs.DatabaseError):
    def __init__(self, code: str, upstream: bool = False, **params):
        super().__init__(render(MESSAGES[code], params), code, **params)
        self.upstream = upstream


def base_url() -> str:
    url = get_settings().ncbi_blast_db_url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise Ncbi16sError("ncbi16s_unreachable", True, detail=f"{url} is not an https address")
    return url


def _read(url: str) -> str:
    from app.tasks.databases import TaskFailure, _open

    try:
        with _open(url, 0) as resp:
            return resp.read(READ_LIMIT).decode("utf-8", "replace")
    except TaskFailure as exc:
        raise Ncbi16sError("ncbi16s_unreachable", True, detail=str(exc)) from exc
    except OSError as exc:
        raise Ncbi16sError("ncbi16s_unreachable", True, detail=str(getattr(exc, "reason", exc))) from exc


def parse_metadata(text: str) -> dict[str, Any]:
    """The facts ARVA uses from 16S_ribosomal_RNA-nucl-metadata.json (fields as NCBI wrote them on 2026-11-03)."""
    try:
        meta = json.loads(text)
    except ValueError as exc:
        raise Ncbi16sError("ncbi16s_metadata", True, detail=str(exc)) from exc
    day = str(meta.get("last-updated") or "")[:10] if isinstance(meta, dict) else ""
    size = meta.get("bytes-total-compressed") if isinstance(meta, dict) else None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not isinstance(size, int) or size <= 0:
        raise Ncbi16sError("ncbi16s_metadata", True, detail="it lacks last-updated or bytes-total-compressed")
    return {"version": day, "archive_bytes": size, "database_bytes": meta.get("bytes-total"),
            "description": meta.get("description"), "sequences": meta.get("number-of-sequences"),
            "letters": meta.get("number-of-letters"), "dbname": meta.get("dbname"),
            "last_updated": meta.get("last-updated"), "metadata_format": meta.get("version")}


def parse_md5(text: str) -> str:
    for line in text.splitlines():
        m = _MD5.match(line.strip())
        if m and m.group(2) == ARCHIVE:
            return m.group(1)
    raise Ncbi16sError("ncbi16s_metadata", True, detail=f"{MD5_FILE} names no MD5 for {ARCHIVE}")


def _blocker(db: Session, version: str, target: Path) -> tuple[str | None, str | None]:
    for r in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == KIND,
                                                        ReferenceDatabase.version == version)):
        if r.status not in (DatabaseStatus.failed, DatabaseStatus.cancelled):
            return render(MESSAGES["ncbi16s_known"], {"version": version, "path": dbs._shown(r.path or "")}), \
                "already_known"
    if target.exists():
        return (f"{dbs._shown(target)} already exists but ARVA has no record of it. Register it if it is a database, "
                "or choose another folder", "target_exists")
    if any(r.path and Path(r.path) in target.parents for r in db.scalars(select(ReferenceDatabase))):
        return f"{dbs._shown(target)} lies inside another database's folder; choose another folder", "inside_database"
    return None, None


def plan(db: Session, taxonomy: bool = False, destination: str | None = None,
         folder: str | None = None) -> dict[str, Any]:
    """What downloading the current build would do: its date, size and MD5 as NCBI publishes them, the files that
    would be kept, the folder and the space needed. Only NCBI's two small text files are read."""
    url = base_url()
    meta = parse_metadata(_read(f"{url}/{NCBI_16S_METADATA}"))
    md5 = parse_md5(_read(f"{url}/{MD5_FILE}"))
    root = dbs._destination(destination)
    folder_text = dbs._folder(folder, f"ncbi-16s/{meta['version']}")
    target = root / folder_text
    database_bytes = meta["database_bytes"] if isinstance(meta["database_bytes"], int) else 0
    required = meta["archive_bytes"] + database_bytes + (TAXONOMY_BYTES_ESTIMATE if taxonomy else 0)
    free = dbs.free_bytes(root)
    available = max(0, free - get_settings().min_free_bytes)
    blocked, code = _blocker(db, meta["version"], target)
    k = kinds.BY_KEY[KIND]
    return {**meta, "url": f"{url}/{ARCHIVE}", "metadata_url": f"{url}/{NCBI_16S_METADATA}",
            "md5_url": f"{url}/{MD5_FILE}", "md5": md5, "taxonomy": taxonomy,
            "kept_files": [*NCBI_16S_FILES, NCBI_16S_METADATA, MD5_FILE, *(NCBI_16S_TAXONOMY if taxonomy else ())],
            "required_bytes": required, "db_dir": str(root), "folder": folder_text, "target_path": str(target),
            "host_target_path": dbs._shown(target), "free_bytes": free, "available_bytes": available,
            "enough": required <= available, "blocked_by": blocked, "blocked_code": code, "licence": k.licence,
            "licence_url": k.licence_url, "only_current": True}


def start(db: Session, confirm_version: str, confirm_bytes: int, accept_terms: bool, taxonomy: bool = False,
          destination: str | None = None, folder: str | None = None) -> ReferenceDatabase:
    """Plan again (NCBI may have published a new build since), check the confirmation and queue the download."""
    from app.tasks.ncbi16s_db import run_ncbi16s_download

    p = plan(db, taxonomy, destination, folder)
    if confirm_bytes != p["archive_bytes"] or not accept_terms:
        raise Ncbi16sError("ncbi16s_confirm", version=p["version"], size=f"{p['archive_bytes']:,} bytes")
    if confirm_version != p["version"]:
        raise Ncbi16sError("ncbi16s_changed", version=p["version"], confirmed=confirm_version[:20])
    if p["blocked_by"]:
        raise dbs.DatabaseStateError(p["blocked_by"])
    if not p["enough"]:
        raise dbs.DatabaseSpaceError(p["required_bytes"], p["available_bytes"], Path(p["db_dir"]))
    k = kinds.BY_KEY[KIND]
    record = ReferenceDatabase(
        key=KEY, kind=KIND, name=k.name, version=p["version"], path=p["target_path"], origin=DatabaseOrigin.download,
        status=DatabaseStatus.downloading, log_text="", source_url=p["url"], licence=k.licence,
        task_id=dbs._task_id(),
        details={"destination": p["db_dir"],
                 "build": {key: p[key] for key in ("url", "metadata_url", "md5", "archive_bytes", "database_bytes",
                                                   "description",
                                                   "sequences", "letters", "last_updated", "taxonomy",
                                                   "kept_files")},
                 "confirmation": {"version": confirm_version, "archive_bytes": confirm_bytes, "terms": k.licence,
                                  "taxonomy": taxonomy, "at": dbs.now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": p["archive_bytes"]},
    )
    db.add(record)
    db.commit()
    dbs._enqueue(record, run_ncbi16s_download)
    db.refresh(record)
    return record
