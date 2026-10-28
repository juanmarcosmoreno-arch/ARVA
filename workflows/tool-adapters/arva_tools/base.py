"""Adapter base class: metadata, executable discovery and version detection."""
from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from arva_tools.runner import isolated_home, tool_environment


class ToolStatus(str, enum.Enum):
    available = "available"
    not_installed = "not_installed"
    incompatible = "incompatible"
    failed = "failed"


@dataclass(frozen=True)
class ToolInfo:
    id: str
    name: str
    description: str
    homepage: str
    license: str
    citation: str
    citation_url: str
    executable: str
    categories: tuple[str, ...]
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    min_version: str
    tested_versions: tuple[str, ...]
    install: dict[str, str] = field(default_factory=dict)


@dataclass
class DetectedTool:
    info: ToolInfo
    status: ToolStatus
    path: str | None = None
    version: str | None = None
    version_validated: bool = False
    message: str = ""
    # Stable code for a tool-specific message, so the interface can show it in the user's language.
    reason: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


def resolve_executable(tool_id: str, executable: str) -> str | None:
    """Find a tool: ARVA_TOOL_<ID> override, then ARVA_TOOLS_PATH, then PATH."""
    override = os.environ.get(f"ARVA_TOOL_{tool_id.upper().replace('-', '_')}")
    if override:
        p = Path(override)
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None
    extra = os.environ.get("ARVA_TOOLS_PATH")
    if extra:
        found = shutil.which(executable, path=extra)
        if found:
            return found
    return shutil.which(executable)


class ToolAdapter:
    info: ToolInfo
    version_args: tuple[str, ...] = ("--version",)
    version_pattern: re.Pattern[str]

    def detect(self) -> DetectedTool:
        path = resolve_executable(self.info.id, self.info.executable)
        if path is None:
            return DetectedTool(self.info, ToolStatus.not_installed, message="Executable not found")
        try:
            with isolated_home() as home:
                proc = subprocess.run(
                    [path, *self.version_args],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=tool_environment(home),
                    cwd=home,
                    stdin=subprocess.DEVNULL,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DetectedTool(self.info, ToolStatus.failed, path, message=f"Could not run: {exc}")
        match = self.version_pattern.search(proc.stdout + "\n" + proc.stderr)
        if not match:
            return DetectedTool(
                self.info, ToolStatus.failed, path, message="Version could not be determined"
            )
        version = match.group(1)
        if parse_version(version) < parse_version(self.info.min_version):
            return DetectedTool(
                self.info,
                ToolStatus.incompatible,
                path,
                version,
                message=f"Version {version} is older than the minimum supported {self.info.min_version}",
            )
        validated = version in self.info.tested_versions
        return DetectedTool(
            self.info,
            ToolStatus.available,
            path,
            version,
            validated,
            "" if validated else
            f"Version {version} has not been validated with ARVA (validated: {', '.join(self.info.tested_versions)})",
        )
