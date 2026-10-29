"""The VFDB and PlasmidFinder databases ABRicate bundles, as read-only database records.

ABRicate 1.4.0's package ships db/vfdb (VFDB's core set A nucleotides) and db/plasmidfinder (CGE's plasmidfinder_db)
already indexed; ARVA reads them where the environment installed them, records the SHA-256 of every file, the
index's date and sequence count, and never runs abricate-get_db or --setupdb (they fetch the latest data). The VFDB
licence and citation are shown as the vfdb kind states them (database_kinds.py: not stated on VFDB's download page).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from arva_tools import ToolStatus
from arva_tools import abricate as abr
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase, VersionSource
from app.services import database_detect as detection
from app.services import database_kinds as kinds
from app.services.annotation import _signature
from app.services.mlst import _manifest

KEYS = {"vfdb": "abricate-vfdb", "plasmidfinder": "abricate-plasmidfinder"}
NAMES = {"vfdb": "VFDB core set A (bundled with ABRicate {version})",
         "plasmidfinder": "PlasmidFinder replicons (bundled with ABRicate {version})"}


def bundled_database(db: Session, executable: str, tool_version: str | None, name: str) -> ReferenceDatabase | None:
    """One database bundled with this ABRicate as a record, created (or recorded again when its files changed) with
    the SHA-256 of every file; None when the package holds no complete, indexed copy."""
    from app.services.databases import _stored_detection, append_log, ensure_default, now

    folder = abr.datadir(executable) / name
    found = next((d for d in detection.detect(folder) if d.kind == name), None) if folder.is_dir() else None
    if found is None or not found.ok or found.version is None:
        return None
    manifest, checksum = _manifest(str(folder), _signature(folder))
    record = db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.path == str(folder)))
    if record is not None and record.checksum == checksum and record.status is DatabaseStatus.registered:
        return record
    stamp = now()
    k = kinds.BY_KEY[name]
    if record is None:
        record = ReferenceDatabase(key=KEYS[name], kind=name, path=str(folder), origin=DatabaseOrigin.bundled,
                                   installed_at=stamp, log_text="")
        db.add(record)
        append_log(record, f"Found the {name} database bundled with ABRicate {tool_version} in {folder}; ARVA reads "
                           "it there and never changes, updates or deletes it")
    else:
        append_log(record, "The bundled files are not the ones recorded (was ABRicate's environment rebuilt?); "
                           "recorded them again")
    info = found.facts["abricate"]
    record.name = NAMES[name].format(version=tool_version)
    record.version, record.version_source = found.version, VersionSource.file
    record.status, record.verification_level, record.verified_at = DatabaseStatus.registered, "full", stamp
    record.checksum, record.manifest = checksum, list(manifest)
    record.size_bytes = sum(m.get("size", 0) for m in manifest)
    record.source_url, record.licence = k.source_url, k.licence
    record.error_message = record.error_detail = None
    record.details = {"detection": _stored_detection(found), "abricate": info, "tool_version": tool_version,
                      "citation": k.citation, "unconfirmed": list(k.unconfirmed)}
    append_log(record, f"{info['sequences']} sequences, BLAST index of {info['indexed']} (the day the package indexed "
                       f"them; the files record no {name} release); content checksum {checksum}")
    db.flush()
    ensure_default(db, name)
    db.commit()
    db.refresh(record)
    return record


def refresh_bundled(db: Session) -> None:
    """Record ABRicate's bundled databases when ABRicate is installed (the Database Manager lists them)."""
    d = detect("abricate")
    if d.status is ToolStatus.available and d.path:
        for name in abr.DATABASES:
            bundled_database(db, d.path, d.version, name)


def summary(record: ReferenceDatabase) -> dict[str, Any]:
    info = (record.details or {}).get("abricate") or {}
    k = kinds.BY_KEY[record.kind]
    return {"id": record.id, "key": record.key, "kind": record.kind, "name": record.name, "version": record.version,
            "version_source": record.version_source.value if record.version_source else None,
            "checksum": record.checksum, "path": record.path, "sequences": info.get("sequences"),
            "indexed": info.get("indexed"), "licence": k.licence, "licence_url": k.licence_url,
            "citation": k.citation, "source_url": k.source_url, "unconfirmed": list(k.unconfirmed)}


def content_checksum(folder: Path) -> str:
    return _manifest(str(folder), _signature(folder))[1]
