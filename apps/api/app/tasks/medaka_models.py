"""Worker task: download one Medaka model the user confirmed (app.services.medaka_models).

1. <model>_model_pt.tar.gz is fetched over HTTPS from the medaka repository at the tag of the installed medaka
   (media.githubusercontent.com, where GitHub serves the repository's Git LFS files) into the database folder's
   download area; a stopped download resumes where the server allows it.
2. Its size and SHA-256 must be those of the Git LFS pointer of the same tag (arva_tools.medaka_models.PUBLISHED);
   otherwise the file is deleted and nothing is installed.
3. The archive is checked without running it (members, sizes, the globals its pickles import), then medaka loads it
   once in its own environment as it loads a model it downloads (open_model + get_meta('model_function')), and
   resolve_model must return the file's own path.
4. The file and ARVA_DATABASE.json (model, address, SHA-256, size, tag, what medaka loaded) are put in
   <database folder>/medaka-models/<model>/, recognised as the medaka_model kind, hashed for the manifest and moved
   into place.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from arva_tools import medaka_models as mm
from arva_tools.registry import detect

from app import __version__
from app.models import DatabaseStatus, VersionSource
from app.services import databases as svc
from app.services.database_detect import ARVA_DATABASE_FILE
from app.tasks.databases import (
    Task,
    TaskCancelled,
    TaskFailure,
    _checked,
    _download_cleanup,
    _run,
    fetch,
    folder_items,
    hash_files,
    manifest_bytes,
    manifest_checksum,
)


@dataclass(frozen=True)
class _Archive:
    """What fetch() reads of a catalogue entry, for the confirmed file."""
    download_url: str
    archive_bytes: int
    extracted_bytes_estimate: int


def _download(task: Task) -> None:
    r = task.record
    info = (r.details or {}).get("medaka_model") or {}
    model = info.get("model") or ""
    root = svc.destination_root(r)
    target = Path(r.path or "")
    if model not in mm.PUBLISHED or root not in target.parents or not info.get("url"):
        raise TaskFailure(f"unexpected model or install folder ({model}, {r.path})")
    expected_sha, expected_bytes = mm.PUBLISHED[model]
    confirmation = (r.details or {}).get("confirmation") or {}
    task.log(f"{r.name}: {info.get('chemistry')}, {info.get('accuracy')}, trained for {info.get('basecaller')}; "
             f"{expected_bytes:,} bytes from {info['url']} (medaka {mm.MEDAKA_TAG}); published SHA-256 "
             f"{expected_sha} (Git LFS pointer of {mm.MEDAKA_TAG}); licence ({mm.LICENCE}) accepted at "
             f"{confirmation.get('at')}; into {svc._shown(target)}", flush=True)
    downloads = svc.downloads_dir(r.id, root)
    downloads.mkdir(parents=True, exist_ok=True)
    fname = mm.model_file_name(model)
    part = downloads / f"{fname}.part"
    fetch(task, _Archive(info["url"], expected_bytes, expected_bytes), part)
    sha = mm.sha256_of(part)
    if sha != expected_sha:
        part.unlink()
        raise TaskFailure(f"the SHA-256 of the downloaded {fname} is {sha}, not medaka {mm.MEDAKA_TAG}'s published "
                          f"{expected_sha}; the file was deleted", "medaka_model_checksum", got=sha,
                          expected=expected_sha)
    task.log(f"SHA-256 {sha} matches medaka {mm.MEDAKA_TAG}'s published file", flush=True)
    if task.cancel_requested():
        raise TaskCancelled()
    staging = svc.staging_dir(r.id, root)
    shutil.rmtree(staging, ignore_errors=True)
    folder = staging / target.name
    folder.mkdir(parents=True)
    shutil.copyfile(part, folder / fname)
    try:
        facts = mm.check_file(folder / fname, model)
    except mm.NotAModel as exc:
        raise TaskFailure(f"{fname} is not a Medaka model ARVA can use: {exc.detail}", "medaka_model_invalid",
                          detail=exc.detail[:300]) from exc
    task.log(f"Archive checked without running it: {', '.join(facts['members'])}; the pickles import only "
             f"{', '.join(facts['meta_globals'] + facts['weights_globals'])}")
    loaded = None
    tool = detect("medaka")
    if tool.path:
        try:
            loaded = mm.load_check(tool.path, folder / fname)
        except (RuntimeError, OSError) as exc:
            raise TaskFailure(str(exc), "medaka_model_unloadable", detail=str(exc)[:300]) from exc
        task.log(f"medaka {tool.version} loaded it (model_function {loaded['model_function']}); resolve_model returns "
                 "the file itself, so -m <file> uses it", flush=True)
    else:
        task.log("Medaka is not installed here, so medaka's own loading of the model was not tried")
    meta = {"kind": "medaka_model", "model": model, "file": fname, "url": info["url"], "medaka_url": info.get("medaka_url"),
            "pointer_url": info.get("pointer_url"), "sha256": sha, "bytes": facts["bytes"], "medaka_tag": mm.MEDAKA_TAG,
            "medaka_commit": mm.MEDAKA_COMMIT, "chemistry": info.get("chemistry"), "device": info.get("device"),
            "accuracy": info.get("accuracy"), "basecaller": info.get("basecaller"),
            "archive": {k: facts[k] for k in ("members", "meta_globals", "weights_globals")},
            "loaded_by": f"medaka {tool.version}" if loaded else None, "licence": mm.LICENCE,
            "downloaded_by": f"ARVA {__version__}", "downloaded_at": svc.now().isoformat()}
    (folder / ARVA_DATABASE_FILE).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    found = _checked(task, "medaka_model", folder, model)
    manifest, _ = hash_files(folder_items(folder), lambda d, t: task.tick(phase="manifest", bytes_done=d, bytes_total=t))
    checksum = manifest_checksum(manifest)
    if task.cancel_requested(lock=True):
        raise TaskCancelled()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(folder, target)
    shutil.rmtree(staging)
    shutil.rmtree(downloads, ignore_errors=True)
    size = manifest_bytes(manifest)
    task.log(f"Installed in {svc._shown(target)}: {fname} ({facts['bytes']:,} bytes) and {ARVA_DATABASE_FILE}; "
             f"polishing passes it to medaka_consensus as -m {svc._shown(target / fname)}")
    stamp = svc.now()
    r.status, r.verification_level = DatabaseStatus.installed, "full"
    r.version_source = VersionSource.checksum
    r.size_bytes, r.checksum, r.archive_checksum, r.manifest = size, checksum, f"sha256:{sha}", manifest
    r.installed_at = r.verified_at = stamp
    found.path = str(target)
    r.details = {**(r.details or {}), "detection": svc._stored_detection(found), "file_count": len(manifest),
                 "medaka_model": {**info, "sha256": sha, "bytes": facts["bytes"], "loaded_by": meta["loaded_by"],
                                  "archive": meta["archive"]}}
    task.set_progress(phase="done", bytes_done=size, bytes_total=size)


def run_medaka_model_download(record_id: str) -> str:
    return _run(record_id, DatabaseStatus.downloading, _download, _download_cleanup)
