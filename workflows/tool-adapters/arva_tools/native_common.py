"""What the native entries of every tool share (ARVA.app runs a tool on the user's Mac: docs/plan-flye-nativo.md,
"Contrato implementado"). Standard library only: ARVA.app runs these modules with the Python of the tool's own
osx-arm64 environment, isolated (-I), without arva_core or the adapter registry.

Paths travel between the API and the Mac only relative to a folder both sides know (the data folder, or a database
folder named in arva.conf), with ARVA's own plain components; each side joins them to its own root and checks, once
links are resolved, that the result stays inside it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

# A component of a path relative to the data folder: ARVA's own names (UUIDs, "_project", "input", "flye", the read
# link names of read_link_name). Never "." or "..", never empty (no "//", no leading or trailing "/").
_REL_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,200}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_STORAGE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class NativeRefusal(ValueError):
    """The work cannot run on this Mac as sent; `code` names the reason for the API and the interface."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


class NativeStopped(BaseException):
    """ARVA.app asked the run to stop (SIGTERM): run_command kills the tool's process group."""


def native_relative(rel: Any) -> str:
    """A path relative to the data folder, as ARVA writes them: components of letters, digits, '_', '.', '-' only,
    none of them '.' or '..', no leading '/'. Raises NativeRefusal("unsafe_path") otherwise."""
    if not isinstance(rel, str) or not rel or len(rel) > 1024:
        raise NativeRefusal("unsafe_path", f"not a relative path: {rel!r}")
    if not all(_REL_PART.fullmatch(part) for part in rel.split("/")):
        raise NativeRefusal("unsafe_path", f"{rel!r} is not a plain path inside the data folder (absolute, '..', "
                                           "an empty component or another character)")
    return rel


def native_folder(path: Any, tool: str, what: str = "the data folder") -> str:
    """A folder as given (absolute, normalised, without spaces: ARVA refuses them for native runs)."""
    if not isinstance(path, str) or not path.startswith("/") or path == "/" or len(path) > 1024 \
            or _CONTROL.search(path) or os.path.normpath(path) != path:
        raise NativeRefusal("unsafe_path", f"{what} must be an absolute, normalised path: {path!r}")
    if any(c.isspace() for c in path):
        raise NativeRefusal("path_has_spaces", f"{tool} runs natively only from paths without spaces: {path}")
    return path


def native_program(path: Any, name: str) -> str:
    """A program's path on the Mac as reported by ARVA.app: absolute, normalised, no spaces or control characters,
    and named `name`."""
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 1024 or _CONTROL.search(path) \
            or os.path.normpath(path) != path or any(c.isspace() for c in path) or Path(path).name != name:
        raise NativeRefusal("unsafe_path", f"not an absolute path to a {name} executable: {path!r}")
    return path


def native_path(root: str, rel: str, must_exist: bool = True, what: str = "the data folder") -> str:
    """root/rel after checking that it stays inside root once links are resolved (a link may point at a stored file;
    a folder the tool creates does not exist yet, so its parent is checked)."""
    native_relative(rel)
    path = f"{root}/{rel}"
    top = os.path.realpath(root)
    # A folder the tool creates may already be there (a resumed run's work folder): then it is checked itself, so that a
    # link in its place cannot lead the tool's writes outside.
    real = os.path.realpath(path if must_exist or os.path.lexists(path) else os.path.dirname(path))
    if real != top and not real.startswith(top + os.sep):
        raise NativeRefusal("outside_data_dir", f"{rel} leads outside {what} ({real})")
    if must_exist and not os.path.exists(path):
        raise NativeRefusal("input_missing", f"{rel} does not exist in {what}")
    return path


def check_storage(data_dir: str, storage_id: Any) -> None:
    """<data_dir>/.arva-storage must hold the storage ID the API gave: the same folder ARVA's containers use."""
    try:
        marker = json.loads(Path(data_dir, ".arva-storage").read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError, AttributeError):
        marker = None
    if not isinstance(marker, str) or not _STORAGE_ID.fullmatch(marker) or marker != storage_id:
        raise NativeRefusal("storage_mismatch", f"{data_dir}/.arva-storage does not hold the storage ID the API "
                                                "gave: this is not the data folder ARVA's containers use")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sysctl(name: str) -> str | None:
    exe = "/usr/sbin/sysctl"
    if not os.path.exists(exe):
        return None
    try:
        proc = subprocess.run([exe, "-n", name], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


def conda_package(executable: str, name: str) -> dict[str, Any] | None:
    """The installed package `name` of the environment `executable` belongs to (its conda-meta record)."""
    record: dict[str, Any] = {}
    for meta in sorted((Path(executable).resolve().parent.parent / "conda-meta").glob(f"{name}-*.json")):
        data = json.loads(meta.read_text())
        if data.get("name") == name:
            record = data
    if not record:
        return None
    return {"version": record.get("version"), "build": record.get("build"), "sha256": record.get("sha256"),
            "url": record.get("url")}


def mac_facts(conda_platform: str | None) -> dict[str, Any]:
    """The Mac a native tool runs on: conda platform, macOS version, chip and memory."""
    memsize = sysctl("hw.memsize")
    return {"platform": conda_platform, "macos": platform.mac_ver()[0] or None,
            "chip": sysctl("machdep.cpu.brand_string"),
            "memory_bytes": int(memsize) if memsize and memsize.isdigit() else None}
