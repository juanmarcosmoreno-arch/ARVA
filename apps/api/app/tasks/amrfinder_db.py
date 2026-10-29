"""Worker task: download an AMRFinderPlus database release from NCBI and index it.

The files are those amrfinder_update fetches (app.services.amrfinder_db.release_files), each downloaded over HTTPS
from the release's folder (no redirect to another host), its size compared with the server's Content-Length and its
SHA-256 recorded; NCBI publishes no checksums. After every file is in, taxgroup.tsv must name no taxgroup whose
AMR_DNA files are missing and version.txt must say the release asked for. amrfinder_index (next to the installed
amrfinder, with that environment's BLAST and HMMER) builds the indexes, `amrfinder --database_version` must accept
the folder, and the kind's folder check runs; then the folder becomes read-only and is moved into place.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import shutil
import urllib.error
from pathlib import Path

from arva_tools import ToolExecutionError
from arva_tools.amrfinderplus import AmrfinderplusAdapter, database_check, env_for
from arva_tools.registry import detect
from arva_tools.runner import run_command

from app.models import DatabaseStatus, VersionSource
from app.services import databases as svc
from app.services.capacity import fmt_bytes
from app.tasks.databases import (
    CHUNK,
    Task,
    TaskCancelled,
    TaskFailure,
    _checked,
    _download_cleanup,
    _open,
    _run,
    folder_items,
    hash_files,
    manifest_bytes,
    manifest_checksum,
)

INDEX_LOG = "amrfinder_index.log"


def _fetch(task: Task, url: str, dest: Path, done: int, total: int) -> tuple[int, str]:
    try:
        resp = _open(url, 0)
    except urllib.error.HTTPError as exc:
        raise TaskFailure(f"NCBI answered HTTP {exc.code} {exc.reason} for {url}", "http_error",
                          host="ftp.ncbi.nlm.nih.gov", status=exc.code) from exc
    except OSError as exc:
        raise TaskFailure(f"could not reach NCBI: {getattr(exc, 'reason', exc)}", "unreachable",
                          host="ftp.ncbi.nlm.nih.gov", detail=str(getattr(exc, "reason", exc))) from exc
    digest, size = hashlib.sha256(), 0
    with resp, open(dest, "xb") as out:
        if resp.status != 200:
            raise TaskFailure(f"NCBI answered HTTP {resp.status} for {url}", "http_error", host="ftp.ncbi.nlm.nih.gov",
                              status=resp.status)
        length = resp.headers.get("Content-Length")
        while True:
            try:
                chunk = resp.read(CHUNK)
            except (OSError, http.client.HTTPException) as exc:
                raise TaskFailure(f"the download of {dest.name} was interrupted ({exc}); start it again",
                                  "interrupted", done_bytes=done + size, total_bytes=total) from exc
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            task.tick(phase="download", bytes_done=done + size, bytes_total=total, file=dest.name)
    if length is not None and length.isdigit() and int(length) != size:
        raise TaskFailure(f"{dest.name}: the server announced {int(length):,} bytes but sent {size:,}", "interrupted",
                          done_bytes=done + size, total_bytes=total)
    return size, digest.hexdigest()


def _taxgroups_with_dna(folder: Path) -> list[str]:
    """The taxgroups taxgroup.tsv gives nucleotide reference genes (third column > 0), as amrfinder_update reads it."""
    out = []
    for line in (folder / "taxgroup.tsv").read_text(errors="replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 3 or not cols[2].strip().isdigit():
            raise TaskFailure(f"taxgroup.tsv has a line ARVA cannot read: {line[:80]!r}", "check_failed",
                              detail="taxgroup.tsv")
        if int(cols[2]):
            out.append(cols[0])
    return out


def _download(task: Task) -> None:
    r = task.record
    release = (r.details or {}).get("release") or {}
    files = release.get("files") or []
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents or not files:
        raise TaskFailure(f"unexpected install folder {r.path}")
    d = detect("amrfinderplus", refresh=True)
    if d.path is None:
        raise TaskFailure("AMRFinderPlus is not installed, so the release cannot be indexed", "check_failed",
                          detail="amrfinder not found")
    task.log(f"Release {r.version} from {release.get('url')} for AMRFinderPlus {release.get('minor')} (installed "
             f"{d.version} at {d.path}); {len(files)} files, about {fmt_bytes(release.get('download_bytes') or 0)}; "
             f"terms accepted at {((r.details or {}).get('confirmation') or {}).get('at')}. NCBI publishes no "
             "checksums: ARVA records the SHA-256 of each file it receives", flush=True)
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    folder = staging / r.version
    folder.mkdir(parents=True)
    total = int(release.get("download_bytes") or 0)
    task.ensure_room(int(total * 2))
    done, fetched = 0, []
    for f in files:
        size, sha = _fetch(task, f"{release['url']}{f['name']}", folder / f["name"], done, total)
        done += size
        fetched.append({"name": f["name"], "bytes": size, "sha256": sha})
        task.log(f"{f['name']}: {size:,} bytes, sha256 {sha}")
    task.tick(force=True, phase="download", bytes_done=done, bytes_total=total)
    version = (folder / "version.txt").read_text(errors="replace").strip()
    if version != r.version:
        raise TaskFailure(f"version.txt says {version!r}, not {r.version}", "version_mismatch", found=version[:40],
                          expected=r.version)
    names = {f["name"] for f in fetched}
    if missing := [g for g in _taxgroups_with_dna(folder)
                   if f"AMR_DNA-{g}.fa" not in names or f"AMR_DNA-{g}.tsv" not in names]:
        raise TaskFailure(f"taxgroup.tsv names nucleotide references for {', '.join(missing)} but the release folder "
                          "lacks their AMR_DNA files", "check_failed", detail="AMR_DNA files missing")
    argv = AmrfinderplusAdapter.index_argv(d.path, folder)
    tmp = staging / "tmp"
    tmp.mkdir()
    task.set_progress(phase="index")
    task.log("Indexing: " + " ".join(argv), flush=True)
    try:
        run_command(argv, cwd=staging, stderr_path=staging / INDEX_LOG, extra_env=env_for(d.path, tmp),
                    timeout_seconds=3600)
    except ToolExecutionError as exc:
        raise TaskFailure(f"amrfinder_index failed: {exc} {exc.stderr_tail[-400:]}", "check_failed",
                          detail="amrfinder_index") from exc
    index_log = (staging / INDEX_LOG).read_text(errors="replace")
    check = database_check(d.path, folder)
    if not check["ok"]:
        raise TaskFailure(f"AMRFinderPlus does not accept the indexed folder: {check['error']}", "check_failed",
                          detail=str(check["error"]))
    task.log(f"amrfinder --database_version: release {check['version']} accepted by AMRFinderPlus "
             f"{check['software']}", flush=True)
    found = _checked(task, "amrfinderplus", folder, r.version)
    manifest, _ = hash_files(folder_items(folder), lambda dn, t: task.tick(phase="manifest", bytes_done=dn,
                                                                            bytes_total=t))
    checksum = manifest_checksum(manifest)
    if task.cancel_requested(lock=True):
        raise TaskCancelled()
    for p in folder.iterdir():
        os.chmod(p, 0o444)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(folder, target)
    shutil.rmtree(staging)
    size = manifest_bytes(manifest)
    task.log(f"Installed in {svc._shown(target)}: {len(manifest)} files, {size:,} bytes ({fmt_bytes(size)}) with the "
             f"indexes; content checksum {checksum}")
    stamp = svc.now()
    r.status, r.version_source, r.verification_level = DatabaseStatus.installed, VersionSource.file, "full"
    r.size_bytes, r.checksum, r.manifest = size, checksum, manifest
    r.installed_at = r.verified_at = stamp
    found.path = str(target)
    r.details = {**(r.details or {}), "detection": svc._stored_detection(found), "file_count": len(manifest),
                 "release": {**release, "fetched": fetched, "checksums_published": False},
                 "index": {"argv": [os.path.basename(argv[0]), *argv[1:]], "amrfinder": d.path,
                           "amrfinder_version": d.version, "log": index_log[-2000:]},
                 "database_check": check}
    task.set_progress(phase="done", bytes_done=size, bytes_total=size)
    svc.ensure_default(task.db, r.kind)


def run_amrfinder_download(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _download, _download_cleanup)
