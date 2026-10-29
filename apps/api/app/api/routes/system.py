from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.schemas import (
    BackupsRead,
    PerformanceRead,
    PerformanceUpdate,
    StorageAdoptRequest,
    StorageCapacityRead,
)
from app.services import locations, performance
from app.services.capacity import storage_capacity

router = APIRouter(tags=["system"])


def _marker(state: locations.MarkerState) -> dict:
    out = {"status": state.status, "disk_id": state.disk_id, "recorded_id": state.recorded_id,
           "backups": state.backups}
    if not state.writable:
        exc = locations.StorageUnavailable(state)
        out |= {"message": {"code": exc.code, "params": exc.params}, "text": str(exc)}
    return out


@router.get("/system/storage", response_model=StorageCapacityRead)
def storage(db: Session = Depends(get_db)):
    """Where ARVA keeps its files: every folder (role, path on this computer as the launcher gave it, path inside
    ARVA, read-only or not, free and total space, filesystem warnings, what it stores), the data folder's storage
    marker and the metadata backups. The top-level numbers are the data folder's free space (no directory walk);
    they are 0 while that folder cannot be read."""
    o = locations.overview(db)
    data = next(loc for loc in o["locations"] if loc["role"] == "data")
    try:
        c = storage_capacity()
        capacity = {"free_bytes": c.free_bytes, "total_bytes": c.total_bytes, "min_free_bytes": c.min_free_bytes,
                    "available_for_data_bytes": c.available_for_data_bytes,
                    "upload_overhead_factor": c.upload_overhead_factor}
    except OSError:
        from app.core.config import get_settings

        capacity = {"free_bytes": 0, "total_bytes": 0, "min_free_bytes": get_settings().min_free_bytes,
                    "available_for_data_bytes": 0, "upload_overhead_factor": 1}
    return StorageCapacityRead(storage_root=data["container_path"], **capacity, data_host_path=data["host_path"],
                               marker=_marker(o["marker"]), locations=o["locations"], backups=o["backups"],
                               in_container=o["in_container"])


@router.post("/system/storage/adopt", response_model=StorageCapacityRead)
def adopt_storage(payload: StorageAdoptRequest, db: Session = Depends(get_db)):
    """Use a data folder that holds another metadata's backups with this ARVA's current metadata (instead of
    restoring them with scripts/restore.sh). Only when the folder's status is restore_needed."""
    if not payload.confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirm must be true")
    try:
        locations.adopt()
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return storage(db)


@router.post("/system/backups", response_model=BackupsRead, status_code=status.HTTP_202_ACCEPTED)
def request_backup():
    """Ask the backup service for a metadata backup now; it makes it within about 30 seconds (pending_since until
    then). 503 while the data folder cannot be written."""
    locations.request_backup()
    return locations.backups_overview()


@router.get("/system/performance", response_model=PerformanceRead)
def get_performance(db: Session = Depends(get_db)):
    """The computer as detected (each fact with its source), the automatic profile and why, the saved choice, what
    each profile gives here, the threads, memory and CPU priority tool runs get now, and what Docker Desktop should
    give ARVA on this Mac. The profiles are ARVA's own heuristics."""
    return performance.overview(db)


@router.put("/system/performance", response_model=PerformanceRead)
def put_performance(payload: PerformanceUpdate, db: Session = Depends(get_db)):
    """Save the profile (auto, light, balanced, maximum, or custom with threads and memory_gb). It applies to jobs
    created from now on; running and queued jobs keep the resources they were given."""
    performance.save_choice(db, payload.model_dump(exclude_none=True))
    return performance.overview(db)
