"""Worker task: download NCBI's current 16S ribosomal RNA BLAST database (app.services.ncbi16s_db).

The archive is fetched over HTTPS into the database folder's download area (a stopped download resumes), its MD5 is
compared with the one NCBI published and confirmed in the plan, and only the database files (NCBI's taxonomy files
only if asked) are extracted, member by member, with the same safety checks as every archive ARVA unpacks. The folder
is then recognised as the ncbi_16s kind (blastdbcmd -info reads it), its build date must be the confirmed one, and
the SHA-256 of every kept file is recorded. The archive is deleted after the verified extraction.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.models import DatabaseStatus, VersionSource
from app.services import databases as svc
from app.services.database_detect import NCBI_16S_METADATA, NCBI_16S_TAXONOMY
from app.services.ncbi16s_db import ARCHIVE, MD5_FILE, READ_LIMIT, parse_metadata
from app.tasks.databases import (
    CHUNK,
    SPACE_CHECK_BYTES,
    Task,
    TaskCancelled,
    TaskFailure,
    _checked,
    _download_cleanup,
    _run,
    extract,
    fetch,
    fmt_bytes,
    folder_items,
    hash_files,
    manifest_bytes,
    manifest_checksum,
    verify_md5,
)


@dataclass(frozen=True)
class _Archive:
    """What fetch() and verify_md5() read of a catalogue entry, for the confirmed build."""
    download_url: str
    archive_bytes: int
    extracted_bytes_estimate: int
    checksum: str
    checksum_sources: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(build: dict) -> str | None:
    """NCBI's metadata file of the build, kept next to the database (its last-updated is the version); None when it
    now describes another build (the detector then reads the date blastdbcmd -info prints)."""
    from app.tasks.databases import _open

    url = build.get("metadata_url")
    if not url:
        return None
    try:
        with _open(url, 0) as resp:
            text = resp.read(READ_LIMIT).decode("utf-8", "replace")
        return text if parse_metadata(text)["last_updated"] == build.get("last_updated") else None
    except Exception:
        return None


def _download(task: Task) -> None:
    r = task.record
    build = (r.details or {}).get("build") or {}
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents or not build.get("url") or not build.get("md5"):
        raise TaskFailure(f"unexpected install folder {r.path}")
    taxonomy = bool(build.get("taxonomy"))
    kept = set(build.get("kept_files") or [])
    archive = _Archive(build["url"], int(build["archive_bytes"]), int(build.get("database_bytes") or 0),
                       build["md5"], (f"{build['url']}.md5",))
    task.log(f"NCBI 16S ribosomal RNA, build {r.version} ({build.get('sequences')} sequences), from {build['url']}; "
             f"{'with' if taxonomy else 'without'} NCBI's taxonomy files; terms accepted at "
             f"{((r.details or {}).get('confirmation') or {}).get('at')}; into {svc._shown(target)}", flush=True)
    downloads = svc.downloads_dir(r.id, root)
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / f"{ARCHIVE}.part"
    fetch(task, archive, part)
    md5 = verify_md5(task, archive, part)
    sha = _sha256(part)
    task.log(f"SHA-256 of the archive: {sha}")
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    since = [0]

    def extracting(read: int, written: int) -> None:
        if written - since[0] >= SPACE_CHECK_BYTES:
            since[0] = written
        task.tick(phase="extract", bytes_done=read, bytes_total=archive.archive_bytes, written_bytes=written)

    skipped: list[str] = []

    def keep(rel: PurePosixPath) -> bool:
        wanted = str(rel) in kept and (taxonomy or rel.name not in NCBI_16S_TAXONOMY)
        if not wanted:
            skipped.append(str(rel))
        return wanted

    unpacked = staging / "unpacked"
    members = extract(part, unpacked, None, extracting, keep=keep)
    (unpacked / MD5_FILE).write_text(f"{md5}  {ARCHIVE}\n")
    meta = _metadata(build)
    if meta is not None:
        (unpacked / NCBI_16S_METADATA).write_text(meta)
    if skipped:
        task.log(f"Not extracted: {', '.join(skipped[:20])}")
    found = _checked(task, "ncbi_16s", unpacked, r.version)
    manifest, _ = hash_files(folder_items(unpacked), lambda d, t: task.tick(phase="manifest", bytes_done=d,
                                                                            bytes_total=t))
    checksum = manifest_checksum(manifest)
    if task.cancel_requested(lock=True):
        raise TaskCancelled()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(unpacked, target)
    shutil.rmtree(downloads)
    shutil.rmtree(staging)
    size = manifest_bytes(manifest)
    task.log(f"Installed in {svc._shown(target)}: {len(manifest)} files, {size:,} bytes ({fmt_bytes(size)}); content "
             f"checksum {checksum}. The archive was deleted after the verified extraction")
    stamp = svc.now()
    r.status, r.version_source, r.verification_level = DatabaseStatus.installed, VersionSource.file, "full"
    r.size_bytes, r.checksum, r.archive_checksum, r.manifest = size, checksum, f"md5:{md5}", manifest
    r.installed_at = r.verified_at = stamp
    found.path = str(target)
    r.details = {**(r.details or {}), "detection": svc._stored_detection(found), "file_count": len(manifest),
                 "members": members, "archive": {"url": build["url"], "filename": ARCHIVE, "bytes":
                                                 archive.archive_bytes, "md5": md5, "sha256": sha,
                                                 "checksum_sources": list(archive.checksum_sources),
                                                 "deleted_after_extraction": True, "not_extracted": skipped}}
    task.set_progress(phase="done", bytes_done=size, bytes_total=size)
    svc.ensure_default(task.db, r.kind)


def run_ncbi16s_download(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _download, _download_cleanup)
