"""Free-space checks on the filesystem that holds the ARVA data directory."""
from __future__ import annotations

import shutil
from dataclasses import dataclass

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

    @property
    def available_for_data_bytes(self) -> int:
        return max(0, self.free_bytes - self.min_free_bytes)


class InsufficientStorageError(ValueError):
    def __init__(self, needed_bytes: int, capacity: StorageCapacity):
        self.needed_bytes = needed_bytes
        self.capacity = capacity
        super().__init__(
            f"Not enough free space in the ARVA data directory: {_exact(needed_bytes)} needed "
            f"but only {_exact(capacity.available_for_data_bytes)} can be used "
            f"({fmt_bytes(capacity.free_bytes)} free, {fmt_bytes(capacity.min_free_bytes)} kept in reserve)."
        )


def _exact(n: int) -> str:
    return fmt_bytes(n) if n < 1024 else f"{fmt_bytes(n)} ({n} bytes)"


def storage_capacity() -> StorageCapacity:
    root = get_storage().root
    usage = shutil.disk_usage(root)
    return StorageCapacity(str(root), usage.free, usage.total, get_settings().min_free_bytes)


def ensure_space(needed_bytes: int) -> StorageCapacity:
    capacity = storage_capacity()
    if needed_bytes > capacity.available_for_data_bytes:
        raise InsufficientStorageError(needed_bytes, capacity)
    return capacity
