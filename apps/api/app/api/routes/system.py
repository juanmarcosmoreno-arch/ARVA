from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.schemas import PerformanceRead, PerformanceUpdate, StorageCapacityRead
from app.services import performance
from app.services.capacity import storage_capacity

router = APIRouter(tags=["system"])


@router.get("/system/storage", response_model=StorageCapacityRead)
def storage():
    """Free space on the filesystem holding the ARVA data directory (no directory walk)."""
    c = storage_capacity()
    return StorageCapacityRead(
        storage_root=c.storage_root,
        free_bytes=c.free_bytes,
        total_bytes=c.total_bytes,
        min_free_bytes=c.min_free_bytes,
        available_for_data_bytes=c.available_for_data_bytes,
        upload_overhead_factor=c.upload_overhead_factor,
    )


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
