"""Local filesystem storage for scientific data.

All paths stored in the database are *relative* to the storage root; the
backend resolves them here, which keeps a single choke point for path
validation and lets an S3-style backend implement the same interface later.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings

CHUNK_SIZE = 1 << 20
# How often save_stream re-checks free space: other uploads or imports may be writing at the same time.
SPACE_CHECK_BYTES = 256 * CHUNK_SIZE
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StoragePathError(ValueError):
    """Raised when a path would escape the storage root."""


class FileTooLargeError(ValueError):
    def __init__(self, max_bytes: int):
        super().__init__(f"file exceeds the {max_bytes} byte limit (ARVA_MAX_UPLOAD_SIZE_BYTES)")


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    size_bytes: int
    sha256: str


class StorageBackend(Protocol):
    def save_stream(
        self, stream: BinaryIO, relative_path: str, max_bytes: int,
        space_check: Callable[[int], None] | None = None,
    ) -> StoredFile: ...
    def resolve(self, relative_path: str) -> Path: ...
    def write_text(self, relative_path: str, content: str) -> str: ...


def sanitize_filename(name: str) -> str:
    """Reduce a user-supplied filename to a safe ASCII basename (no directories); 'Perú' becomes 'Peru'."""
    base = name.replace("\\", "/").split("/")[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFKD", base) if not unicodedata.combining(ch))
    base = _SAFE_NAME.sub("_", base).strip("._")
    return base[:200] or "file"


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StoragePathError(f"path escapes storage root: {relative_path!r}")
        return candidate

    def save_stream(
        self, stream: BinaryIO, relative_path: str, max_bytes: int,
        space_check: Callable[[int], None] | None = None,
    ) -> StoredFile:
        """Stream to disk while hashing (space_check(written) may abort every SPACE_CHECK_BYTES); stored read-only."""
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise StoragePathError(f"refusing to overwrite existing file: {relative_path!r}")
        tmp = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        size = checked = 0
        try:
            with open(tmp, "xb") as out:
                while chunk := stream.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError(max_bytes)
                    digest.update(chunk)
                    out.write(chunk)
                    if space_check is not None and size - checked >= SPACE_CHECK_BYTES:
                        checked = size
                        out.flush()
                        space_check(size)
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return StoredFile(relative_path, size, digest.hexdigest())

    def write_text(self, relative_path: str, content: str) -> str:
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return relative_path

    def seal(self, relative_path: str) -> StoredFile:
        """Checksum a file written by a tool and make it read-only (immutable from now on)."""
        target = self.resolve(relative_path)
        digest = hashlib.sha256()
        size = 0
        with open(target, "rb") as fh:
            while chunk := fh.read(CHUNK_SIZE):
                size += len(chunk)
                digest.update(chunk)
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return StoredFile(relative_path, size, digest.hexdigest())

    def remove_tree(self, relative_path: str) -> None:
        """Delete partial outputs of a failed job. Original data (raw/) can never be removed."""
        if not relative_path.startswith(("results/", "processed/")):
            raise StoragePathError(f"refusing to delete outside results/ or processed/: {relative_path!r}")
        target = self.resolve(relative_path)
        if not target.exists():
            return
        for dirpath, _dirs, files in os.walk(target):
            os.chmod(dirpath, stat.S_IRWXU)
            for f in files:
                os.chmod(os.path.join(dirpath, f), stat.S_IRUSR | stat.S_IWUSR)
        shutil.rmtree(target)

    def usage_bytes(self) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(self.root):
            for f in files:
                try:
                    total += os.lstat(os.path.join(dirpath, f)).st_size
                except OSError:
                    pass
        return total


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_root)
