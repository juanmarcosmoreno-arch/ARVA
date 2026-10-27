"""Local filesystem storage for scientific data.

All paths stored in the database are *relative* to the storage root; the
backend resolves them here, which keeps a single choke point for path
validation and lets an S3-style backend implement the same interface later.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings

CHUNK_SIZE = 1 << 20
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StoragePathError(ValueError):
    """Raised when a path would escape the storage root."""


class FileTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    size_bytes: int
    sha256: str


class StorageBackend(Protocol):
    def save_stream(self, stream: BinaryIO, relative_path: str, max_bytes: int) -> StoredFile: ...
    def resolve(self, relative_path: str) -> Path: ...
    def write_text(self, relative_path: str, content: str) -> str: ...


def sanitize_filename(name: str) -> str:
    """Reduce a user-supplied filename to a safe basename (no directories)."""
    base = name.replace("\\", "/").split("/")[-1]
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

    def save_stream(self, stream: BinaryIO, relative_path: str, max_bytes: int) -> StoredFile:
        """Stream to disk while hashing; the stored raw file is made read-only."""
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise StoragePathError(f"refusing to overwrite existing file: {relative_path!r}")
        tmp = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        size = 0
        try:
            with open(tmp, "xb") as out:
                while chunk := stream.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError(f"file exceeds the {max_bytes} byte limit")
                    digest.update(chunk)
                    out.write(chunk)
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
