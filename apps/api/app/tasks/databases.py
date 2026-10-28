"""Worker tasks of the Database Manager.

Download: fetch the archive from the catalogue's official URL (resumed with an HTTP range request when a partial
file exists and the server honours it), compare its MD5 with the published one, unpack it with ARVA's own checks
(no absolute or '..' paths, nothing outside the expected top folder, no links leaving it, no special files), run
Bakta's folder check, record the SHA-256 of every file, then move the folder into place and delete the archive.
Verify: Bakta's folder check again and every file compared with that manifest (a registered folder gets its
manifest on its first verification).

Cancellation is read from the database about once a second; a cancelled or interrupted download keeps its partial
file so the next download resumes it.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import posixpath
import re
import shutil
import tarfile
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.db.session import SessionLocal
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase
from app.services import databases as svc
from app.services.capacity import fmt_bytes
from app.services.database_catalogue import CatalogueEntry, entry

CHUNK = 1 << 20
TICK_SECONDS = 1.0
SPACE_CHECK_BYTES = 256 * CHUNK
HTTP_TIMEOUT_SECONDS = 60
USER_AGENT = f"ARVA/{__version__} (Database Manager)"


class TaskFailure(Exception):
    """An expected failure with a user-facing reason."""


class TaskCancelled(Exception):
    pass


class UnsafeArchive(TaskFailure):
    pass


class Task:
    def __init__(self, db: Session, record: ReferenceDatabase):
        self.db = db
        self.record = record
        self.lines = (record.log_text or "").splitlines()
        self._last_tick = 0.0

    def log(self, message: str, flush: bool = False) -> None:
        self.lines.append(f"[{svc.now().isoformat(timespec='seconds')}] {message}")
        self.record.log_text = "\n".join(self.lines)
        if flush:
            self.db.commit()

    def set_progress(self, **fields) -> None:
        self.record.progress = {**(self.record.progress or {}), **fields, "updated_at": svc.now().isoformat()}

    def cancel_requested(self, lock: bool = False) -> bool:
        query = select(ReferenceDatabase.cancel_requested_at).where(ReferenceDatabase.id == self.record.id)
        with self.db.no_autoflush:
            return self.db.scalar(query.with_for_update() if lock else query) is not None

    def tick(self, force: bool = False, **fields) -> None:
        """Save progress and look for a cancellation, at most once per TICK_SECONDS unless forced."""
        t = time.monotonic()
        if not force and t - self._last_tick < TICK_SECONDS:
            return
        self._last_tick = t
        self.set_progress(**fields)
        self.db.commit()
        if self.cancel_requested():
            raise TaskCancelled()

    def ensure_room(self, needed: int) -> None:
        root = svc.databases_dir()
        if needed > (available := svc.available_bytes(root)):
            raise TaskFailure(str(svc.DatabaseSpaceError(needed, available, root)))


def _run(record_id: str, expected: DatabaseStatus, body: Callable[[Task], None],
         cleanup: Callable[[Task, BaseException], None]) -> str:
    db = SessionLocal()
    try:
        record = db.get(ReferenceDatabase, record_id, with_for_update=True)
        if record is None:
            raise LookupError(f"reference database {record_id} not found")
        if record.status is not expected:
            db.rollback()
            return record.status.value
        task = Task(db, record)
        try:
            if record.cancel_requested_at is not None:
                raise TaskCancelled()
            task.set_progress(phase="starting", started_at=svc.now().isoformat())
            task.log(f"Worker started ({expected.value}); ARVA {__version__}", flush=True)
            body(task)
        except BaseException as exc:
            db.rollback()
            record = db.get(ReferenceDatabase, record_id, populate_existing=True)
            task.record = record
            cleanup(task, exc)
            if isinstance(exc, TaskCancelled):
                record.status = svc.end_status(record)
                record.error_message = None
                task.log("Cancelled at the user's request")
            else:
                expected_failure = isinstance(exc, TaskFailure | svc.DatabaseError)
                record.status = DatabaseStatus.failed
                record.error_message = str(exc) if expected_failure else f"{type(exc).__name__}: {exc}"
                task.log(f"ERROR: {record.error_message}")
                if not expected_failure:
                    task.log(traceback.format_exc())
            task.set_progress(phase=record.status.value)
            task.log(f"Finished with status '{record.status.value}'")
            db.commit()
            if not isinstance(exc, Exception):
                raise
            return record.status.value
        task.log(f"Finished with status '{record.status.value}'")
        db.commit()
        return record.status.value
    finally:
        db.close()


# --- Download ---------------------------------------------------------------------------------------------------

class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (new.scheme, new.netloc) != (old.scheme, old.netloc):
            raise TaskFailure(f"the server redirected to {newurl}, outside {old.scheme}://{old.netloc}; ARVA "
                              "downloads only from the official address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, offset: int):
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    opener = urllib.request.build_opener(_SameOriginRedirect)
    return opener.open(urllib.request.Request(url, headers=headers), timeout=HTTP_TIMEOUT_SECONDS)


def fetch(task: Task, e: CatalogueEntry, part: Path) -> None:
    total = e.archive_bytes or 0
    offset = part.stat().st_size if part.exists() else 0
    if offset > total:
        part.unlink()
        offset = 0
    if offset == total:
        task.log(f"The archive was already downloaded completely ({total:,} bytes)")
        return
    task.ensure_room(total - offset + (e.extracted_bytes_estimate or 0))
    host = urlsplit(e.download_url or "").netloc
    try:
        resp = _open(e.download_url or "", offset)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset:
            task.log(f"The server refused to resume at byte {offset:,} (HTTP 416); downloading again from the start")
            part.unlink()
            return fetch(task, e, part)
        raise TaskFailure(f"{host} answered HTTP {exc.code} {exc.reason} for {e.download_url}") from exc
    except OSError as exc:
        raise TaskFailure(f"could not reach {host}: {getattr(exc, 'reason', exc)}") from exc
    with resp:
        if resp.status == 206:
            got = resp.headers.get("Content-Range", "")
            if got != f"bytes {offset}-{total - 1}/{total}":
                raise TaskFailure(f"the server's Content-Range {got!r} does not continue the partial file at byte "
                                  f"{offset:,} of {total:,}")
            mode = "ab"
            task.log(f"Resuming the download at byte {offset:,} of {total:,}")
        elif resp.status == 200:
            if offset:
                task.log("The server ignored the range request; downloading again from the start")
                offset = 0
            length = resp.headers.get("Content-Length")
            if length is not None and length.isdigit() and int(length) != total:
                raise TaskFailure(f"the server announces {int(length):,} bytes but the publisher's record gives "
                                  f"{total:,}; nothing was kept")
            mode = "wb"
            task.log(f"Downloading {total:,} bytes from {e.download_url}")
        else:
            raise TaskFailure(f"{host} answered HTTP {resp.status} for {e.download_url}")
        done, since_check = offset, 0
        task.tick(force=True, phase="download", bytes_done=done, bytes_total=total, resumed_from=offset)
        with open(part, mode) as out:
            while True:
                try:
                    chunk = resp.read(CHUNK)
                except (OSError, http.client.HTTPException) as exc:
                    raise TaskFailure(f"the download was interrupted at {done:,} of {total:,} bytes ({exc}); start "
                                      "it again to resume from there") from exc
                if not chunk:
                    break
                if done + len(chunk) > total:
                    out.close()
                    part.unlink()
                    raise TaskFailure("the server sent more bytes than the published size; the file was deleted")
                out.write(chunk)
                done += len(chunk)
                since_check += len(chunk)
                if since_check >= SPACE_CHECK_BYTES:
                    since_check = 0
                    out.flush()
                    task.ensure_room(total - done + (e.extracted_bytes_estimate or 0))
                task.tick(phase="download", bytes_done=done, bytes_total=total)
    if done != total:
        raise TaskFailure(f"the transfer ended at {done:,} of {total:,} bytes; start the download again to resume")
    task.tick(force=True, phase="download", bytes_done=done, bytes_total=total)
    task.log(f"Downloaded {total:,} bytes", flush=True)


def verify_md5(task: Task, e: CatalogueEntry, part: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    done = 0
    with open(part, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
            done += len(chunk)
            task.tick(phase="checksum", bytes_done=done, bytes_total=e.archive_bytes)
    got = digest.hexdigest()
    if got != e.checksum:
        part.unlink()
        raise TaskFailure(f"the MD5 of the downloaded archive is {got} but the published MD5 is {e.checksum} "
                          f"({'; '.join(e.checksum_sources)}). The archive was deleted; download it again")
    task.log(f"MD5 {got} matches the published checksum ({'; '.join(e.checksum_sources)})", flush=True)
    return got


# --- Safe extraction --------------------------------------------------------------------------------------------

def safe_member_path(name: str, top_dir: str) -> PurePosixPath:
    """The member's path inside the archive, or UnsafeArchive: absolute, with '..', or outside top_dir/."""
    if "\x00" in name or not name:
        raise UnsafeArchive(f"the archive has an invalid member name {name!r}")
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchive(f"the archive has an absolute path {name!r}; nothing was installed")
    parts = [p for p in PurePosixPath(name).parts if p != "."]
    if ".." in parts:
        raise UnsafeArchive(f"the archive member {name!r} contains '..'; nothing was installed")
    if not parts or parts[0] != top_dir:
        raise UnsafeArchive(f"the archive member {name!r} lies outside the expected folder {top_dir}/")
    return PurePosixPath(*parts)


def check_link_target(rel: PurePosixPath, linkname: str, top_dir: str) -> None:
    if not linkname or "\x00" in linkname or linkname.startswith("/"):
        raise UnsafeArchive(f"the link {rel} has an absolute or invalid target {linkname!r}")
    resolved = posixpath.normpath(posixpath.join(str(rel.parent), linkname))
    if resolved != top_dir and not resolved.startswith(top_dir + "/"):
        raise UnsafeArchive(f"the link {rel} points outside {top_dir}/ ({linkname!r}); nothing was installed")


class _CountingReader:
    def __init__(self, fh):
        self.fh = fh
        self.pos = 0

    def read(self, n: int = -1) -> bytes:
        data = self.fh.read(n)
        self.pos += len(data)
        return data


def extract(archive: Path, dest: Path, top_dir: str, on_progress: Callable[[int, int], None]) -> int:
    """Unpack a (compressed) tar archive into the empty folder `dest`, member by member, without the tarfile
    extraction helpers: only directories, regular files, hard links to earlier files and relative symbolic links
    that stay inside top_dir/ are accepted. Symbolic links are created last, so nothing is ever written through one.
    on_progress(compressed bytes read, bytes written). Returns the number of members."""
    dest.mkdir(parents=True, exist_ok=False)
    real_dest = os.path.realpath(dest)
    links: list[tuple[PurePosixPath, str]] = []
    count = written = 0
    with open(archive, "rb") as raw:
        counter = _CountingReader(raw)
        try:
            tar = tarfile.open(fileobj=counter, mode="r|*")
        except tarfile.TarError as exc:
            raise TaskFailure(f"the archive could not be read: {exc}") from exc
        with tar:
            try:
                for member in tar:
                    rel = safe_member_path(member.name, top_dir)
                    target = dest.joinpath(*rel.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isreg():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        src = tar.extractfile(member)
                        try:
                            out = open(target, "xb")
                        except FileExistsError:
                            raise UnsafeArchive(f"the archive member {member.name!r} appears twice") from None
                        with out:
                            while chunk := src.read(CHUNK):
                                out.write(chunk)
                                written += len(chunk)
                                on_progress(counter.pos, written)
                        os.chmod(target, 0o444)
                    elif member.issym():
                        check_link_target(rel, member.linkname, top_dir)
                        links.append((rel, member.linkname))
                    elif member.islnk():
                        source = dest.joinpath(*safe_member_path(member.linkname, top_dir).parts)
                        if source.is_symlink() or not source.is_file():
                            raise UnsafeArchive(f"the hard link {member.name!r} does not point to an earlier file")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.link(source, target)
                    else:
                        raise UnsafeArchive(f"the archive member {member.name!r} is a device or FIFO; not accepted")
                    count += 1
                    on_progress(counter.pos, written)
            except (tarfile.TarError, EOFError) as exc:
                raise TaskFailure(f"the archive is damaged: {exc}") from exc
            except OSError as exc:
                raise TaskFailure(f"the archive could not be unpacked: {exc}") from exc
    for rel, linkname in links:
        target = dest.joinpath(*rel.parts)
        if os.path.realpath(target.parent) != os.path.join(real_dest, *rel.parent.parts):
            raise UnsafeArchive(f"the link {rel} lies under another link; not accepted")
        if os.path.lexists(target):
            raise UnsafeArchive(f"the archive member {rel} appears twice")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(linkname, target)
    return count


# --- Manifest ---------------------------------------------------------------------------------------------------

def _walk(folder: Path) -> list[Path]:
    out = []
    for dirpath, dirs, files in os.walk(folder):
        dirs.sort()
        out.extend(Path(dirpath) / d for d in dirs if os.path.islink(os.path.join(dirpath, d)))
        out.extend(Path(dirpath) / f for f in sorted(files))
    return sorted(out)


def build_manifest(folder: Path, on_progress: Callable[[int, int], None]) -> list[dict]:
    """Path, size and SHA-256 of every file (links: their target), sorted by path."""
    paths = _walk(folder)
    total = sum(p.lstat().st_size for p in paths if not p.is_symlink())
    done = 0
    manifest = []
    for p in paths:
        rel = p.relative_to(folder).as_posix()
        if p.is_symlink():
            manifest.append({"path": rel, "link": os.readlink(p)})
            continue
        digest = hashlib.sha256()
        size = 0
        with open(p, "rb") as fh:
            while chunk := fh.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
                done += len(chunk)
                on_progress(done, total)
        manifest.append({"path": rel, "size": size, "sha256": digest.hexdigest()})
    return manifest


def manifest_checksum(manifest: list[dict]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def manifest_bytes(manifest: list[dict]) -> int:
    return sum(m.get("size", 0) for m in manifest)


def compare_manifests(old: list[dict], new: list[dict]) -> dict[str, list[str]]:
    before = {m["path"]: m for m in old}
    after = {m["path"]: m for m in new}
    return {
        "missing": sorted(set(before) - set(after)),
        "changed": sorted(p for p in set(before) & set(after) if before[p] != after[p]),
        "extra": sorted(set(after) - set(before)),
    }


def amrfinder_info(folder: Path) -> dict | None:
    """The AMRFinderPlus data Bakta's AMR expert system reads (amrfinderplus-db/latest), if the folder has them."""
    latest = folder / "amrfinderplus-db" / "latest"
    real = os.path.realpath(latest)
    if not latest.is_dir() or os.path.commonpath([real, os.path.realpath(folder)]) != os.path.realpath(folder):
        return None

    def first_line(name: str) -> str | None:
        try:
            return (latest / name).read_text(encoding="utf-8", errors="replace")[:200].strip() or None
        except OSError:
            return None

    return {"latest": os.readlink(latest) if latest.is_symlink() else "latest", "version": first_line("version.txt"),
            "database_format": first_line("database_format_version.txt")}


# --- Tasks ------------------------------------------------------------------------------------------------------

def _download(task: Task) -> None:
    r = task.record
    e = entry(r.key)
    if e.status != "available" or e.version != r.version:
        raise TaskFailure(f"the catalogue no longer offers {r.name} {r.version}")
    root = svc.databases_dir()
    target = root / e.install_dir
    if r.path != str(target):
        raise TaskFailure(f"unexpected install folder {r.path}")
    task.log(f"Database: {e.name} {e.version} ({e.release_date}, doi:{e.doi}); source {e.download_url}; licence "
             f"{e.licence}, accepted at {((r.details or {}).get('confirmation') or {}).get('at')}")
    downloads = svc.downloads_dir(r.id)
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / f"{e.filename}.part"
    fetch(task, e, part)
    md5 = verify_md5(task, e, part)
    staging = svc.staging_dir(r.id)
    shutil.rmtree(staging, ignore_errors=True)
    estimate = e.extracted_bytes_estimate or 0
    since_check = [0]

    def extracting(read: int, written: int) -> None:
        if written - since_check[0] >= SPACE_CHECK_BYTES:
            since_check[0] = written
            task.ensure_room(max(0, estimate - written))
        task.tick(phase="extract", bytes_done=read, bytes_total=e.archive_bytes, written_bytes=written)

    task.log(f"Unpacking into {staging}", flush=True)
    members = extract(part, staging, e.top_dir or "", extracting)
    unpacked = staging / (e.top_dir or "")
    if not unpacked.is_dir():
        raise TaskFailure(f"the archive has no {e.top_dir}/ folder")
    info = svc.check_bakta_dir(unpacked)
    if svc.bakta_version(info) != e.version or info["type"] != e.db_type:
        raise TaskFailure(f"the archive holds Bakta database {svc.bakta_version(info)} ({info['type']}), not "
                          f"{e.version} ({e.db_type})")
    task.log(f"Unpacked {members} members; Bakta's folder check passed: version.json {json.dumps(info)}", flush=True)
    manifest = build_manifest(unpacked, lambda d, t: task.tick(phase="manifest", bytes_done=d, bytes_total=t))
    checksum = manifest_checksum(manifest)
    if task.cancel_requested(lock=True):
        raise TaskCancelled()
    if target.exists():
        task.log(f"Replacing this database's previous folder {target}")
        os.rename(target, staging / "previous")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(unpacked, target)
    shutil.rmtree(downloads)
    shutil.rmtree(staging)
    size = manifest_bytes(manifest)
    task.log(f"Installed in {target}: {len(manifest)} files, {size:,} bytes ({fmt_bytes(size)}); content checksum "
             f"{checksum}. The archive was deleted after the verified extraction")
    amr = amrfinder_info(target)
    task.log(f"AMRFinderPlus data in amrfinderplus-db/latest: {amr['version']} (database format "
             f"{amr['database_format']})" if amr else "This archive has no amrfinderplus-db/latest folder")
    stamp = svc.now()
    r.status = DatabaseStatus.installed
    r.size_bytes, r.checksum, r.archive_checksum = size, checksum, f"md5:{md5}"
    r.installed_at = r.verified_at = stamp
    r.details = {
        **(r.details or {}), "version_json": info, "manifest": manifest, "members": members,
        "archive": {"url": e.download_url, "filename": e.filename, "bytes": e.archive_bytes, "md5": md5,
                    "checksum_sources": list(e.checksum_sources), "deleted_after_extraction": True},
        "amrfinderplus_db": amr,
    }
    task.set_progress(phase="done", bytes_done=size, bytes_total=size)


def _download_cleanup(task: Task, _exc: BaseException) -> None:
    shutil.rmtree(svc.staging_dir(task.record.id), ignore_errors=True)


def run_database_download(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _download, _download_cleanup)


def _verify(task: Task) -> None:
    r = task.record
    folder = Path(r.path or "")
    if not folder.is_dir():
        raise TaskFailure(f"the database folder {folder} no longer exists")
    info = svc.check_bakta_dir(folder)
    if r.version and svc.bakta_version(info) != r.version:
        raise TaskFailure(f"version.json now says {svc.bakta_version(info)}; this database was recorded as "
                          f"{r.version}")
    task.log(f"Bakta's folder check passed for {folder}; computing the SHA-256 of every file", flush=True)
    manifest = build_manifest(folder, lambda d, t: task.tick(phase="verify", bytes_done=d, bytes_total=t))
    old = (r.details or {}).get("manifest")
    stamp = svc.now()
    if old is None:
        r.checksum = manifest_checksum(manifest)
        r.size_bytes = manifest_bytes(manifest)
        r.installed_at = stamp
        r.details = {**(r.details or {}), "version_json": info, "manifest": manifest}
        task.log(f"Recorded {len(manifest)} files, {r.size_bytes:,} bytes; content checksum {r.checksum}. There is "
                 "no published checksum for an unpacked folder, so this only lets later checks detect changes")
    else:
        diff = compare_manifests(old, manifest)
        if diff["missing"] or diff["changed"]:
            names = ", ".join((diff["changed"] + diff["missing"])[:5])
            raise TaskFailure(f"integrity check failed: {len(diff['changed'])} file(s) changed and "
                              f"{len(diff['missing'])} missing since installation ({names})")
        if diff["extra"]:
            task.log(f"{len(diff['extra'])} file(s) added since installation (not part of the recorded database): "
                     f"{', '.join(diff['extra'][:5])}")
        task.log(f"All {len(old)} recorded files are unchanged (SHA-256)")
    r.details = {**(r.details or {}), "amrfinderplus_db": amrfinder_info(folder),
                 "last_verification": {"at": stamp.isoformat(), "files": len(manifest)}}
    r.verified_at = stamp
    r.error_message = None
    r.status = DatabaseStatus.installed if r.origin is DatabaseOrigin.download else DatabaseStatus.registered
    task.set_progress(phase="done")


def run_database_verify(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.verifying, _verify, lambda _t, _e: None)
