from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ReferenceDatabase
from app.schemas.schemas import (
    BrowseListingRead,
    CatalogueEntryRead,
    CompatibilityRead,
    DatabaseDownloadRequest,
    DatabaseExtractRequest,
    DatabaseKindRead,
    DatabaseLocationsRead,
    DatabaseRegisterRequest,
    DatabaseUsageRead,
    DatabaseVerifyRequest,
    DetectionRead,
    DetectResultRead,
    DownloadPlanRead,
    ExtractPlanRead,
    NcbiPlanRead,
    NcbiPlanRequest,
    NcbiStartRequest,
    ReferenceDatabaseRead,
)
from app.services import abricate_db, mlst
from app.services import database_catalogue as catalogue
from app.services import database_kinds as kinds
from app.services import databases as svc
from app.services import ncbi_datasets as ncbi
from app.services.locations import to_host

router = APIRouter(tags=["databases"])
_PREVIEW_GENOMES = 20


def _entry(e: catalogue.CatalogueEntry) -> CatalogueEntryRead:
    return CatalogueEntryRead(**asdict(e), install_dir=e.install_dir,
                              compatibility_now=asdict(svc.entry_compatibility(e)))


def _read(db: Session, r: ReferenceDatabase, log: bool = False) -> ReferenceDatabaseRead:
    details = r.details or {}
    detection = details.get("detection") or {}
    known = catalogue.BY_KEY.get(r.key)
    available, reason = svc.availability(r)
    out = ReferenceDatabaseRead.model_validate(r)
    return out.model_copy(update={
        "version_json": details.get("version_json"),
        "version_file": detection.get("version_file"),
        "variant": detection.get("variant"),
        "collection": details.get("collection"),
        "files": details.get("file_count"),
        "published_md5_checked": details.get("published_md5_checked"),
        "amrfinderplus_db": _bakta_amr(details.get("amrfinderplus_db")),
        "archive": details.get("archive"),
        "catalogue_version": known.version if known else None,
        "compatibility": CompatibilityRead(**asdict(svc.record_compatibility(r))),
        "jobs_using": svc.jobs_using(db, r.id),
        "available": available,
        "unavailable_reason": reason,
        "host_path": to_host(r.path),
        "log_text": r.log_text if log else None,
        "mlst": mlst.database_summary(r) if r.kind == mlst.KIND else None,
    })


def _bakta_amr(info: dict | None) -> dict | None:
    """The AMRFinderPlus data inside a Bakta database, with whether the installed AMRFinderPlus reads them."""
    if not info:
        return info
    compat = kinds.compatibility("amrfinderplus", {"database_format_version": info.get("database_format")},
                                 version=info.get("version"))
    return {**info, "compatibility": asdict(compat)}


def _detection(db: Session, d) -> DetectionRead:
    out = d.as_dict()
    facts = dict(out["facts"])
    genomes = facts.pop("genomes", None)
    if genomes is not None:
        facts["genome_preview"] = [g for g in genomes if not g["present"]][:_PREVIEW_GENOMES] + \
            [g for g in genomes if g["present"]][:_PREVIEW_GENOMES]
        for g in facts["genome_preview"]:
            g["host_path"] = to_host(g["path"])
    existing = db.scalar(select(ReferenceDatabase.id).where(ReferenceDatabase.path == d.path))
    compat = None
    if d.kind in kinds.BY_KEY:
        info = d.facts if d.kind == "amrfinderplus" else d.facts.get("version_json")
        compat = asdict(kinds.compatibility(d.kind, info, version=d.version))
    return DetectionRead(**{**out, "facts": facts}, kind_name=kinds.BY_KEY[d.kind].name if d.kind in kinds.BY_KEY
                         else None, host_path=to_host(d.path), compatibility=compat, already_registered=existing)


def _coded(code: int, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": str(exc), "code": exc.code, "params": exc.params})


def _space(exc: svc.DatabaseSpaceError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                        content={"detail": str(exc), "needed_bytes": exc.needed, "available_bytes": exc.available})


def _refusal(exc: Exception):
    """A refusal as JSON with its code when it has one (the interface shows api.error.<code>), else as before."""
    if isinstance(exc, svc.DatabaseSpaceError):
        return _space(exc)
    if isinstance(exc, LookupError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference database not found") from exc
    if isinstance(exc, svc.DatabaseFolderUnavailable):
        return _coded(status.HTTP_503_SERVICE_UNAVAILABLE, exc)
    if isinstance(exc, ncbi.NcbiError) and exc.upstream:
        return _coded(status.HTTP_502_BAD_GATEWAY, exc)
    code = status.HTTP_409_CONFLICT if isinstance(exc, svc.DatabaseStateError) else status.HTTP_400_BAD_REQUEST
    if getattr(exc, "code", None):
        return _coded(code, exc)
    raise HTTPException(code, str(exc)) from exc


_EXPECTED = (LookupError, svc.DatabaseError, svc.DatabaseStateError, svc.DatabaseSpaceError)


@router.get("/databases/kinds", response_model=list[DatabaseKindRead])
def list_kinds():
    """Every database kind ARVA recognises: how it is recognised and versioned, its tools, licence, citation, and
    whether ARVA can download it, with the sources of those facts and what is not confirmed."""
    return [DatabaseKindRead(**asdict(k)) for k in kinds.KINDS]


@router.get("/databases/catalogue", response_model=list[CatalogueEntryRead])
def list_catalogue():
    """The versions ARVA can download, with the facts published by their source (size, checksum, licence) and
    whether the tool version ARVA runs can read them."""
    return [_entry(e) for e in catalogue.CATALOGUE]


@router.get("/databases/locations", response_model=DatabaseLocationsRead)
def database_locations():
    """The database folders ARVA may download into, and the folders the registration browser shows."""
    return {"writable": svc.writable_locations(), "browse": svc.browse_roots()}


@router.get("/databases/browse", response_model=BrowseListingRead)
def browse(root: str = Query(max_length=4096), path: str = Query(default="", max_length=4096)):
    """The folders and files under a database folder or an added database folder (read only)."""
    try:
        return svc.browse(root, path)
    except _EXPECTED as exc:
        return _refusal(exc)


@router.get("/databases/detect", response_model=DetectResultRead)
def detect(path: str = Query(min_length=1, max_length=4096), db: Session = Depends(get_db)):
    """What a folder or file is: its kind, the version and the file it was read from, the files checked, the
    problems found and, for a reference collection, its coverage. Nothing is written."""
    try:
        real, found = svc.detect(path)
    except _EXPECTED as exc:
        return _refusal(exc)
    return {"path": str(real), "host_path": to_host(str(real)), "candidates": [_detection(db, d) for d in found]}


@router.get("/databases/catalogue/{key}/plan", response_model=DownloadPlanRead)
def download_plan(key: str, destination: str | None = Query(default=None, max_length=4096),
                  folder: str | None = Query(default=None, max_length=400),
                  keep_plasmid_fasta: bool = False,
                  taxonomy_archive: str | None = Query(default=None, pattern=r"^taxdmp_\d{4}-\d{2}-\d{2}\.zip$"),
                  db: Session = Depends(get_db)):
    """What downloading this version into the chosen database folder needs now: bytes to fetch, room for
    unpacking, free space, licence, source (for MOB-suite, also the NCBI taxonomy archive it needs)."""
    try:
        plan = svc.plan_download(db, key, destination, folder, keep_plasmid_fasta, taxonomy_archive)
        destinations = svc.writable_locations()
    except _EXPECTED as exc:
        return _refusal(exc)
    return DownloadPlanRead(**{**asdict(plan), "entry": _entry(plan.entry), "destinations": destinations})


@router.get("/databases", response_model=list[ReferenceDatabaseRead])
def list_databases(db: Session = Depends(get_db)):
    mlst.refresh_bundled(db)
    abricate_db.refresh_bundled(db)
    records = db.scalars(select(ReferenceDatabase).order_by(ReferenceDatabase.kind, ReferenceDatabase.created_at))
    return [_read(db, r) for r in records]


@router.get("/databases/usage", response_model=DatabaseUsageRead)
def disk_usage(db: Session = Depends(get_db)):
    try:
        return svc.usage(db)
    except svc.DatabaseFolderUnavailable as exc:
        return _coded(status.HTTP_503_SERVICE_UNAVAILABLE, exc)


@router.get("/databases/extract/plan", response_model=ExtractPlanRead)
def extract_plan(path: str = Query(min_length=1, max_length=4096),
                 destination: str | None = Query(default=None, max_length=4096),
                 folder: str | None = Query(default=None, max_length=400), db: Session = Depends(get_db)):
    """What extracting a copy of an NCBI Datasets package zip into a database folder needs (the zip is only read)."""
    try:
        plan = svc.plan_extract(db, path, destination, folder)
        destinations = svc.writable_locations()
    except _EXPECTED as exc:
        return _refusal(exc)
    return ExtractPlanRead(**{**{k: v for k, v in plan.__dict__.items() if k != "detection"},
                              "detection": _detection(db, plan.detection), "destinations": destinations})


def _filters(payload: NcbiPlanRequest) -> ncbi.Filters:
    return ncbi.Filters(**payload.filters.model_dump())


@router.post("/databases/ncbi/plan", response_model=NcbiPlanRead,
             responses={502: {"description": "NCBI Datasets refused, failed or could not be reached"}})
def ncbi_plan(payload: NcbiPlanRequest, db: Session = Depends(get_db)):
    """What a reference genome collection of the taxon would hold, from NCBI Datasets' metadata only: the taxon
    (several when a name is ambiguous), the number of genomes, species and type-material genomes, NCBI's download
    size estimate, ARVA's estimate of the unpacked size and the destination's free space. Nothing is downloaded but
    metadata; only the taxon and the filters are sent."""
    try:
        return ncbi.plan(db, payload.taxon, payload.tax_id, _filters(payload), payload.destination, payload.folder)
    except _EXPECTED as exc:
        return _refusal(exc)


@router.post("/databases/ncbi", response_model=ReferenceDatabaseRead, status_code=status.HTTP_202_ACCEPTED,
             responses={502: {"description": "NCBI Datasets refused, failed or could not be reached"},
                        507: {"description": "Not enough free space in the chosen database folder"}})
def ncbi_start(payload: NcbiStartRequest, db: Session = Depends(get_db)):
    """Download the confirmed collection from NCBI Datasets into a database folder (a background task). The list is
    fetched again and must match the confirmed number of genomes and fingerprint; every file is checked against the
    package's md5sum.txt and the collection is installed with its source and download date as its version."""
    try:
        return _read(db, ncbi.start(db, payload.taxon, payload.tax_id, _filters(payload), payload.confirm_genomes,
                                    payload.confirm_fingerprint, payload.destination, payload.folder))
    except _EXPECTED as exc:
        return _refusal(exc)


@router.get("/databases/{record_id}", response_model=ReferenceDatabaseRead)
def get_database(record_id: str, db: Session = Depends(get_db)):
    record = db.get(ReferenceDatabase, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference database not found")
    return _read(db, record, log=True)


@router.post("/databases/downloads", response_model=ReferenceDatabaseRead, status_code=status.HTTP_202_ACCEPTED,
             responses={507: {"description": "Not enough free space in the chosen database folder"}})
def start_download(payload: DatabaseDownloadRequest, db: Session = Depends(get_db)):
    """Queue a download from the catalogue's official URL into the chosen database folder. `confirm_bytes` must
    repeat the archive size and `accept_licence` must be true. A failed or cancelled download of the same version is
    resumed where it was."""
    try:
        return _read(db, svc.start_download(db, payload.key, payload.confirm_bytes, payload.accept_licence,
                                            payload.destination, payload.folder, payload.keep_plasmid_fasta,
                                            payload.taxonomy_archive))
    except _EXPECTED as exc:
        return _refusal(exc)


@router.post("/databases/register", response_model=ReferenceDatabaseRead, status_code=status.HTTP_201_CREATED)
def register_database(payload: DatabaseRegisterRequest, db: Session = Depends(get_db)):
    """Register an existing database folder or file of any kind (inside a database folder, an import folder or a
    folder added with scripts/start.sh --add-databases; the path may be given as on this computer) after the quick
    verification. A version the files do not state is declared (and recorded as declared). ARVA never modifies or
    deletes a registered folder."""
    try:
        record = svc.register(db, payload.path, payload.kind, payload.declared_version, payload.collection_date,
                              payload.full_checksum)
    except _EXPECTED as exc:
        return _refusal(exc)
    return _read(db, record)


@router.post("/databases/extract", response_model=ReferenceDatabaseRead, status_code=status.HTTP_202_ACCEPTED,
             responses={507: {"description": "Not enough free space in the chosen database folder"}})
def extract_copy(payload: DatabaseExtractRequest, db: Session = Depends(get_db)):
    """Extract a copy of an NCBI Datasets package zip into a database folder (the zip is never changed)."""
    try:
        return _read(db, svc.start_extract(db, payload.path, payload.confirm_bytes, payload.collection_date,
                                           payload.destination, payload.folder))
    except _EXPECTED as exc:
        return _refusal(exc)


@router.post("/databases/{record_id}/verify", response_model=ReferenceDatabaseRead,
             status_code=status.HTTP_202_ACCEPTED)
def verify_database(record_id: str, payload: DatabaseVerifyRequest | None = None, db: Session = Depends(get_db)):
    """Check the database again: quick (at once: the kind's files, their sizes and the version file) or full (a
    cancellable background job: the SHA-256 of every file against the manifest recorded the first time, and the
    publisher's per-file MD5s where it lists them)."""
    try:
        return _read(db, svc.start_verify(db, record_id, (payload or DatabaseVerifyRequest()).level))
    except _EXPECTED as exc:
        return _refusal(exc)


@router.post("/databases/{record_id}/default", response_model=ReferenceDatabaseRead)
def make_default(record_id: str, db: Session = Depends(get_db)):
    """Make this the database of its kind analyses use when none is chosen (one per kind)."""
    try:
        return _read(db, svc.set_default(db, record_id))
    except _EXPECTED as exc:
        return _refusal(exc)


@router.post("/databases/{record_id}/cancel", response_model=ReferenceDatabaseRead,
             status_code=status.HTTP_202_ACCEPTED)
def cancel_database_task(record_id: str, db: Session = Depends(get_db)):
    """Stop a download (its partial file is kept for resuming), an extraction or a full verification."""
    try:
        return _read(db, svc.cancel(db, record_id))
    except _EXPECTED as exc:
        return _refusal(exc)


@router.delete("/databases/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_database(record_id: str, db: Session = Depends(get_db)):
    """Delete a database ARVA installed or extracted (its folder and record), or only the record of a registered
    folder. Refused while it is busy, or while a queued or running job uses it."""
    try:
        svc.delete(db, record_id)
    except _EXPECTED as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
