"""Worker tasks: VFDB's full set B as an ABRicate database (app.services.vfdb_db).

Download: VFDB_setB_nt.fas.gz is fetched over HTTPS into the database folder's download area (a stopped download
resumes where the server allows it). Build from a file the user has: the file is only read. Then, for both:

1. the file must be gzip (or plain FASTA for a file of the user's) whose stored name is VFDB's and whose stored time
   is the date confirmed (VFDB's security filter can answer with a web page, which is refused here);
2. it is converted as abricate-get_db converts set A (arva_tools.abricate_vfdb: the same header rewrite, reverse
   complements, removal of identical sequences, sorting; gene names with spaces get "_" in the identifier only), and
   gzip checks its CRC as it is read;
3. `sequences` is indexed with the makeblastdb of ABRicate's environment, as abricate-get_db indexes it
   (`makeblastdb -in sequences -title vfdb -dbtype nucl -hash_index -logfile ...`, an argument list);
4. the index is checked with that environment's blastdbcmd (ABRicate's own check before a run): the number of
   sequences must be the number written;
5. ARVA_DATABASE.json records the set, the version, the source (URL or path, size, Last-Modified or gzip time), the
   SHA-256 of the downloaded file, of the FASTA in it and of `sequences`, the conversion's counts and the indexing
   command; the folder is recognised as the vfdb kind, the SHA-256 of every file is recorded, and it is moved into
   place. The layout is <database folder>/<folder>/vfdb_set<X>/ so that ABRicate reads it with --datadir
   <database folder>/<folder> --db vfdb_set<X>; the downloaded file stays in vfdb_set<X>/src/.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import zlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from arva_tools import abricate as abr
from arva_tools import abricate_vfdb as conv
from arva_tools.registry import detect

from app import __version__
from app.models import DatabaseStatus, VersionSource
from app.services import databases as svc
from app.services import vfdb_db
from app.services.database_detect import ARVA_DATABASE_FILE
from app.tasks.databases import (
    CHUNK,
    Task,
    TaskCancelled,
    TaskFailure,
    _checked,
    _download_cleanup,
    _run,
    fetch,
    fmt_bytes,
    folder_items,
    hash_files,
    manifest_bytes,
    manifest_checksum,
)

TOOL_TIMEOUT = 1800
_COUNT = re.compile(r"\b([\d,]+)\s+sequences;")
SETS_BY_NAME = {name: s for s, name in conv.SETS.items()}


@dataclass(frozen=True)
class _Archive:
    """What fetch() reads of a catalogue entry, for the confirmed file."""
    download_url: str
    archive_bytes: int
    extracted_bytes_estimate: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _abricate_bin(name: str) -> str:
    """A program of ABRicate's environment (makeblastdb, blastdbcmd): the one ABRicate itself runs."""
    tool = detect("abricate")
    if not tool.path:
        raise TaskFailure(vfdb_db.MESSAGES["vfdb_no_abricate"], "vfdb_no_abricate")
    exe = Path(os.path.realpath(tool.path)).parent / name
    if not exe.is_file():
        raise TaskFailure(f"{name} is not in ABRicate's environment ({exe.parent})", "vfdb_no_abricate")
    return str(exe)


def _check_file(task: Task, path: Path, expected_set: str, expected_day: str | None, compressed_required: bool) -> dict:
    """The gzip header (or plain FASTA) of the file to convert, against what was confirmed."""
    head = conv.gzip_header(path)
    with open(path, "rb") as fh:
        start = fh.read(1)
    if head is None:
        if compressed_required or start != b">":
            raise TaskFailure(f"{path.name} is neither gzip nor FASTA (VFDB's server may have sent a web page instead "
                              "of the file); nothing was built", "vfdb_bad_file", detail="not gzip or FASTA")
        task.log(f"{path.name} is plain FASTA")
        return {"compressed": False}
    name = SETS_BY_NAME.get(head.get("name") or "")
    if head.get("name") and name != expected_set:
        raise TaskFailure(f"the file's stored name is {head['name']}, not {conv.SETS[expected_set]}", "vfdb_bad_file",
                          detail=f"stored name {head['name']}")
    day = (head.get("mtime") or "")[:10]
    if expected_day and day and abs((date.fromisoformat(day) - date.fromisoformat(expected_day)).days) > 1:
        # VFDB gzips each file a few seconds before the server dates it (Last-Modified); a day either side allows for
        # midnight, anything else is another build than the one confirmed.
        raise TaskFailure(f"the file is dated {head['mtime']} (gzip header), not {expected_day} as confirmed",
                          "version_mismatch", found=day, expected=expected_day)
    task.log(f"gzip header: name {head.get('name') or '(none)'}, stored time {head.get('mtime') or '(none)'}")
    return {"compressed": True, "gzip_name": head.get("name"), "gzip_mtime": head.get("mtime")}


def _index(task: Task, folder: Path, records: int) -> dict:
    makeblastdb = _abricate_bin("makeblastdb")
    (folder / "src").mkdir(exist_ok=True)
    argv = conv.makeblastdb_argv(makeblastdb, folder / "sequences", folder / "src" / "makeblastdb.log")
    task.log("Indexing as abricate-get_db does: " + " ".join(argv), flush=True)
    env = {**os.environ, **abr.env_for(makeblastdb)}
    try:
        done = subprocess.run(argv, cwd=folder, capture_output=True, text=True, timeout=TOOL_TIMEOUT, env=env,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TaskFailure(f"makeblastdb could not run: {exc}", "vfdb_index_failed", detail=str(exc)) from exc
    if done.returncode != 0:
        log = (folder / "src" / "makeblastdb.log")
        tail = log.read_text(errors="replace")[-500:] if log.is_file() else (done.stderr or "")[-500:]
        raise TaskFailure(f"makeblastdb stopped (exit status {done.returncode}): {tail.strip()}", "vfdb_index_failed",
                          detail=tail.strip()[:300])
    blastdbcmd = _abricate_bin("blastdbcmd")
    info = subprocess.run([blastdbcmd, "-info", "-db", str(folder / "sequences")], capture_output=True, text=True,
                          timeout=120, env=env, check=False)
    m = _COUNT.search(info.stdout)
    found = int(m.group(1).replace(",", "")) if m else None
    if info.returncode != 0 or found != records:
        raise TaskFailure(f"the BLAST index holds {found} sequences, not the {records} written", "vfdb_index_failed",
                          detail=f"{found} indexed, {records} written")
    version = subprocess.run([makeblastdb, "-version"], capture_output=True, text=True, timeout=60, env=env,
                             check=False).stdout.strip().splitlines()
    task.log(f"blastdbcmd -info: {found:,} sequences, as written", flush=True)
    return {"argv": [Path(argv[0]).name, *[a.replace(str(folder) + "/", "") for a in argv[1:]]],
            "makeblastdb": version[0] if version else None, "sequences": found}


def _build(task: Task, source: Path, kept_source: Path | None, check: dict, source_sha: str) -> None:
    """Convert, index, check and install; `kept_source` is the downloaded file to keep in src/ (None: the user's
    file, only read)."""
    r = task.record
    info = (r.details or {}).get("vfdb") or {}
    s = info.get("set") or "B"
    root = svc.destination_root(r)
    target = Path(r.path or "")
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    unpacked = staging / "unpacked"
    folder = unpacked / target.name
    folder.mkdir(parents=True)
    task.tick(force=True, phase="convert")
    task.log(f"Converting {source.name} to ABRicate's format as abricate-get_db converts VFDB (header "
             f">vfdb~~~gene~~~accession~~~ description)", flush=True)
    try:
        result = conv.convert_file(source, folder / "sequences")
    except (OSError, EOFError, zlib.error, gzip.BadGzipFile, ValueError) as exc:
        raise TaskFailure(f"{source.name} could not be read as VFDB's FASTA: {exc}", "vfdb_bad_file",
                          detail=str(exc)[:300]) from exc
    if result.records_written == 0:
        raise TaskFailure(f"{source.name} holds no sequences", "vfdb_bad_file", detail="no sequences")
    task.log(f"Read {result.records_read:,} records; wrote {result.records_written:,} ({result.duplicates_dropped:,} "
             f"identical sequences dropped, {result.reverse_complemented:,} reverse-complemented, "
             f"{result.without_accession:,} without an accession, {result.genes:,} gene names). FASTA SHA-256 "
             f"{result.sha256_fasta}; sequences SHA-256 {result.sha256_sequences}")
    if result.spaces_replaced:
        task.log(f"{len(result.spaces_replaced)} gene names have spaces, written with '_' in the identifier so that "
                 f"ABRicate reports them whole (abricate-get_db would cut them): "
                 f"{', '.join(result.spaces_replaced[:10])}")
    if task.cancel_requested():
        raise TaskCancelled()
    if kept_source is not None:
        (folder / "src").mkdir(exist_ok=True)
        shutil.copyfile(kept_source, folder / "src" / vfdb_db.FILE)
    task.tick(force=True, phase="index")
    index = _index(task, folder, result.records_written)
    src = info.get("source") or {}
    meta = {"kind": "vfdb", "format": "abricate", "set": s, "dataset": vfdb_db.DATASETS[s], "version": r.version,
            "version_from": "last_modified" if src.get("url") else ("gzip_mtime" if check.get("gzip_mtime")
                                                                    and r.version_source is VersionSource.file
                                                                    else "declared"),
            "source": {**src, "sha256": source_sha, **{k: v for k, v in check.items() if k != "compressed"}},
            "fasta": {"sha256": result.sha256_fasta, "bytes": result.fasta_bytes, "records": result.records_read},
            "sequences": {"sha256": result.sha256_sequences, "bytes": result.sequences_bytes,
                          "records": result.records_written, "genes": result.genes},
            "conversion": {**result.as_dict(), "method": "abricate-get_db get_vfdb (ABRicate 1.4.0), gene-name spaces "
                                                         "written as '_'"},
            "index": index, "abricate": {"datadir": "..", "db": target.name},
            "licence": vfdb_db.kinds.BY_KEY["vfdb"].licence, "built_by": f"ARVA {__version__}",
            "built_at": svc.now().isoformat()}
    (folder / ARVA_DATABASE_FILE).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    found = _checked(task, "vfdb", folder, r.version, variant="abricate_arva")
    manifest, _ = hash_files(folder_items(folder), lambda d, t: task.tick(phase="manifest", bytes_done=d,
                                                                          bytes_total=t))
    checksum = manifest_checksum(manifest)
    if task.cancel_requested(lock=True):
        raise TaskCancelled()
    target.parent.parent.mkdir(parents=True, exist_ok=True)
    os.rename(unpacked, target.parent)
    shutil.rmtree(staging)
    downloads = svc.downloads_dir(r.id, root)
    shutil.rmtree(downloads, ignore_errors=True)
    size = manifest_bytes(manifest)
    task.log(f"Installed in {svc._shown(target)}: {len(manifest)} files, {size:,} bytes ({fmt_bytes(size)}); content "
             f"checksum {checksum}. ABRicate reads it with --datadir {svc._shown(target.parent)} --db {target.name}")
    stamp = svc.now()
    r.status, r.verification_level = DatabaseStatus.installed, "full"
    r.version_source = r.version_source or VersionSource.file
    r.size_bytes, r.checksum, r.archive_checksum, r.manifest = size, checksum, f"sha256:{source_sha}", manifest
    r.installed_at = r.verified_at = stamp
    found.path = str(target)
    r.details = {**(r.details or {}), "detection": svc._stored_detection(found), "file_count": len(manifest),
                 "vfdb": {**info, **{k: meta[k] for k in ("source", "fasta", "sequences", "conversion", "index",
                                                          "built_by", "built_at", "version_from")}}}
    task.set_progress(phase="done", bytes_done=size, bytes_total=size)
    svc.ensure_default(task.db, r.kind)


def _download(task: Task) -> None:
    r = task.record
    src = ((r.details or {}).get("vfdb") or {}).get("source") or {}
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents or not src.get("url") or not src.get("bytes"):
        raise TaskFailure(f"unexpected install folder {r.path}")
    confirmation = (r.details or {}).get("confirmation") or {}
    task.log(f"{r.name}, version {r.version} (Last-Modified {src.get('last_modified')}), {src['bytes']:,} bytes from "
             f"{src['url']}; licence and citation accepted at {confirmation.get('at')}; into {svc._shown(target)}. "
             "VFDB publishes no checksum: ARVA records the SHA-256 of what it receives", flush=True)
    downloads = svc.downloads_dir(r.id, root)
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / f"{vfdb_db.FILE}.part"
    fetch(task, _Archive(src["url"], int(src["bytes"]), int(src["bytes"]) * vfdb_db.BUILT_PER_COMPRESSED), part)
    sha = _sha256(part)
    task.log(f"SHA-256 of {vfdb_db.FILE}: {sha}")
    day = (src.get("last_modified_utc") or "")[:10] or r.version
    check = _check_file(task, part, "B", day, compressed_required=True)
    _build(task, part, part, check, sha)


def _from_file(task: Task) -> None:
    r = task.record
    info = (r.details or {}).get("vfdb") or {}
    src = info.get("source") or {}
    source = Path(src.get("path") or "")
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents or not source.is_file():
        raise TaskFailure(f"the file {svc._shown(source)} or the folder {svc._shown(target)} is not where it was "
                          "planned", "folder_missing", folder=svc._shown(source))
    if source.stat().st_size != src.get("bytes"):
        raise TaskFailure(f"{source.name} changed size since you confirmed it ({source.stat().st_size:,} bytes, not "
                          f"{src.get('bytes'):,})", "vfdb_bad_file", detail="size changed")
    task.ensure_room(int(src["bytes"]) * vfdb_db.BUILT_PER_COMPRESSED)
    task.log(f"Building {r.name} {r.version} from {svc._shown(source)} ({src['bytes']:,} bytes; the file is only read) "
             f"into {svc._shown(target)}", flush=True)
    sha = _sha256(source)
    task.log(f"SHA-256 of {source.name}: {sha}")
    expected = r.version if r.version_source is VersionSource.file else None
    check = _check_file(task, source, info.get("set") or "B", expected, compressed_required=False)
    _build(task, source, None, check, sha)


def _cleanup(task: Task, exc: BaseException) -> None:
    _download_cleanup(task, exc)


def run_vfdb_download(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _download, _cleanup)


def run_vfdb_build(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.extracting, _from_file, _cleanup)

