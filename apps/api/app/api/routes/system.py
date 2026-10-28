from fastapi import APIRouter

from app.schemas.schemas import StorageCapacityRead
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
