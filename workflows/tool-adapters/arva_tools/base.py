"""Adapter base class: metadata, executable discovery and version detection."""
from __future__ import annotations

import enum
import os
import platform
import re
import shutil
import subprocess
import sys
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
    # The platforms with a checked-in Bioconda lock (docker/conda-locks/<id>/); empty for tools from other sources.
    conda_platforms: tuple[str, ...] = ()


@dataclass
class DetectedTool:
    info: ToolInfo
    status: ToolStatus
    path: str | None = None
    version: str | None = None
    version_validated: bool = False
    message: str = ""
    # Stable code of the message, with its values, so the interface can show it in the user's language.
    reason: str | None = None
    reason_params: dict[str, str] = field(default_factory=dict)


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


_HELP_OPTION = re.compile(r"^\s+(--?[A-Za-z0-9][\w-]*)(?:,\s+(--[A-Za-z0-9][\w-]*))?(?=[\s,]|$)")


def help_options(text: str) -> frozenset[str]:
    """The options a --help text lists at the start of its lines ("  -t, --threads <int>", "  -1 <filename>")."""
    found: set[str] = set()
    for line in text.splitlines():
        if m := _HELP_OPTION.match(line):
            found.update(o for o in m.groups() if o)
    return frozenset(found)


def read_help(executable: str, args: tuple[str, ...] = ("--help",), extra_env: dict[str, str] | None = None) -> str:
    with isolated_home() as home:
        proc = subprocess.run([executable, *args], capture_output=True, text=True, errors="replace", timeout=60,
                              env={**tool_environment(home), **(extra_env or {})}, cwd=home, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(executable).name} {' '.join(args)} exited with status {proc.returncode}")
    return proc.stdout + proc.stderr


def conda_platform() -> str | None:
    """This machine's platform in Bioconda's naming, for the platforms ARVA has locks for."""
    machine = platform.machine().lower()
    if sys.platform != "linux":
        return None
    return {"x86_64": "linux-64", "amd64": "linux-64", "aarch64": "linux-aarch64", "arm64": "linux-aarch64"}.get(machine)


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


# How long the version check may take, and how long its one retry may take when the first attempt timed out or
# printed no version: a tool that imports a large library (Medaka loads PyTorch) can take minutes under Rosetta on a
# Mac with its memory taken, and was once marked unusable with no reason right after a run used all the memory.
VERSION_TIMEOUT_SECONDS = 60
VERSION_RETRY_TIMEOUT_SECONDS = 180
OUTPUT_TAIL_CHARS = 300


def output_tail(text: str, limit: int = OUTPUT_TAIL_CHARS) -> str:
    """The last characters of a tool's output, on one line, for a reason shown to the user."""
    return " ".join(text.split())[-limit:]


class ToolAdapter:
    info: ToolInfo
    version_args: tuple[str, ...] = ("--version",)
    version_pattern: re.Pattern[str]
    version_timeout: float = VERSION_TIMEOUT_SECONDS
    version_retry_timeout: float = VERSION_RETRY_TIMEOUT_SECONDS

    def _run_version(self, path: str, timeout: float) -> subprocess.CompletedProcess[str]:
        with isolated_home() as home:
            return subprocess.run([path, *self.version_args], capture_output=True, text=True, errors="replace",
                                  timeout=timeout, env={**tool_environment(home), **self.environment(path)}, cwd=home,
                                  stdin=subprocess.DEVNULL)

    def _read_version(self, path: str) -> re.Match[str] | DetectedTool:
        """The version line's match, or why it could not be read (a failed DetectedTool with its reason): the check
        runs once more, with the longer timeout, when the first attempt timed out or printed no version, so a tool
        slowed down for a moment (memory taken, a large library loading) is not declared unusable."""
        failure: DetectedTool | None = None
        for timeout in (self.version_timeout, self.version_retry_timeout):
            try:
                proc = self._run_version(path, timeout)
            except subprocess.TimeoutExpired:
                failure = DetectedTool(
                    self.info, ToolStatus.failed, path,
                    message=f"{Path(path).name} {' '.join(self.version_args)} did not answer within {timeout:g} s "
                            f"(after a first attempt of {self.version_timeout:g} s)",
                    reason="version_timeout", reason_params={"seconds": f"{timeout:g}",
                                                             "first": f"{self.version_timeout:g}"})
                continue
            except OSError as exc:
                return DetectedTool(self.info, ToolStatus.failed, path, message=f"Could not run: {exc}",
                                    reason="not_runnable", reason_params={"detail": str(exc)})
            output = proc.stdout + "\n" + proc.stderr
            if match := self.version_pattern.search(output):
                return match
            if proc.returncode != 0:
                tail = output_tail(proc.stderr or proc.stdout)
                failure = DetectedTool(
                    self.info, ToolStatus.failed, path,
                    message=f"{Path(path).name} {' '.join(self.version_args)} exited with status {proc.returncode}"
                            + (f": {tail}" if tail else ""),
                    reason="version_exit", reason_params={"status": str(proc.returncode), "output": tail})
            else:
                failure = DetectedTool(self.info, ToolStatus.failed, path, message="Version could not be determined",
                                       reason="no_version", reason_params={"output": output_tail(output)})
        assert failure is not None
        return failure

    def environment(self, executable: str) -> dict[str, str]:
        """Variables the tool needs on top of the cleaned environment (e.g. its own environment's bin/ first)."""
        return {}

    def detect(self) -> DetectedTool:
        path = resolve_executable(self.info.id, self.info.executable)
        if path is None:
            plat = conda_platform()
            if self.info.conda_platforms and plat not in self.info.conda_platforms:
                return DetectedTool(
                    self.info, ToolStatus.not_installed,
                    message=f"Executable not found; ARVA has no Bioconda lock of {self.info.name} for "
                            f"{plat or 'this platform'} (only {', '.join(self.info.conda_platforms)})",
                    reason="no_conda_platform",
                    reason_params={"platform": plat or "?", "platforms": ", ".join(self.info.conda_platforms)})
            return DetectedTool(self.info, ToolStatus.not_installed, message="Executable not found", reason="not_found")
        found = self._read_version(path)
        if isinstance(found, DetectedTool):
            return found
        match = found
        version = match.group(1)
        if parse_version(version) < parse_version(self.info.min_version):
            return DetectedTool(
                self.info,
                ToolStatus.incompatible,
                path,
                version,
                message=f"Version {version} is older than the minimum supported {self.info.min_version}",
                reason="too_old",
                reason_params={"version": version, "min": self.info.min_version},
            )
        validated = version in self.info.tested_versions
        tested = ", ".join(self.info.tested_versions)
        if validated:
            return DetectedTool(self.info, ToolStatus.available, path, version, True)
        return DetectedTool(
            self.info, ToolStatus.available, path, version, False,
            f"Version {version} has not been validated with ARVA (validated: {tested})",
            "not_validated", {"version": version, "tested": tested},
        )
