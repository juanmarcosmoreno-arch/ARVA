"""Worker tasks of the Database Manager.

Download: fetch the archive from the catalogue's official URL (resumed with an HTTP range request when a partial
file exists and the server honours it), compare its MD5 with the published one, unpack it with ARVA's own checks
(no absolute or '..' paths, nothing outside the expected top folder, no links leaving it, no special files), run the
kind's folder check (Bakta's own for Bakta), record the SHA-256 of every file (and compare the publisher's per-file
MD5s where it lists them), then move the folder into place and delete the archive.
Extract: copy an NCBI Datasets package out of its zip into a database folder with the same kind of checks (the zip is
only read), then compare every file with the package's md5sum.txt.
Verify (full): the kind's check again and every file compared with the manifest (a registered folder gets its
manifest on its first full verification).

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
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.core import errorlog
from app.db.session import SessionLocal
from app.models import DatabaseStatus, ReferenceDatabase, VersionSource
from app.services import database_detect as detection
from app.services import databases as svc
from app.services import reference_collections as rc
from app.services.capacity import fmt_bytes
from app.services.database_catalogue import CatalogueEntry, entry

CHUNK = 1 << 20
TICK_SECONDS = 1.0
SPACE_CHECK_BYTES = 256 * CHUNK
HTTP_TIMEOUT_SECONDS = 60
USER_AGENT = f"ARVA/{__version__} (Database Manager)"


class TaskFailure(Exception):
    """An expected failure with a user-facing reason; `code` and `params` name it for the interface
    (database.error.<code>, recorded in error_detail)."""

    def __init__(self, message: str, code: str | None = None, **params: str | int):
        super().__init__(message)
        self.code = code
        self.params = params


class TaskCancelled(Exception):
    pass


class UnsafeArchive(TaskFailure):
    pass


class DiskNotConnected(TaskFailure):
    """The folder's disk is not connected: the database keeps the status it had (it is not marked failed)."""


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
        root = svc.destination_root(self.record)
        if needed > (available := svc.available_bytes(root)):
            raise TaskFailure(str(svc.DatabaseSpaceError(needed, available, root)), "no_space", needed_bytes=needed,
                              available_bytes=available)


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
                record.error_message = record.error_detail = None
                task.log("Cancelled at the user's request")
            else:
                expected_failure = isinstance(exc, TaskFailure | svc.DatabaseError)
                record.status = svc.end_status(record) if isinstance(exc, DiskNotConnected) else DatabaseStatus.failed
                record.error_message = str(exc) if expected_failure else f"{type(exc).__name__}: {exc}"
                code = getattr(exc, "code", None)
                record.error_detail = {"code": code, "params": exc.params} if code else None
                task.log(f"ERROR: {record.error_message}")
                if not expected_failure:
                    task.log(traceback.format_exc())
            task.set_progress(phase=record.status.value)
            task.log(f"Finished with status '{record.status.value}'")
            db.commit()
            cancelled = isinstance(exc, TaskCancelled)
            errorlog.record("job", "info" if cancelled else "error",
                            (record.error_detail or {}).get("code") or ("job_cancelled" if cancelled else "job_failed"),
                            record.error_message or None,
                            params={"job_type": f"database_{expected.value}", **((record.error_detail or {}).get("params") or {})},
                            exc=None if cancelled else exc,
                            job={"id": record.id, "type": f"database_{expected.value}", "status": record.status.value,
                                 "database": {"key": record.key, "kind": record.kind, "version": record.version}})
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
        raise TaskFailure(f"{host} answered HTTP {exc.code} {exc.reason} for {e.download_url}", "http_error",
                          host=host, status=exc.code) from exc
    except OSError as exc:
        raise TaskFailure(f"could not reach {host}: {getattr(exc, 'reason', exc)}", "unreachable", host=host,
                          detail=str(getattr(exc, "reason", exc))) from exc
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
            raise TaskFailure(f"{host} answered HTTP {resp.status} for {e.download_url}", "http_error", host=host,
                              status=resp.status)
        done, since_check = offset, 0
        task.tick(force=True, phase="download", bytes_done=done, bytes_total=total, resumed_from=offset)
        with open(part, mode) as out:
            while True:
                try:
                    chunk = resp.read(CHUNK)
                except (OSError, http.client.HTTPException) as exc:
                    raise TaskFailure(f"the download was interrupted at {done:,} of {total:,} bytes ({exc}); start "
                                      "it again to resume from there", "interrupted", done_bytes=done,
                                      total_bytes=total) from exc
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
        raise TaskFailure(f"the transfer ended at {done:,} of {total:,} bytes; start the download again to resume",
                          "interrupted", done_bytes=done, total_bytes=total)
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
                          f"({'; '.join(e.checksum_sources)}). The archive was deleted; download it again",
                          "md5_mismatch", got=got, expected=e.checksum)
    task.log(f"MD5 {got} matches the published checksum ({'; '.join(e.checksum_sources)})", flush=True)
    return got


# --- Safe extraction --------------------------------------------------------------------------------------------

def safe_member_path(name: str, top_dir: str | None) -> PurePosixPath | None:
    """The member's path inside the archive, or UnsafeArchive: absolute, with '..', or outside top_dir/ (None: the
    archive's members lie at its root). None for the root entry itself ("./")."""
    if "\x00" in name or not name:
        raise UnsafeArchive(f"the archive has an invalid member name {name!r}")
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchive(f"the archive has an absolute path {name!r}; nothing was installed")
    parts = [p for p in PurePosixPath(name).parts if p != "."]
    if ".." in parts:
        raise UnsafeArchive(f"the archive member {name!r} contains '..'; nothing was installed")
    if top_dir is None:
        return PurePosixPath(*parts) if parts else None
    if not parts or parts[0] != top_dir:
        raise UnsafeArchive(f"the archive member {name!r} lies outside the expected folder {top_dir}/")
    return PurePosixPath(*parts)


def check_link_target(rel: PurePosixPath, linkname: str, top_dir: str | None) -> None:
    if not linkname or "\x00" in linkname or linkname.startswith("/"):
        raise UnsafeArchive(f"the link {rel} has an absolute or invalid target {linkname!r}")
    resolved = posixpath.normpath(posixpath.join(str(rel.parent), linkname))
    if top_dir is None:
        if resolved == ".." or resolved.startswith("../") or resolved == ".":
            raise UnsafeArchive(f"the link {rel} points outside the archive ({linkname!r}); nothing was installed")
        return
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


def extract(archive: Path, dest: Path, top_dir: str | None, on_progress: Callable[[int, int], None]) -> int:
    """Unpack a (compressed) tar archive into the empty folder `dest`, member by member, without the tarfile
    extraction helpers: only directories, regular files, hard links to earlier files and relative symbolic links
    that stay inside top_dir/ (or the archive, without a top folder) are accepted. Symbolic links are created last,
    so nothing is ever written through one. on_progress(compressed bytes read, bytes written). Returns the number of
    members."""
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
                    if rel is None:
                        if not member.isdir():
                            raise UnsafeArchive(f"the archive member {member.name!r} is not a folder")
                        continue
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
                        linked = safe_member_path(member.linkname, top_dir)
                        if linked is None:
                            raise UnsafeArchive(f"the hard link {member.name!r} does not point to an earlier file")
                        source = dest.joinpath(*linked.parts)
                        if source.is_symlink() or not source.is_file():
                            raise UnsafeArchive(f"the hard link {member.name!r} does not point to an earlier file")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.link(source, target)
                    else:
                        raise UnsafeArchive(f"the archive member {member.name!r} is a device or FIFO; not accepted")
                    count += 1
                    on_progress(counter.pos, written)
            except (tarfile.TarError, EOFError) as exc:
                raise TaskFailure(f"the archive is damaged: {exc}", "archive_damaged", detail=str(exc)) from exc
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


def folder_items(folder: Path) -> list[tuple[str, Path]]:
    return [(p.relative_to(folder).as_posix(), p) for p in _walk(folder)]


def hash_files(items: list[tuple[str, Path]], on_progress: Callable[[int, int], None],
               md5_of: frozenset[str] = frozenset()) -> tuple[list[dict], dict[str, str]]:
    """Path (the item's key), size and SHA-256 of every file (links: their target), sorted by key; and the MD5 of
    the keys in md5_of, read in the same pass."""
    items = sorted(items)
    total = sum(p.lstat().st_size for _, p in items if not p.is_symlink())
    done = 0
    manifest, md5s = [], {}
    for key, p in items:
        if p.is_symlink():
            manifest.append({"path": key, "link": os.readlink(p)})
            continue
        digest = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False) if key in md5_of else None
        size = 0
        with open(p, "rb") as fh:
            while chunk := fh.read(CHUNK):
                digest.update(chunk)
                if md5 is not None:
                    md5.update(chunk)
                size += len(chunk)
                done += len(chunk)
                on_progress(done, total)
        manifest.append({"path": key, "size": size, "sha256": digest.hexdigest()})
        if md5 is not None:
            md5s[key] = md5.hexdigest()
    return manifest, md5s


def build_manifest(folder: Path, on_progress: Callable[[int, int], None]) -> list[dict]:
    """Path, size and SHA-256 of every file in a folder (links: their target), sorted by path."""
    return hash_files(folder_items(folder), on_progress)[0]


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


# --- What a database's files must be ----------------------------------------------------------------------------

def _checked(task: Task, kind: str, folder: Path, expected_version: str | None = None,
             variant: str | None = None) -> detection.Detection:
    """The kind's folder check on an unpacked or registered database (Bakta's own check for Bakta)."""
    found = next((d for d in detection.detect(folder, svc.list_context()) if d.kind == kind), None)
    if found is None:
        raise TaskFailure(f"the folder is not a {kind} database ARVA recognises", "not_recognised")
    if not found.ok:
        problems = "; ".join(p.text for p in found.problems if p.blocking)
        raise TaskFailure(f"the {kind} folder check failed: {problems}", "check_failed", detail=problems)
    if kind == "bakta":
        svc.check_bakta_dir(folder)
    if expected_version is not None and found.version != expected_version:
        raise TaskFailure(f"the files say version {found.version}, not {expected_version}", "version_mismatch",
                          found=str(found.version), expected=expected_version)
    if variant is not None and found.variant != variant:
        raise TaskFailure(f"the files are the {found.variant} variant, not {variant}", "version_mismatch",
                          found=str(found.variant), expected=variant)
    task.log(f"Folder check passed ({kind}): version {found.version or '(not stated)'}"
             + (f" from {found.version_file}" if found.version_file else ""), flush=True)
    return found


def published_checksums(record: ReferenceDatabase, folder: Path, found: detection.Detection | None = None) -> dict:
    """The publisher's MD5 of each file, by manifest key, where the database lists them: a Kraken 2 index's .md5
    file, CheckM2's CONTENTS.json, an NCBI Datasets package's md5sum.txt."""
    det = found.as_dict() if found is not None else ((record.details or {}).get("detection") or {})
    facts = det.get("facts") or {}
    if record.kind == "kraken2" and (name := facts.get("published_md5")):
        return {k: v for k, v in detection.published_md5s(folder / name).items() if (folder / k).is_file()}
    if record.kind == "checkm2" and (listed := facts.get("contents_md5")):
        return {k: v for k, v in listed.items() if (folder / k).is_file()}
    if record.kind == "reference_genomes":
        roots = [Path(facts.get("package_root") or folder)] if det.get("variant") == "ncbi_package" else \
            [Path(p) for p in facts.get("packages", [])]
        return {str(root / k): v for root in roots for k, v in rc.package_md5s(root).items()}
    return {}


def _items(record: ReferenceDatabase, path: Path) -> list[tuple[str, Path]]:
    """What the full checksum covers: a reference collection's genomes and its own files (by absolute path), a
    single-file database's file, or every file of the folder."""
    if record.kind == "reference_genomes":
        genomes = [Path(g["path"]) for g in record.inventory or []]
        det = (record.details or {}).get("detection") or {}
        own = [path] if path.is_file() else [Path((det.get("facts") or {}).get("package_root") or path) / f["path"]
                                               for f in det.get("files", []) if f.get("present")]
        return sorted({(str(p), p) for p in (*genomes, *own)})
    if path.is_file():
        return [(path.name, path)]
    return folder_items(path)


def _compare_published(task: Task, published: dict[str, str], md5s: dict[str, str]) -> None:
    if not published:
        return
    bad = sorted(k for k, v in published.items() if k in md5s and md5s[k] != v)
    absent = sorted(k for k in published if k not in md5s)
    if bad:
        names = ", ".join(PurePosixPath(b).name for b in bad[:5])
        raise TaskFailure(f"{len(bad)} file(s) differ from the publisher's MD5 ({names})", "published_mismatch",
                          count=len(bad), names=names)
    task.log(f"{len(md5s)} file(s) match the publisher's MD5" + (f"; {len(absent)} listed file(s) are not part of "
                                                                 "this copy" if absent else ""), flush=True)


def _checkm2_version(manifest: list[dict], found: detection.Detection) -> str | None:
    rel = found.facts.get("dmnd")
    sha = next((m.get("sha256") for m in manifest if m["path"] == rel), None)
    return detection.CHECKM2_DMND_SHA256.get(sha or "")


# --- Tasks ------------------------------------------------------------------------------------------------------

def _download(task: Task) -> None:
    r = task.record
    e = entry(r.key)
    if e.version != r.version:
        raise TaskFailure(f"the catalogue no longer offers {r.name} {r.version}")
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents:
        raise TaskFailure(f"unexpected install folder {r.path}")
    task.log(f"Database: {e.name} {e.version} ({e.release_date}{', doi:' + e.doi if e.doi else ''}); source "
             f"{e.download_url}; licence {e.licence}, accepted at "
             f"{((r.details or {}).get('confirmation') or {}).get('at')}; into {svc._shown(target)}")
    downloads = svc.downloads_dir(r.id, root)
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / f"{e.filename}.part"
    fetch(task, e, part)
    md5 = verify_md5(task, e, part)
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    estimate = e.extracted_bytes_estimate
    since_check = [0]

    def extracting(read: int, written: int) -> None:
        if written - since_check[0] >= SPACE_CHECK_BYTES:
            since_check[0] = written
            task.ensure_room(max(0, estimate - written))
        task.tick(phase="extract", bytes_done=read, bytes_total=e.archive_bytes, written_bytes=written)

    task.log(f"Unpacking into {staging}", flush=True)
    members = extract(part, staging / "unpacked", e.top_dir, extracting)
    unpacked = staging / "unpacked" / e.top_dir if e.top_dir else staging / "unpacked"
    if not unpacked.is_dir():
        raise TaskFailure(f"the archive has no {e.top_dir}/ folder")
    found = _checked(task, e.kind, unpacked, e.version, e.db_type if e.kind == "bakta" else None)
    published = published_checksums(r, unpacked, found)
    manifest, md5s = hash_files(folder_items(unpacked), lambda d, t: task.tick(phase="manifest", bytes_done=d,
                                                                               bytes_total=t), frozenset(published))
    _compare_published(task, published, md5s)
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
    task.log(f"Installed in {svc._shown(target)}: {len(manifest)} files, {size:,} bytes ({fmt_bytes(size)}); content "
             f"checksum {checksum}. The archive was deleted after the verified extraction")
    amr = amrfinder_info(target) if e.kind == "bakta" else None
    if e.kind == "bakta":
        task.log(f"AMRFinderPlus data in amrfinderplus-db/latest: {amr['version']} (database format "
                 f"{amr['database_format']})" if amr else "This archive has no amrfinderplus-db/latest folder")
    stamp = svc.now()
    r.status, r.kind = DatabaseStatus.installed, e.kind
    r.version_source, r.verification_level = VersionSource.file, "full"
    r.size_bytes, r.checksum, r.archive_checksum = size, checksum, f"md5:{md5}"
    r.installed_at = r.verified_at = stamp
    found.path = str(target)
    r.manifest = manifest
    r.details = {
        **(r.details or {}), "detection": svc._stored_detection(found), "version_json": found.facts.get("version_json"),
        "file_count": len(manifest), "members": members,
        "archive": {"url": e.download_url, "filename": e.filename, "bytes": e.archive_bytes, "md5": md5,
                    "checksum_sources": list(e.checksum_sources), "deleted_after_extraction": True},
        "published_md5_checked": len(md5s), "amrfinderplus_db": amr,
    }
    task.set_progress(phase="done", bytes_done=size, bytes_total=size)
    svc.ensure_default(task.db, r.kind)


def _download_cleanup(task: Task, _exc: BaseException) -> None:
    shutil.rmtree(svc.staging_dir(task.record.id, svc.destination_root(task.record)), ignore_errors=True)


def run_database_download(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _download, _download_cleanup)


def extract_zip(archive: Path, dest: Path, limit: int, on_progress: Callable[[int, int], None]) -> int:
    """Copy every entry of a zip archive into the empty folder `dest`: only plain files and folders with relative
    names without '..', each no larger than the size the zip declares, at most `limit` bytes in all (zipfile checks
    each file's CRC-32 as it is read). Returns the number of files."""
    dest.mkdir(parents=True, exist_ok=False)
    written = count = 0
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if problem := rc.zip_member_problem(info):
                    raise UnsafeArchive(f"the zip entry {info.filename!r} is not accepted ({problem}); nothing was "
                                        "kept")
                target = dest.joinpath(*PurePosixPath(info.filename).parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src:
                    try:
                        out = open(target, "xb")
                    except FileExistsError:
                        raise UnsafeArchive(f"the zip entry {info.filename!r} appears twice") from None
                    with out:
                        size = 0
                        while chunk := src.read(CHUNK):
                            size += len(chunk)
                            written += len(chunk)
                            if size > info.file_size or written > limit:
                                raise UnsafeArchive(f"the zip entry {info.filename!r} is larger than the zip "
                                                    "declares; nothing was kept")
                            out.write(chunk)
                            on_progress(written, limit)
                os.chmod(target, 0o444)
                count += 1
    except (zipfile.BadZipFile, EOFError) as exc:
        raise TaskFailure(f"the archive is damaged: {exc}", "archive_damaged", detail=str(exc)) from exc
    return count


def _extract(task: Task) -> None:
    r = task.record
    details = r.details or {}
    source = Path(details.get("source_zip") or "")
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if root not in target.parents or not source.is_file():
        raise TaskFailure(f"the zip {svc._shown(source)} or the folder {svc._shown(target)} is not where it was "
                          "planned", "folder_missing", folder=svc._shown(source))
    expected = int((details.get("zip") or {}).get("uncompressed_bytes") or 0)
    task.ensure_room(expected)
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    task.log(f"Extracting a copy of {svc._shown(source)} ({expected:,} bytes) into {svc._shown(target)}; the zip is "
             "only read", flush=True)
    files = extract_zip(source, staging / "unpacked", expected,
                        lambda d, t: task.tick(phase="extract", bytes_done=d, bytes_total=t))
    unpacked = staging / "unpacked"
    found = _checked(task, "reference_genomes", unpacked)
    found.facts["package_root"] = str(target)
    published = {str(unpacked / k): v for k, v in rc.package_md5s(unpacked).items()}
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

    def moved(p: str) -> str:
        return str(target / Path(p).relative_to(unpacked)) if Path(p).is_relative_to(unpacked) else p

    manifest = [{**m, "path": moved(m["path"])} for m in manifest]
    genomes = [{**g, "path": moved(g["path"])} for g in found.facts.get("genomes", [])]
    found.path = str(target)
    stamp = svc.now()
    day = details.get("collection_date")
    r.version, r.version_source = svc.collection_version(found, day), VersionSource.declared
    r.status, r.verification_level = DatabaseStatus.installed, "full"
    r.checksum, r.size_bytes = manifest_checksum(manifest), manifest_bytes(manifest)
    r.installed_at = r.verified_at = stamp
    r.manifest, r.inventory = manifest, genomes
    r.details = {**details, "detection": svc._stored_detection(found), "collection": found.facts.get("collection"),
                 "file_count": len(manifest), "published_md5_checked": len(md5s)}
    coverage = found.facts.get("collection") or {}
    task.log(f"Copied {files} files; {coverage.get('genomes')} genomes of {coverage.get('species')} species; version "
             f"{r.version} (date declared by the user); content checksum {r.checksum}")
    task.set_progress(phase="done", bytes_done=r.size_bytes, bytes_total=r.size_bytes)
    svc.ensure_default(task.db, r.kind)


def run_database_extract(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.extracting, _extract, _download_cleanup)


def _verify(task: Task) -> None:
    r = task.record
    path = Path(r.path or "")
    if not (path.is_dir() or path.is_file()):
        from app.services.locations import unavailable_reason

        shown = svc._shown(path)
        if unavailable_reason(str(path)) == "disk_not_connected":
            raise DiskNotConnected(f"the disk of the database folder {shown} is not connected; the database was not "
                                   "checked and is kept as it is", "disk_not_connected", folder=shown)
        raise TaskFailure(f"the database folder {shown} no longer exists", "folder_missing", folder=shown)
    found = _checked(task, r.kind, path, r.version if r.version_source is VersionSource.file else None)
    if r.kind == "reference_genomes":
        fp = (found.facts.get("collection") or {}).get("fingerprint")
        if fp != ((r.details or {}).get("collection") or {}).get("fingerprint"):
            raise TaskFailure("the collection's genomes are not the ones recorded at registration", "check_failed",
                              detail="accession fingerprint changed")
    published = published_checksums(r, path, found)
    task.log(f"Computing the SHA-256 of every file of {svc._shown(path)}"
             + (f" and the MD5 of the {len(published)} the publisher lists" if published else ""), flush=True)
    manifest, md5s = hash_files(_items(r, path), lambda d, t: task.tick(phase="verify", bytes_done=d, bytes_total=t),
                                frozenset(published))
    _compare_published(task, published, md5s)
    old = r.manifest
    stamp = svc.now()
    if old is None:
        r.checksum = manifest_checksum(manifest)
        r.size_bytes = manifest_bytes(manifest)
        r.manifest = manifest
        task.log(f"Recorded {len(manifest)} files, {r.size_bytes:,} bytes; content checksum {r.checksum}. "
                 + ("Later checks compare every file with it" if published else "There is no published checksum for "
                    "an unpacked folder, so this only lets later checks detect changes"))
    else:
        diff = compare_manifests(old, manifest)
        if diff["missing"] or diff["changed"]:
            names = ", ".join((diff["changed"] + diff["missing"])[:5])
            raise TaskFailure(f"integrity check failed: {len(diff['changed'])} file(s) changed and "
                              f"{len(diff['missing'])} missing since installation ({names})", "integrity_failed",
                              changed=len(diff["changed"]), missing=len(diff["missing"]), names=names)
        if diff["extra"]:
            task.log(f"{len(diff['extra'])} file(s) added since installation (not part of the recorded database): "
                     f"{', '.join(diff['extra'][:5])}")
        task.log(f"All {len(old)} recorded files are unchanged (SHA-256)")
    if r.kind == "checkm2" and r.version is None:
        if version := _checkm2_version(manifest, found):
            r.version, r.version_source = version, VersionSource.checksum
            task.log(f"The SHA-256 of {found.facts['dmnd']} is CheckM2's published hash of database version "
                     f"{version} (version_hashes_1.1.0.json)")
        else:
            task.log(f"The SHA-256 of {found.facts['dmnd']} is not among CheckM2 1.1.0's published hashes; declare "
                     "the version")
    r.details = {**(r.details or {}), "amrfinderplus_db": amrfinder_info(path) if r.kind == "bakta" else None,
                 "file_count": len(manifest), "published_md5_checked": len(md5s),
                 "last_verification": {"at": stamp.isoformat(), "files": len(manifest), "level": "full"}}
    r.verified_at = stamp
    r.verification_level = "full"
    r.error_message = r.error_detail = None
    r.status = DatabaseStatus.installed if r.origin in svc.OWNED else DatabaseStatus.registered
    task.set_progress(phase="done")
    svc.ensure_default(task.db, r.kind)


def run_database_verify(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.verifying, _verify, lambda _t, _e: None)
