"""Preparing a MOB-suite database folder from the verified Zenodo archive, as mob_init would, without running it.

mob_init (MOB-suite 3.1.9) downloads the archive with TLS verification turned off and the latest NCBI taxonomy
through ete3; ARVA instead downloads the pinned archive (its MD5 compared with Zenodo's), unpacks the files
mob_recon reads, builds the same BLAST indexes and Mash sketch with the environment's makeblastdb and mash
(arva_tools.mobsuite has the commands), and builds taxa.sqlite with ete3 from a dated NCBI taxonomy archive the user
confirmed. The reference plasmids' FASTA is streamed from the archive into makeblastdb and mash at once; it is kept
on disk only when asked (mob_recon searches its BLAST index, not the FASTA).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any

from arva_tools import mobsuite as mob
from arva_tools.runner import isolated_home, tool_environment

from app.services import databases as svc
from app.services.database_catalogue import CatalogueEntry
from app.tasks.databases import (
    CHUNK,
    Task,
    TaskCancelled,
    TaskFailure,
    _CountingReader,
    fetch,
    safe_member_path,
)

PROVENANCE = "ARVA_DATABASE.json"
PREPARE_LOG = "ARVA_PREPARE.log"
_SKIPPED_PREFIXES = ("._",)
_SKIPPED_NAMES = (".DS_Store", "__init__.py")


def _feed(task: Task, procs: list[subprocess.Popen], source, sink, size: int, read_before: int) -> tuple[str, int]:
    """Write `source` to every process's standard input (and to `sink`), with its SHA-256 and length."""
    digest, done = hashlib.sha256(), 0
    while chunk := source.read(CHUNK):
        digest.update(chunk)
        done += len(chunk)
        for p in procs:
            try:
                p.stdin.write(chunk)
            except BrokenPipeError:
                raise TaskFailure(f"{Path(p.args[0]).name} stopped while reading the reference plasmids") from None
        if sink is not None:
            sink.write(chunk)
        task.tick(phase="index", bytes_done=read_before + done, bytes_total=size)
    return digest.hexdigest(), done


def _start(argv: list[str], log: Path, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    task_log = open(log, "ab")
    try:
        return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=task_log, stderr=task_log, cwd=cwd, env=env,
                                start_new_session=True)
    finally:
        task_log.close()


def _run(task: Task, argv: list[str], log: Path, cwd: Path, env: dict[str, str]) -> None:
    task.log("Command: " + " ".join(argv), flush=True)
    with open(log, "ab") as out:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out, cwd=cwd, env=env,
                                start_new_session=True)
        while proc.poll() is None:
            try:
                task.tick(phase="index")
            except TaskCancelled:
                proc.kill()
                proc.wait()
                raise
            time.sleep(0.5)
    if proc.returncode != 0:
        raise TaskFailure(f"{Path(argv[0]).name} exited with status {proc.returncode} (see {log.name})",
                          "prepare_failed", tool=Path(argv[0]).name, status=proc.returncode)


def prepare(task: Task, e: CatalogueEntry, archive: Path, dest: Path, exe: str, threads: int,
            keep_fasta: bool) -> dict[str, Any]:
    """Unpack the files mob_recon reads into `dest` and build the reference plasmids' BLAST index and Mash sketch,
    streaming their FASTA from the archive once. Returns what was done, for the record."""
    dest.mkdir(parents=True, exist_ok=False)
    log = dest / PREPARE_LOG
    files: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    commands: list[list[str]] = []
    fasta: dict[str, Any] | None = None
    with isolated_home() as home, open(archive, "rb") as raw:
        env = {**tool_environment(home), **mob.env_for(exe, home)}
        counter = _CountingReader(raw)
        try:
            tar = tarfile.open(fileobj=counter, mode="r|gz")
        except tarfile.TarError as exc:
            raise TaskFailure(f"the archive could not be read: {exc}") from exc
        with tar:
            for member in tar:
                rel = safe_member_path(member.name, None)
                name = rel.name if rel else ""
                if rel is None or member.isdir() or name.startswith(_SKIPPED_PREFIXES) or name in _SKIPPED_NAMES:
                    if rel is not None and not member.isdir():
                        skipped.append(str(rel))
                    continue
                if not member.isreg() or rel.parts[:-1] != ("data",) or name not in (*mob.DB_FILES,
                                                                                       mob.PLASMID_FASTA):
                    raise TaskFailure(f"the archive holds {rel}, which MOB-suite database {e.version} does not; "
                                      "nothing was installed", "unexpected_member", member=str(rel)[:200])
                src = tar.extractfile(member)
                if name == mob.PLASMID_FASTA:
                    argvs = [mob.makeblastdb_plasmids(exe, dest), mob.mash_sketch(exe, dest, threads)]
                    commands += argvs
                    for a in argvs:
                        task.log("Command: " + " ".join(a) + " < data/" + name, flush=True)
                    procs = [_start(a, log, dest, env) for a in argvs]
                    sink = open(dest / name, "xb") if keep_fasta else None
                    try:
                        sha, size = _feed(task, procs, src, sink, member.size, 0)
                    except BaseException:
                        for p in procs:
                            p.kill()
                        raise
                    finally:
                        for p in procs:
                            if p.stdin and not p.stdin.closed:
                                try:
                                    p.stdin.close()
                                except BrokenPipeError:
                                    pass
                        if sink is not None:
                            sink.close()
                    for p, a in zip(procs, argvs, strict=True):
                        if p.wait() != 0:
                            raise TaskFailure(f"{Path(a[0]).name} exited with status {p.returncode} while indexing "
                                              f"the reference plasmids (see {PREPARE_LOG})", "prepare_failed",
                                              tool=Path(a[0]).name, status=p.returncode)
                    fasta = {"sha256": sha, "bytes": size, "kept": keep_fasta}
                    task.log(f"Reference plasmids ({size:,} bytes, sha256 {sha}) indexed by makeblastdb and mash"
                             + ("; the FASTA was kept" if keep_fasta else "; the FASTA was not kept (mob_recon "
                                                                         "searches only its BLAST index)"), flush=True)
                    continue
                digest = hashlib.sha256()
                with open(dest / name, "xb") as out:
                    while chunk := src.read(CHUNK):
                        digest.update(chunk)
                        out.write(chunk)
                files[name] = {"sha256": digest.hexdigest(), "bytes": member.size}
    if missing := [n for n in mob.DB_FILES if n not in files] + ([] if fasta else [mob.PLASMID_FASTA]):
        raise TaskFailure(f"the archive lacks {', '.join(missing)}; nothing was installed", "missing_files",
                          files=", ".join(missing))
    with isolated_home() as home:
        argv = mob.makeblastdb_repetitive(exe, dest)
        commands.append(argv)
        _run(task, argv, log, dest, {**tool_environment(home), **mob.env_for(exe, home)})
    if skipped:
        task.log(f"Left out {len(skipped)} macOS metadata file(s) of the archive (._* and .DS_Store) and its empty "
                 "__init__.py")
    return {"files": files, "plasmid_fasta": fasta, "skipped": skipped, "commands": commands}


def taxonomy_entry(e: CatalogueEntry, taxonomy: dict[str, Any]) -> CatalogueEntry:
    """The NCBI taxonomy archive as a download: its size is the Content-Length the plan read (NCBI publishes no
    checksum for the dated archives)."""
    return dataclasses.replace(e, download_url=taxonomy["url"], filename=taxonomy["name"],
                               archive_bytes=taxonomy["bytes"], checksum="", extracted_bytes_estimate=0)


def taxonomy(task: Task, e: CatalogueEntry, info: dict[str, Any], downloads: Path, dest: Path,
             exe: str) -> dict[str, Any]:
    """Download the dated NCBI taxonomy archive, record its SHA-256, repack names.dmp, nodes.dmp and merged.dmp as
    the tar ete3 reads and build taxa.sqlite in `dest`; the archive and the tar are deleted afterwards."""
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / f"{info['name']}.part"
    fetch(task, taxonomy_entry(e, info), part)
    digest = hashlib.sha256()
    with open(part, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    sha = digest.hexdigest()
    task.log(f"NCBI taxonomy archive {info['name']}: {info['bytes']:,} bytes (the size NCBI announced), sha256 {sha} "
             "(NCBI publishes no checksum for the dated archives)", flush=True)
    work = downloads / "taxonomy"
    work.mkdir(exist_ok=True)
    tar_path = work / "taxdump.tar.gz"
    try:
        with zipfile.ZipFile(part) as z, tarfile.open(tar_path, "w:gz") as out:
            names = {i.filename: i for i in z.infolist()}
            if missing := [m for m in mob.TAXDUMP_MEMBERS if m not in names]:
                raise TaskFailure(f"{info['name']} lacks {', '.join(missing)}", "missing_files",
                                  files=", ".join(missing))
            for m in mob.TAXDUMP_MEMBERS:
                ti = tarfile.TarInfo(m)
                ti.size = names[m].file_size
                with z.open(names[m]) as src:
                    out.addfile(ti, src)
    except (zipfile.BadZipFile, OSError) as exc:
        raise TaskFailure(f"{info['name']} could not be read: {exc}", "archive_damaged", detail=str(exc)) from exc
    part.unlink()
    with isolated_home() as home:
        argv = mob.taxonomy_build(exe, dest, tar_path)
        _run(task, argv, dest / PREPARE_LOG, work, {**tool_environment(home), **mob.env_for(exe, home)})
    tar_path.unlink()
    for m in (mob.TAXA, mob.TAXA_EXTRA):
        if not (dest / m).is_file():
            raise TaskFailure(f"ete3 did not write {m}", "prepare_failed", tool="ete3", status=0)
    return {"archive": info["name"], "url": info["url"], "bytes": info["bytes"], "sha256": sha,
            "modified": info.get("modified"), "command": argv}


def write_provenance(dest: Path, e: CatalogueEntry, md5: str, prepared: dict[str, Any], tax: dict[str, Any],
                     tool_version: str | None) -> dict[str, Any]:
    """ARVA's record of how the folder was made, kept in the folder (the version is read from it)."""
    doc = {"kind": "mobsuite", "version": e.version, "source": e.source_url, "archive": {
        "url": e.download_url, "bytes": e.archive_bytes, "md5": md5, "checksum_sources": list(e.checksum_sources)},
           "files": prepared["files"], "plasmid_fasta": prepared["plasmid_fasta"], "taxonomy": tax,
           "prepared_with": {"tool": "MOB-suite", "version": tool_version, "commands": [*prepared["commands"],
                                                                                          tax["command"]]},
           "prepared_at": svc.now().isoformat(timespec="seconds")}
    (dest / PROVENANCE).write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def make_read_only(folder: Path) -> None:
    for f in folder.iterdir():
        if f.is_file():
            os.chmod(f, 0o444)


def read_provenance(folder: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads((folder / PROVENANCE).read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("kind") == "mobsuite" else None

