"""Medaka models that the medaka package does not ship, as a kind of the Database Manager (database_kinds.py kind
medaka_model): the models ARVA can download (those medaka 2.1.1 publishes and loads, arva_tools.medaka_models), a
download only after the user confirms the model, what it was trained for, the address, the size, the SHA-256 and
the licence, and the registered models polishing can use.

medaka itself would download a missing model from its repository's master branch with no checksum
(medaka/models.py resolve_model); ARVA never lets it. ARVA downloads the file from the repository at the tag of the
installed medaka (v2.1.1), checks it against the SHA-256 and size of that tag's Git LFS pointer, checks the archive
without running it, lets medaka load it once and records the address and the SHA-256 (app.tasks.medaka_models). A
model file the user already has is registered where it is (databases.register), after the same checks; ARVA never
changes or deletes it.

Models are never chosen automatically: polishing uses a registered model only when the user picks it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arva_tools import medaka_models as mm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.messages import render
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase
from app.services import database_kinds as kinds
from app.services import databases as dbs

KIND = "medaka_model"
KEY_PREFIX = "medaka-"
DEFAULT_FOLDER = "medaka-models"

MESSAGES = {
    "medaka_model_unknown": "{model} is not one of the Medaka models ARVA can download (the consensus models medaka "
                            "{version} publishes that its package does not ship).",
    "medaka_model_shipped": "{model} ships with Medaka's package; there is nothing to download.",
    "medaka_model_confirm": "Confirm the model ({model}, {size}, SHA-256 {sha256}), the address and Medaka's licence "
                            "first.",
    "medaka_model_changed": "The model you confirmed ({confirmed}) is not the file ARVA would download now "
                            "({sha256}, {size}); look at the plan again.",
    "medaka_model_known": "{model} is already known to ARVA ({path}); delete that record first.",
}


class MedakaModelError(dbs.DatabaseError):
    def __init__(self, code: str, **params):
        super().__init__(render(MESSAGES[code], params), code, **params)


def key_for(model: str) -> str:
    return f"{KEY_PREFIX}{model}"


def record_name(model: str) -> str:
    return f"Medaka model {model}"


def model_file(record: ReferenceDatabase) -> Path | None:
    """The model's .tar.gz: the registered file itself, or the file inside the folder ARVA downloaded it into."""
    if not record.path:
        return None
    p = Path(record.path)
    if p.name.endswith(mm.MODEL_SUFFIX):
        return p
    return p / mm.model_file_name(record.version or "")


def _installed_lists() -> tuple[str | None, list[str] | None, list[str]]:
    """(medaka version, allowed models, shipped models) of the installed medaka, read from its own options.py, or
    (None, None, []) when it is not installed."""
    from app.services.polishing import medaka_catalogue

    cat, _error = medaka_catalogue(cached=True)
    if cat is None:
        return None, None, []
    return cat.get("version"), list(cat.get("allowed_models") or []), [m["name"] for m in cat.get("bundled_models") or []]


def summary(record: ReferenceDatabase) -> dict[str, Any]:
    """What polishing shows and records about a registered model."""
    info = (record.details or {}).get("medaka_model") or {}
    name = record.version or info.get("model")
    f = model_file(record)
    meta = mm.info(name).as_dict() if name in mm.PUBLISHED else {}
    return {"database_id": record.id, "model": name, "name": record.name, "path": str(f) if f else None,
            "sha256": info.get("sha256"),
            "url": info.get("url") or record.source_url, "origin": record.origin.value,
            "status": record.status.value, "chemistry": meta.get("chemistry"), "device": meta.get("device"),
            "accuracy": meta.get("accuracy"), "basecaller": meta.get("basecaller"), "notes": list(meta.get("notes") or [])}


def usable_records(db: Session) -> list[ReferenceDatabase]:
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == KIND)
                      .order_by(ReferenceDatabase.version, ReferenceDatabase.created_at))
    return [r for r in rows if dbs.usable_now(r)]


def registered(db: Session) -> list[dict[str, Any]]:
    """The models polishing may use besides the shipped ones: usable records whose file is there."""
    out = []
    for r in usable_records(db):
        s = summary(r)
        if s["path"] and Path(s["path"]).is_file() and s["sha256"]:
            out.append(s)
    return out


def listing(db: Session) -> dict[str, Any]:
    """The Database Manager's view: what medaka ships, what ARVA can download (with each model's facts and whether it
    is already here), the registered models, Medaka's licence and the guidance on choosing a model."""
    version, allowed, shipped = _installed_lists()
    records = list(db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == KIND)))
    known = {r.version: r for r in records if r.status not in (DatabaseStatus.failed, DatabaseStatus.cancelled)}
    available = []
    for m in mm.catalogue(allowed, shipped):
        r = known.get(m.name)
        available.append({**_model_info(m.name), "database_id": r.id if r else None,
                          "status": r.status.value if r else None})
    return {"medaka_version": version, "published_for": mm.MEDAKA_VERSION, "tag": mm.MEDAKA_TAG,
            "commit": mm.MEDAKA_COMMIT, "shipped": shipped, "available": available, "registered": registered(db),
            "licence": mm.LICENCE, "licence_url": mm.LICENCE_URL, "citation": mm.CITATION,
            "medaka_url_template": mm.MEDAKA_URL_TEMPLATE,
            "download_url_template": download_url("{fname}"),
            "deprecated_example": "r941_min_high_g360"}


def download_url(fname: str) -> str:
    """The address ARVA downloads a model file from: the medaka repository at the installed version's tag."""
    base = get_settings().medaka_models_url.rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise dbs.DatabaseError(f"{base} is not an https address")
    return f"{base}/{mm.MEDAKA_TAG}/medaka/data/{fname}"


def _model_info(name: str) -> dict[str, Any]:
    out = mm.info(name).as_dict()
    return {**out, "url": download_url(out["file"])}


def _check_model(model: str) -> mm.ModelInfo:
    version, allowed, shipped = _installed_lists()
    if model in shipped:
        raise MedakaModelError("medaka_model_shipped", model=model)
    if model not in mm.PUBLISHED or (allowed is not None and model not in allowed):
        raise MedakaModelError("medaka_model_unknown", model=model[:120], version=version or mm.MEDAKA_VERSION)
    return mm.info(model)


def _blocker(db: Session, model: str, target: Path) -> tuple[str | None, str | None]:
    for r in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == KIND,
                                                        ReferenceDatabase.version == model)):
        if r.status not in (DatabaseStatus.failed, DatabaseStatus.cancelled):
            return render(MESSAGES["medaka_model_known"], {"model": model, "path": dbs._shown(r.path or "")}), \
                "already_known"
    if target.exists():
        return (f"{dbs._shown(target)} already exists but ARVA has no record of it. Register it if it is a model, or "
                "choose another folder", "target_exists")
    if any(r.path and Path(r.path) in target.parents for r in db.scalars(select(ReferenceDatabase))):
        return f"{dbs._shown(target)} lies inside another database's folder; choose another folder", "inside_database"
    return None, None


def plan_download(db: Session, model: str, destination: str | None = None, folder: str | None = None) -> dict[str, Any]:
    """What downloading one model would do (nothing is sent): the model and what it was trained for, the address,
    its size and SHA-256 as medaka v2.1.1 publishes them, the licence, the folder and the space."""
    m = _check_model(model)
    root = dbs._destination(destination)
    folder_text = dbs._folder(folder, f"{DEFAULT_FOLDER}/{model}")
    target = root / folder_text
    blocked, code = _blocker(db, model, target)
    free = dbs.free_bytes(root)
    available = max(0, free - get_settings().min_free_bytes)
    k = kinds.BY_KEY[KIND]
    return {**_model_info(m.name), "model": model, "key": key_for(model), "medaka_version": mm.MEDAKA_VERSION,
            "tag": mm.MEDAKA_TAG, "commit": mm.MEDAKA_COMMIT, "licence": mm.LICENCE, "licence_url": mm.LICENCE_URL,
            "citation": mm.CITATION, "source_page": k.source_url, "db_dir": str(root), "folder": folder_text,
            "target_path": str(target), "host_target_path": dbs._shown(target),
            "destinations": dbs.writable_locations(), "required_bytes": m.bytes, "free_bytes": free,
            "reserve_bytes": get_settings().min_free_bytes, "available_bytes": available,
            "enough": m.bytes <= available, "blocked_by": blocked, "blocked_code": code}


def start_download(db: Session, model: str, confirm_sha256: str, confirm_bytes: int, accept_licence: bool,
                   destination: str | None = None, folder: str | None = None) -> ReferenceDatabase:
    """Plan again, check the confirmation and queue the download (app.tasks.medaka_models)."""
    from app.tasks.medaka_models import run_medaka_model_download

    p = plan_download(db, model, destination, folder)
    if not accept_licence or not confirm_sha256 or confirm_bytes <= 0:
        raise MedakaModelError("medaka_model_confirm", model=model, size=f"{p['bytes']:,} bytes", sha256=p["sha256"])
    if confirm_sha256 != p["sha256"] or confirm_bytes != p["bytes"]:
        raise MedakaModelError("medaka_model_changed", confirmed=f"{confirm_sha256[:64]}, {confirm_bytes:,} bytes",
                               sha256=p["sha256"], size=f"{p['bytes']:,} bytes")
    if p["blocked_by"]:
        raise dbs.DatabaseStateError(p["blocked_by"])
    if not p["enough"]:
        raise dbs.DatabaseSpaceError(p["required_bytes"], p["available_bytes"], Path(p["db_dir"]))
    record = ReferenceDatabase(
        key=p["key"], kind=KIND, name=record_name(model), version=model, path=p["target_path"],
        origin=DatabaseOrigin.download, status=DatabaseStatus.downloading, log_text="", source_url=p["url"],
        licence=mm.LICENCE, task_id=dbs._task_id(),
        details={"destination": p["db_dir"],
                 "medaka_model": {"model": model, "file": p["file"], "url": p["url"], "medaka_url": p["medaka_url"],
                                  "pointer_url": p["pointer_url"], "published_sha256": p["sha256"],
                                  "bytes": p["bytes"], "tag": mm.MEDAKA_TAG, "commit": mm.MEDAKA_COMMIT,
                                  "chemistry": p["chemistry"], "device": p["device"], "accuracy": p["accuracy"],
                                  "basecaller": p["basecaller"]},
                 "confirmation": {"model": model, "sha256": confirm_sha256, "bytes": confirm_bytes,
                                  "licence": mm.LICENCE, "url": p["url"], "at": dbs.now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": p["bytes"]},
    )
    db.add(record)
    db.commit()
    dbs._enqueue(record, run_medaka_model_download)
    db.refresh(record)
    return record


def registered_details(found) -> dict[str, Any]:
    """The `medaka_model` details of a registered model file (database_detect checked it)."""
    facts = found.facts.get("medaka_model") or {}
    name = facts.get("name")
    meta = mm.info(name).as_dict() if name in mm.PUBLISHED else {}
    return {"model": name, "file": Path(found.path).name if found.path_type == "file" else meta.get("file"),
            "sha256": facts.get("sha256"), "published_sha256": facts.get("published_sha256"),
            "bytes": facts.get("bytes"), "tag": mm.MEDAKA_TAG, "url": None, "pointer_url": meta.get("pointer_url"),
            "chemistry": meta.get("chemistry"), "device": meta.get("device"), "accuracy": meta.get("accuracy"),
            "basecaller": meta.get("basecaller"), "meta_globals": facts.get("meta_globals"),
            "weights_globals": facts.get("weights_globals")}


def blocking_duplicate(db: Session, model: str | None) -> ReferenceDatabase | None:
    """A record of the same model that is not failed or cancelled (one record per model, so polishing can name it)."""
    if not model:
        return None
    return next((r for r in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == KIND,
                                                                        ReferenceDatabase.version == model))
                 if r.status not in (DatabaseStatus.failed, DatabaseStatus.cancelled)), None)
