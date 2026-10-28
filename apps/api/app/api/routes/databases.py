from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ReferenceDatabase
from app.schemas.schemas import (
    CatalogueEntryRead,
    DatabaseDownloadRequest,
    DatabaseRegisterRequest,
    DatabaseUsageRead,
    DownloadPlanRead,
    ReferenceDatabaseRead,
)
from app.services import database_catalogue as catalogue
from app.services import databases as svc

router = APIRouter(tags=["databases"])


def _entry(e: catalogue.CatalogueEntry) -> CatalogueEntryRead:
    return CatalogueEntryRead(**asdict(e))


def _read(db: Session, r: ReferenceDatabase, log: bool = False) -> ReferenceDatabaseRead:
    details = r.details or {}
    known = catalogue.BY_KEY.get(r.key)
    out = ReferenceDatabaseRead.model_validate(r)
    return out.model_copy(update={
        "version_json": details.get("version_json"),
        "files": len(details["manifest"]) if details.get("manifest") else None,
        "amrfinderplus_db": details.get("amrfinderplus_db"),
        "archive": details.get("archive"),
        "catalogue_version": known.version if known else None,
        "jobs_using": svc.jobs_using(db, r.id),
        "log_text": r.log_text if log else None,
    })


def _errors(exc: Exception):
    if isinstance(exc, LookupError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Reference database not found")
    if isinstance(exc, svc.DatabaseStateError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _space(exc: svc.DatabaseSpaceError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                        content={"detail": str(exc), "needed_bytes": exc.needed, "available_bytes": exc.available})


@router.get("/databases/catalogue", response_model=list[CatalogueEntryRead])
def list_catalogue():
    """Databases ARVA knows, with the facts published by their source (size, checksum, licence, version)."""
    return [_entry(e) for e in catalogue.CATALOGUE]


@router.get("/databases/catalogue/{key}/plan", response_model=DownloadPlanRead)
def download_plan(key: str, db: Session = Depends(get_db)):
    """What downloading this database needs now: bytes to fetch, room for unpacking, free space, licence, source."""
    try:
        plan = svc.plan_download(db, key)
    except (LookupError, svc.DatabaseError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND if isinstance(exc, LookupError) else 400, str(exc)) from exc
    return DownloadPlanRead(**{**asdict(plan), "entry": _entry(plan.entry)})


@router.get("/databases", response_model=list[ReferenceDatabaseRead])
def list_databases(db: Session = Depends(get_db)):
    records = db.scalars(select(ReferenceDatabase).order_by(ReferenceDatabase.key, ReferenceDatabase.created_at))
    return [_read(db, r) for r in records]


@router.get("/databases/usage", response_model=DatabaseUsageRead)
def disk_usage(db: Session = Depends(get_db)):
    return svc.usage(db)


@router.get("/databases/{record_id}", response_model=ReferenceDatabaseRead)
def get_database(record_id: str, db: Session = Depends(get_db)):
    record = db.get(ReferenceDatabase, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference database not found")
    return _read(db, record, log=True)


@router.post("/databases/downloads", response_model=ReferenceDatabaseRead, status_code=status.HTTP_202_ACCEPTED,
             responses={507: {"description": "Not enough free space in ARVA_DB_DIR"}})
def start_download(payload: DatabaseDownloadRequest, db: Session = Depends(get_db)):
    """Queue a download from the catalogue's official URL. `confirm_bytes` must repeat the archive size and
    `accept_licence` must be true. A failed or cancelled download of the same version is resumed."""
    try:
        return _read(db, svc.start_download(db, payload.key, payload.confirm_bytes, payload.accept_licence))
    except svc.DatabaseSpaceError as exc:
        return _space(exc)
    except (LookupError, svc.DatabaseError, svc.DatabaseStateError) as exc:
        raise _errors(exc) from exc


@router.post("/databases/register", response_model=ReferenceDatabaseRead, status_code=status.HTTP_202_ACCEPTED)
def register_database(payload: DatabaseRegisterRequest, db: Session = Depends(get_db)):
    """Register an existing Bakta database folder (inside ARVA_DB_DIR or an import folder) after Bakta's own checks;
    the worker then records the SHA-256 of every file. ARVA never modifies or deletes a registered folder."""
    try:
        return _read(db, svc.register(db, payload.path))
    except (svc.DatabaseError, svc.DatabaseStateError) as exc:
        raise _errors(exc) from exc


@router.post("/databases/{record_id}/verify", response_model=ReferenceDatabaseRead,
             status_code=status.HTTP_202_ACCEPTED)
def verify_database(record_id: str, db: Session = Depends(get_db)):
    """Check the folder again: Bakta's folder check and every file against the SHA-256 recorded at installation."""
    try:
        return _read(db, svc.start_verify(db, record_id))
    except (LookupError, svc.DatabaseStateError) as exc:
        raise _errors(exc) from exc


@router.post("/databases/{record_id}/cancel", response_model=ReferenceDatabaseRead,
             status_code=status.HTTP_202_ACCEPTED)
def cancel_database_task(record_id: str, db: Session = Depends(get_db)):
    """Stop a download (its partial file is kept for resuming) or a verification."""
    try:
        return _read(db, svc.cancel(db, record_id))
    except (LookupError, svc.DatabaseStateError) as exc:
        raise _errors(exc) from exc


@router.delete("/databases/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_database(record_id: str, db: Session = Depends(get_db)):
    """Delete an installed database's folder and record, or only the record of a registered folder. Refused while
    it is downloading or verifying, or while a queued or running job uses it."""
    try:
        svc.delete(db, record_id)
    except (LookupError, svc.DatabaseStateError) as exc:
        raise _errors(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
