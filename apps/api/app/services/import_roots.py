"""Server folders (ARVA_IMPORT_ROOTS) that can be browsed and imported from.

Every user-supplied path is relative to one configured root. It is resolved
with symlinks followed and rejected unless the result stays inside that root.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from app.core.config import get_settings

MAX_ENTRIES = 2000
# Bounds the work for huge folders; anything beyond is reported as truncated.
_SCAN_LIMIT = 20 * MAX_ENTRIES
_MAX_PATH = 4096
_KINDS = (
    ("fastq", re.compile(r"\.(?:fastq|fq)(?:\.gz)?$", re.IGNORECASE)),
    ("fasta", re.compile(r"\.(?:fasta|fa|fna|fas)(?:\.gz)?$", re.IGNORECASE)),
    ("pod5", re.compile(r"\.pod5$", re.IGNORECASE)),
)


class ImportPathError(ValueError):
    """A requested location is not an accessible path inside an import folder."""


@dataclass(frozen=True)
class ImportRoot:
    index: int
    path: Path
    real: Path

    @property
    def name(self) -> str:
        return self.path.name or str(self.path)

    @property
    def exists(self) -> bool:
        return self.real.is_dir()


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    type: str
    size_bytes: int | None
    kind: str
    modified_at: datetime


@dataclass(frozen=True)
class Listing:
    root: int
    path: str
    parent: str | None
    entries: list[Entry]
    truncated: bool


@dataclass(frozen=True)
class SelectedFile:
    relative: str
    real: Path
    size_bytes: int

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative).name


def file_kind(name: str) -> str:
    return next((kind for kind, rx in _KINDS if rx.search(name)), "other")


def configured_roots() -> list[ImportRoot]:
    return [
        ImportRoot(i, p, Path(os.path.realpath(p))) for i, p in enumerate(get_settings().import_roots)
    ]


def _usable(root: ImportRoot) -> ImportRoot:
    if not root.exists:
        raise ImportPathError(f"Import folder {root.path} does not exist on this server")
    return root


def get_root(index: int) -> ImportRoot:
    roots = configured_roots()
    if not roots:
        raise ImportPathError("Server folder import is not enabled (ARVA_IMPORT_ROOTS is empty)")
    if not 0 <= index < len(roots):
        raise ImportPathError(f"Unknown import folder #{index}")
    return _usable(roots[index])


def root_by_path(path: str) -> ImportRoot:
    for root in configured_roots():
        if str(root.path) == path:
            return _usable(root)
    raise ImportPathError(f"{path} is not a configured import folder (check ARVA_IMPORT_ROOTS)")


def _clean(relative: str) -> PurePosixPath:
    if len(relative) > _MAX_PATH or "\x00" in relative or "\\" in relative:
        raise ImportPathError("Invalid path")
    if relative.startswith("/"):
        raise ImportPathError("Absolute paths are not allowed; give a path relative to the import folder")
    parts = PurePosixPath(relative).parts
    if ".." in parts:
        raise ImportPathError("'..' is not allowed in import paths")
    if any(p.startswith(".") for p in parts):
        raise ImportPathError("Hidden files and folders cannot be browsed or imported")
    return PurePosixPath(*parts) if parts else PurePosixPath()


def _contained(root: ImportRoot, path: Path) -> Path | None:
    real = Path(os.path.realpath(path))
    return real if real == root.real or root.real in real.parents else None


def resolve(root: ImportRoot, relative: str) -> tuple[str, Path]:
    """Validate a root-relative path; returns its normalised form and its real location."""
    rel = _clean(relative)
    real = _contained(root, root.real / rel)
    if real is None:
        raise ImportPathError(f"{relative!r} points outside the import folder")
    return (rel.as_posix() if rel.parts else ""), real


def browse(root: ImportRoot, relative: str) -> Listing:
    rel, real = resolve(root, relative)
    if not real.is_dir():
        raise ImportPathError(f"{rel or '/'} is not a folder")
    found: list[tuple[bool, str, os.stat_result]] = []
    truncated = False
    try:
        with os.scandir(real) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                if len(found) >= _SCAN_LIMIT:
                    truncated = True
                    break
                target = _contained(root, Path(entry.path)) if entry.is_symlink() else Path(entry.path)
                if target is None:
                    continue
                try:
                    st = target.stat()
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode):
                    found.append((stat.S_ISDIR(st.st_mode), entry.name, st))
    except PermissionError as exc:
        raise ImportPathError(f"{rel or '/'} cannot be read by ARVA (permission denied)") from exc
    found.sort(key=lambda f: (not f[0], f[1].casefold(), f[1]))
    if len(found) > MAX_ENTRIES:
        truncated = True
        found = found[:MAX_ENTRIES]
    entries = [
        Entry(
            name=name,
            path=f"{rel}/{name}" if rel else name,
            type="dir" if is_dir else "file",
            size_bytes=None if is_dir else st.st_size,
            kind="other" if is_dir else file_kind(name),
            modified_at=datetime.fromtimestamp(st.st_mtime, UTC),
        )
        for is_dir, name, st in found
    ]
    parent = None if not rel else PurePosixPath(rel).parent.as_posix()
    return Listing(root.index, rel, "" if parent == "." else parent, entries, truncated)


def resolve_file(root: ImportRoot, relative: str) -> SelectedFile:
    """A readable regular file inside the root (symlinks allowed only if they stay inside)."""
    rel, real = resolve(root, relative)
    if not rel:
        raise ImportPathError("A file path is required")
    try:
        st = os.stat(real)
    except FileNotFoundError as exc:
        raise ImportPathError(f"{rel}: file not found") from exc
    except OSError as exc:
        raise ImportPathError(f"{rel}: cannot be read ({exc.strerror})") from exc
    if not stat.S_ISREG(st.st_mode):
        raise ImportPathError(f"{rel}: not a regular file")
    if not os.access(real, os.R_OK):
        raise ImportPathError(f"{rel}: ARVA has no permission to read this file")
    return SelectedFile(rel, real, st.st_size)


def open_source(selected: SelectedFile) -> BinaryIO:
    """Open read-only, refusing a symlink swapped in after validation."""
    fd = os.open(selected.real, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ImportPathError(f"{selected.relative}: not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
