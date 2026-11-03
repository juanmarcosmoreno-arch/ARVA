"""Free-space checks on the filesystem that holds the ARVA data directory."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.storage import get_storage

_UNITS = ("KB", "MB", "GB", "TB", "PB")


def fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = n / 1024
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            break
        value /= 1024
    return f"{value:.1f} {unit}"


@dataclass(frozen=True)
class StorageCapacity:
    storage_root: str
    free_bytes: int
    total_bytes: int
    min_free_bytes: int
    upload_overhead_factor: int
    # The free space is the launcher's figure from the start, because Docker reports another disk's for this folder.
    misreported: bool = False

    @property
    def available_for_data_bytes(self) -> int:
        return max(0, self.free_bytes - self.min_free_bytes)


_BUFFER_NOTE = (
    "Uploads are first buffered there, on another disk than the data; import large files from a server folder "
    "instead, which needs no buffer, or free space on that disk (with Docker Desktop: its virtual disk)."
)
_SPOOL_NOTE = (
    "Uploads are first buffered in a temporary file on the same disk, so an upload needs twice its size "
    "while it is received; server folder import needs no buffer."
)


_MISREPORTED_NOTE = (
    "Inside Docker this folder shows another disk's free space, so ARVA counts the figure scripts/start.sh measured "
    "on this computer when ARVA started, minus what ARVA has written to that disk since (Settings → Storage explains "
    "how to share the disk itself)."
)


class InsufficientStorageError(ValueError):
    def __init__(self, needed_bytes: int, capacity: StorageCapacity, note: str = "",
                 where: str = "the ARVA data directory"):
        self.needed_bytes = needed_bytes
        self.capacity = capacity
        if capacity.misreported:
            note = f"{note} {_MISREPORTED_NOTE}".strip()
        super().__init__(
            f"Not enough free space in {where}: {_exact(needed_bytes)} needed "
            f"but only {_exact(capacity.available_for_data_bytes)} can be used "
            f"({fmt_bytes(capacity.free_bytes)} free, {fmt_bytes(capacity.min_free_bytes)} kept in reserve)."
            + (f" {note}" if note else "")
        )


def _exact(n: int) -> str:
    return fmt_bytes(n) if n < 1024 else f"{fmt_bytes(n)} ({n} bytes)"


def upload_overhead_factor(root: Path) -> int:
    """2 when request bodies are spooled to the filesystem holding the data: an upload is then stored twice."""
    try:
        same_disk = os.stat(tempfile.gettempdir()).st_dev == os.stat(root).st_dev
    except OSError:
        same_disk = True
    return 2 if same_disk else 1


def storage_capacity() -> StorageCapacity:
    """The data folder's free space as ARVA counts it: when Docker reports another disk's space for it (Docker
    Desktop sharing an external disk only through /Volumes), the figure scripts/start.sh measured on the host at
    start (app/services/locations.py, free_space)."""
    from app.services.locations import free_space

    root = get_storage().root
    space = free_space(root)
    return StorageCapacity(
        str(root), int(space.free_bytes or 0), int(space.total_bytes or 0), get_settings().min_free_bytes,
        upload_overhead_factor(root), space.misreported,
    )


def ensure_space(needed_bytes: int) -> StorageCapacity:
    capacity = storage_capacity()
    if needed_bytes > capacity.available_for_data_bytes:
        raise InsufficientStorageError(needed_bytes, capacity)
    return capacity


def ensure_upload_space(content_length: int) -> StorageCapacity:
    """Space for a browser upload, counting the spooled copy of the request body."""
    capacity = storage_capacity()
    needed = content_length * capacity.upload_overhead_factor
    if needed > capacity.available_for_data_bytes:
        raise InsufficientStorageError(needed, capacity, _SPOOL_NOTE if capacity.upload_overhead_factor > 1 else "")
    if capacity.upload_overhead_factor == 1:
        # The body is buffered on another disk first (in Docker: the container's /tmp, on the Docker Desktop disk
        # that also holds the database), which must not fill up either.
        spool = tempfile.gettempdir()
        try:
            usage = shutil.disk_usage(spool)
        except OSError:
            return capacity
        buffer = StorageCapacity(spool, usage.free, usage.total, capacity.min_free_bytes, 1)
        if content_length > buffer.available_for_data_bytes:
            raise InsufficientStorageError(content_length, buffer, _BUFFER_NOTE,
                                           where=f"the temporary folder {spool} where uploads are buffered")
    return capacity
