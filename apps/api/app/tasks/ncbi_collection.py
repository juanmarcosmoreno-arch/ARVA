"""Worker task: download the reference collection the user confirmed from NCBI Datasets, check it and install it.

The genome data package is requested for exactly the confirmed accessions (POST /genome/download, genomic FASTA
only) into the database folder's download area, with a cap on its size (NCBI sends no Content-Length). It is
extracted with the same checks as a zip the user provides (plain files, no '..', declared sizes, CRC-32), every file
is compared with the package's md5sum.txt, and the accessions in the package must be the confirmed ones. The zip is
deleted after the verified extraction (its SHA-256 is recorded). The version is the source and the download date
(UTC) with the accession fingerprint, recorded by ARVA (version source "download").
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.models import DatabaseStatus, VersionSource
from app.services import databases as svc
from app.services import ncbi_datasets as ncbi
from app.services import reference_collections as rc
from app.tasks.databases import (
    CHUNK,
    SPACE_CHECK_BYTES,
    Task,
    TaskCancelled,
    TaskFailure,
    _checked,
    _compare_published,
    _download_cleanup,
    _run,
    extract_zip,
    folder_items,
    hash_files,
    manifest_bytes,
    manifest_checksum,
)

ZIP_NAME = "ncbi_dataset.zip"
# The package may be larger than NCBI's estimate; ARVA accepts up to this many times it (and at least 64 MB more).
ZIP_FACTOR = 4
ZIP_MARGIN = 64 << 20


def _fetch(task: Task, accessions: list[str], part: Path, limit: int) -> tuple[int, str]:
    req = ncbi._request("POST", "/genome/download", {"filename": ZIP_NAME},
                        {"accessions": accessions, "include_annotation_type": ["GENOME_FASTA"]})
    req.headers["Accept"] = "application/zip"
    digest, done, since = hashlib.sha256(), 0, 0
    try:
        resp = ncbi.open_request(req, "genome package")
    except ncbi.NcbiError as exc:
        raise TaskFailure(str(exc), exc.code, **exc.params) from exc
    with resp, open(part, "wb") as out:
        task.log(f"Downloading the genome package of {len(accessions)} genomes from {req.full_url} (POST, genomic "
                 "FASTA only)", flush=True)
        while chunk := resp.read(CHUNK):
            done += len(chunk)
            if done > limit:
                raise TaskFailure(f"the package is larger than {limit:,} bytes ({ZIP_FACTOR} times NCBI's estimate); "
                                  "nothing was kept", "ncbi_too_large", limit=limit)
            out.write(chunk)
            digest.update(chunk)
            since += len(chunk)
            if since >= SPACE_CHECK_BYTES:
                since = 0
                out.flush()
                task.ensure_room(SPACE_CHECK_BYTES)
            task.tick(phase="download", bytes_done=done, bytes_total=None)
    return done, digest.hexdigest()


def _body(task: Task) -> None:
    r = task.record
    details = r.details or {}
    meta = details["ncbi"]
    accessions = list(meta["accessions"])
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents:
        raise TaskFailure(f"unexpected install folder {r.path}")
    if target.exists():
        raise TaskFailure(f"{svc._shown(target)} already exists", "target_exists", path=svc._shown(target))
    if ncbi.fingerprint(accessions) != meta["fingerprint"]:
        raise TaskFailure("the recorded accession list does not match its confirmed fingerprint")
    task.log(f"Reference collection: {meta['taxon']['name']} (NCBI Taxonomy {meta['taxon']['tax_id']}), filters "
             f"{json.dumps(meta['filters'], sort_keys=True)}, {len(accessions)} genomes confirmed at "
             f"{details['confirmation']['at']} (fingerprint {meta['fingerprint'][:12]}); no API key, e-mail or "
             "personal data is sent", flush=True)
    downloads = svc.downloads_dir(r.id, root)
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / f"{ZIP_NAME}.part"
    estimate = int(meta["zip_estimate_bytes"])
    task.ensure_room(estimate + int(meta["fasta_estimate_bytes"]))
    size, sha = _fetch(task, accessions, part, max(estimate * ZIP_FACTOR, estimate + ZIP_MARGIN))
    day = datetime.now(UTC).date().isoformat()
    task.log(f"Downloaded {size:,} bytes (sha256 {sha})", flush=True)
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(part) as z:
            declared = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as exc:
        raise TaskFailure(f"NCBI's package is not a readable zip: {exc}", "archive_damaged", detail=str(exc)) from exc
    task.ensure_room(declared)
    files = extract_zip(part, staging / "unpacked", declared,
                        lambda d, t: task.tick(phase="extract", bytes_done=d, bytes_total=t))
    unpacked = staging / "unpacked"
    found = _checked(task, "reference_genomes", unpacked)
    got = {g["accession"] for g in found.facts.get("genomes", []) if g.get("accession") and g.get("present")}
    if missing := sorted(set(accessions) - got):
        raise TaskFailure(f"NCBI's package lacks {len(missing)} confirmed genome(s): {', '.join(missing[:10])}",
                          "ncbi_package_incomplete", count=len(missing), names=", ".join(missing[:10]))
    if extra := sorted(got - set(accessions)):
        raise TaskFailure(f"NCBI's package holds {len(extra)} genome(s) that were not confirmed: "
                          f"{', '.join(extra[:10])}", "ncbi_package_unexpected", count=len(extra),
                          names=", ".join(extra[:10]))
    published = {str(unpacked / k): v for k, v in rc.package_md5s(unpacked).items()}
    if not published:
        raise TaskFailure("NCBI's package has no md5sum.txt to check its files against", "ncbi_no_checksums")
    items = folder_items(unpacked)
    manifest, md5s = hash_files([(str(unpacked / k), p) for k, p in items],
                                lambda d, t: task.tick(phase="manifest", bytes_done=d, bytes_total=t),
                                frozenset(published))
    _compare_published(task, published, md5s)
    if task.cancel_requested(lock=True):
        raise TaskCancelled()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(unpacked, target)
    shutil.rmtree(staging)
    shutil.rmtree(downloads)

    def moved(p: str) -> str:
        return str(target / Path(p).relative_to(unpacked)) if Path(p).is_relative_to(unpacked) else p

    manifest = [{**m, "path": moved(m["path"])} for m in manifest]
    genomes = [{**g, "path": moved(g["path"])} for g in found.facts.get("genomes", [])]
    found.path = str(target)
    stamp = svc.now()
    r.version, r.version_source = rc.version_string("ncbi_package", day, found.facts["collection"]["fingerprint"]), \
        VersionSource.download
    r.status, r.verification_level = DatabaseStatus.installed, "full"
    r.checksum, r.size_bytes = manifest_checksum(manifest), manifest_bytes(manifest)
    r.archive_checksum = f"sha256:{sha}"
    r.installed_at = r.verified_at = stamp
    r.manifest, r.inventory = manifest, genomes
    r.details = {**details, "detection": svc._stored_detection(found), "collection": found.facts.get("collection"),
                 "collection_date": day, "file_count": len(manifest), "published_md5_checked": len(md5s),
                 "archive": {"bytes": size, "sha256": sha, "deleted_after_extraction": True, "members": files}}
    c = found.facts.get("collection") or {}
    task.log(f"Installed in {svc._shown(target)}: {c.get('genomes')} genomes of {c.get('species')} species, every file "
             f"matching md5sum.txt; version {r.version} (download date, recorded by ARVA); content checksum "
             f"{r.checksum}. The zip was deleted after the verified extraction")
    task.set_progress(phase="done", bytes_done=r.size_bytes, bytes_total=r.size_bytes)
    svc.ensure_default(task.db, r.kind)


def _cleanup(task: Task, exc: BaseException) -> None:
    _download_cleanup(task, exc)
    shutil.rmtree(svc.downloads_dir(task.record.id, svc.destination_root(task.record)), ignore_errors=True)


def run_ncbi_collection(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _body, _cleanup)

