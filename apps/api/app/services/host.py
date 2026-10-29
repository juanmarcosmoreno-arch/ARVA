"""What this computer gives ARVA: the CPUs and memory this process can actually use, whether it runs in a container,
and facts about the host computer.

Host facts come from two places: a launcher (scripts/start.sh reads them on a Mac and passes them in as ARVA_HOST_*
environment variables, untrusted strings that are validated and bounded here), and, when ARVA runs natively on
macOS, sysctl, sw_vers and system_profiler read directly (argument vectors, no shell). Every reader is defensive: a
missing or malformed value is unknown, never a guess. The parsers are pure functions so they can be tested with
constructed inputs; nothing here has run on a real Mac yet (docs/installation.md).
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

GIB = 1024**3
MAX_TEXT = 80
_CORES = (1, 1024)
_MEMORY = (256 * 1024**2, 64 * 1024**4)
_VERSION = re.compile(r"\d{1,3}(?:\.\d{1,3}){0,2}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# A cgroup limit at least this large means "no limit" (cgroup v1 reports unlimited as a page-aligned LONG_MAX).
_UNLIMITED = 1 << 60

SYSCTL = "/usr/sbin/sysctl"
SW_VERS = "/usr/bin/sw_vers"
SYSTEM_PROFILER = "/usr/sbin/system_profiler"


@dataclass(frozen=True)
class Fact:
    value: Any = None
    source: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None


UNKNOWN = Fact()


@dataclass(frozen=True)
class HostFacts:
    """The computer ARVA runs on, as far as it is known. Inside Docker Desktop this is the Mac, not the Linux VM."""
    platform: Fact = UNKNOWN
    model_name: Fact = UNKNOWN
    model_id: Fact = UNKNOWN
    chip: Fact = UNKNOWN
    performance_cores: Fact = UNKNOWN
    efficiency_cores: Fact = UNKNOWN
    physical_cores: Fact = UNKNOWN
    logical_cpus: Fact = UNKNOWN
    memory_bytes: Fact = UNKNOWN
    os_version: Fact = UNKNOWN
    arch: Fact = UNKNOWN
    docker_cpus: Fact = UNKNOWN
    docker_memory_bytes: Fact = UNKNOWN

    @property
    def is_mac(self) -> bool:
        return self.platform.value == "macos"

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {name: {"value": f.value, "source": f.source} for name, f in vars(self).items()}


@dataclass(frozen=True)
class ContainerFacts:
    """What this process can use: CPUs (affinity and CPU quota) and memory (memory limit, or the memory the
    kernel reports)."""
    usable_cpus: int
    cpus_source: str
    memory_bytes: int | None
    memory_source: str | None
    in_container: bool = False
    container_marker: str | None = None

    @property
    def memory_gb(self) -> float | None:
        return None if self.memory_bytes is None else self.memory_bytes / GIB


@dataclass(frozen=True)
class Detection:
    host: HostFacts
    container: ContainerFacts
    notes: list[str] = field(default_factory=list)


# --- Parsers (pure) --------------------------------------------------------------------------------------------

def clean_text(value: str | None, limit: int = MAX_TEXT) -> str | None:
    """A printable, bounded copy of an untrusted string; None when nothing printable is left."""
    if value is None:
        return None
    text = " ".join(_CONTROL.sub(" ", value).split())[:limit].strip()
    return text or None


def parse_int(value: str | None, bounds: tuple[int, int]) -> int | None:
    text = (value or "").strip()
    if not text.isdigit() or len(text) > 20:
        return None
    n = int(text)
    return n if bounds[0] <= n <= bounds[1] else None


def parse_version(value: str | None) -> str | None:
    text = (value or "").strip()
    return text if _VERSION.fullmatch(text) else None


def parse_arch(value: str | None) -> str | None:
    text = (value or "").strip()
    return text if text in ("arm64", "x86_64") else None


def parse_cpu_max(text: str) -> float | None:
    """cgroup v2 cpu.max, "$MAX $PERIOD" ("max" = no limit; Documentation/admin-guide/cgroup-v2.rst): the CPUs the
    quota allows, or None."""
    parts = text.split()
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        quota, period = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return quota / period if quota > 0 and period > 0 else None


def parse_cfs_quota(quota_text: str, period_text: str) -> float | None:
    """cgroup v1 cpu.cfs_quota_us / cpu.cfs_period_us (-1 = no limit; Documentation/scheduler/sched-bwc.rst)."""
    try:
        quota, period = int(quota_text.strip()), int(period_text.strip())
    except ValueError:
        return None
    return quota / period if quota > 0 and period > 0 else None


def parse_memory_limit(text: str) -> int | None:
    """cgroup v2 memory.max ("max" = no limit) or v1 memory.limit_in_bytes, in bytes; None without a limit."""
    value = text.strip()
    if not value.isdigit():
        return None
    n = int(value)
    return n if 0 < n < _UNLIMITED else None


def parse_meminfo(text: str) -> int | None:
    """MemTotal of /proc/meminfo, in bytes."""
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * (1024 if len(parts) < 3 or parts[2] == "kB" else 1)
    return None


def cgroup_paths(text: str) -> dict[str, str]:
    """/proc/self/cgroup: the cgroup v2 path (key "") and each v1 controller's path."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _, controllers, path = parts
        path = path.removesuffix(" (deleted)")
        if not controllers:
            out[""] = path
        for c in controllers.split(","):
            if c:
                out[c] = path
    return out


def parse_processors(text: str | None) -> tuple[int, int, int] | None:
    """system_profiler's number_processors on Apple silicon, "proc TOTAL:PERFORMANCE:EFFICIENCY" (a plain number on
    Intel Macs; see mondoohq/cnquery providers/os/resources/macos_hardware.go)."""
    m = re.fullmatch(r"proc (\d{1,4}):(\d{1,4}):(\d{1,4})", (text or "").strip())
    if not m:
        return None
    total, perf, eff = (int(g) for g in m.groups())
    return (total, perf, eff) if total == perf + eff and perf >= 1 else None


def parse_system_profiler(text: str) -> dict[str, str]:
    """machine_name, machine_model, chip_type and number_processors of `system_profiler -json SPHardwareDataType`
    (the only keys ARVA keeps; the serial number and UUIDs are never read). Tolerates text before the JSON, such as
    the log line macOS 26.3.1 and 26.4 print (Apple developer forums, thread 820473)."""
    start = text.find("{")
    try:
        data = json.loads(text[start:]) if start >= 0 else {}
        item = data["SPHardwareDataType"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return {}
    if not isinstance(item, dict):
        return {}
    return {k: str(item[k]) for k in ("machine_name", "machine_model", "chip_type", "number_processors")
            if isinstance(item.get(k), str | int)}


# --- Readers ---------------------------------------------------------------------------------------------------

def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _candidates(base: Path, path: str | None) -> list[Path]:
    """The process's own cgroup folder and its ancestors up to the mount point (limits apply hierarchically), or
    only the mount point when the path is unknown (inside a container's cgroup namespace it is "/")."""
    dirs = [base]
    if path and path != "/":
        parts = [p for p in path.split("/") if p]
        dirs = [base.joinpath(*parts[:i]) for i in range(len(parts), 0, -1)] + [base]
    return dirs


def cpu_quota(root: Path = Path("/")) -> tuple[float | None, str | None]:
    """The tightest CPU quota on this process's cgroups: (CPUs, "cgroup_v2" | "cgroup_v1"), or (None, None)."""
    paths = cgroup_paths(_read(root / "proc/self/cgroup") or "")
    fs = root / "sys/fs/cgroup"
    found = [q for d in _candidates(fs, paths.get("")) if (t := _read(d / "cpu.max")) and (q := parse_cpu_max(t))]
    if found:
        return min(found), "cgroup_v2"
    for mount in ("cpu,cpuacct", "cpu"):
        base = fs / mount
        for d in _candidates(base, paths.get("cpu")):
            quota, period = _read(d / "cpu.cfs_quota_us"), _read(d / "cpu.cfs_period_us")
            if quota is not None and period is not None and (q := parse_cfs_quota(quota, period)):
                found.append(q)
        if found:
            return min(found), "cgroup_v1"
    return None, None


def memory_limit(root: Path = Path("/")) -> tuple[int | None, str | None]:
    paths = cgroup_paths(_read(root / "proc/self/cgroup") or "")
    fs = root / "sys/fs/cgroup"
    found = [m for d in _candidates(fs, paths.get("")) if (t := _read(d / "memory.max")) and (m := parse_memory_limit(t))]
    if found:
        return min(found), "cgroup_v2"
    found = [m for d in _candidates(fs / "memory", paths.get("memory"))
             if (t := _read(d / "memory.limit_in_bytes")) and (m := parse_memory_limit(t))]
    return (min(found), "cgroup_v1") if found else (None, None)


def container_marker(root: Path = Path("/"), environ: Mapping[str, str] | None = None) -> str | None:
    """How the container shows itself, as systemd's detect-virt checks (src/basic/virt.c): /.dockerenv (Docker),
    /run/.containerenv (Podman) or the `container` environment variable."""
    environ = os.environ if environ is None else environ
    if (root / ".dockerenv").exists():
        return "docker"
    if (root / "run/.containerenv").exists():
        return "podman"
    return clean_text(environ.get("container"), 40)


def _affinity() -> tuple[int, str]:
    if hasattr(os, "sched_getaffinity"):
        try:
            return len(os.sched_getaffinity(0)), "affinity"
        except OSError:
            pass
    return os.cpu_count() or 1, "cpu_count"


def _physical_memory() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def read_container(root: Path = Path("/"), environ: Mapping[str, str] | None = None,
                   affinity: Callable[[], tuple[int, str]] = _affinity, macos_memory: int | None = None
                   ) -> ContainerFacts:
    cpus, cpus_source = affinity()
    quota, quota_source = cpu_quota(root)
    if quota is not None and math.ceil(quota) < cpus:
        cpus, cpus_source = max(1, math.ceil(quota)), quota_source or cpus_source
    total = parse_meminfo(_read(root / "proc/meminfo") or "")
    total_source = "meminfo" if total else None
    if total is None and macos_memory is not None:
        total, total_source = macos_memory, "macos"
    if total is None:
        total = _physical_memory()
        total_source = "sysconf" if total else None
    limit, limit_source = memory_limit(root)
    if limit is not None and (total is None or limit < total):
        total, total_source = limit, limit_source
    marker = container_marker(root, environ)
    return ContainerFacts(usable_cpus=max(1, cpus), cpus_source=cpus_source, memory_bytes=total,
                          memory_source=total_source, in_container=marker is not None, container_marker=marker)


def read_launcher(environ: Mapping[str, str]) -> HostFacts:
    """The ARVA_HOST_* variables scripts/start.sh sets: validated, bounded, and unknown when empty or malformed."""
    def get(name: str) -> str | None:
        return environ.get(f"ARVA_HOST_{name}") or None

    def fact(value: Any) -> Fact:
        return Fact(value, "launcher") if value is not None else UNKNOWN

    platform = (get("PLATFORM") or "").strip().lower()
    return HostFacts(
        platform=fact(platform if platform in ("macos", "linux") else None),
        model_name=fact(clean_text(get("MODEL_NAME"))),
        model_id=fact(clean_text(get("MODEL_ID"), 40)),
        chip=fact(clean_text(get("CHIP"))),
        performance_cores=fact(parse_int(get("PERF_CORES"), _CORES)),
        efficiency_cores=fact(parse_int(get("EFF_CORES"), (0, _CORES[1]))),
        physical_cores=fact(parse_int(get("PHYSICAL_CORES"), _CORES)),
        logical_cpus=fact(parse_int(get("LOGICAL_CPUS"), _CORES)),
        memory_bytes=fact(parse_int(get("MEMORY_BYTES"), _MEMORY)),
        os_version=fact(parse_version(get("OS_VERSION"))),
        arch=fact(parse_arch(get("ARCH"))),
        docker_cpus=fact(parse_int(get("DOCKER_CPUS"), _CORES)),
        docker_memory_bytes=fact(parse_int(get("DOCKER_MEMORY_BYTES"), _MEMORY)),
    )


def _run(argv: list[str]) -> str | None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def read_macos(run: Callable[[list[str]], str | None] = _run) -> HostFacts:
    """This Mac, read directly when ARVA runs natively on macOS. Keys: Apple's "Determining system capabilities"
    (hw.nperflevels, hw.perflevelN.physicalcpu with N = 0 the fastest cores, hw.physicalcpu, hw.logicalcpu,
    hw.memsize), sysctl(3) (hw.model, machdep.cpu.brand_string) and "About the Rosetta translation environment"
    (sysctl.proc_translated). Intel Macs and older macOS lack some keys; those facts stay unknown."""
    def sysctl(key: str) -> str | None:
        out = run([SYSCTL, "-n", key])
        return out.strip() if out else None

    def fact(value: Any) -> Fact:
        return Fact(value, "macos") if value is not None else UNKNOWN

    levels = parse_int(sysctl("hw.nperflevels"), (1, 8))
    perf = eff = None
    if levels and levels >= 2:
        perf = parse_int(sysctl("hw.perflevel0.physicalcpu"), _CORES)
        counts = [parse_int(sysctl(f"hw.perflevel{n}.physicalcpu"), (0, _CORES[1])) for n in range(1, levels)]
        eff = sum(counts) if perf and all(c is not None for c in counts) else None
    profile = parse_system_profiler(run([SYSTEM_PROFILER, "-json", "SPHardwareDataType"]) or "")
    if perf is None and (procs := parse_processors(profile.get("number_processors"))):
        perf, eff = procs[1], procs[2]
    translated = sysctl("sysctl.proc_translated") == "1"
    machine = os.uname().machine if hasattr(os, "uname") else None
    return HostFacts(
        platform=fact("macos"),
        model_name=fact(clean_text(profile.get("machine_name"))),
        model_id=fact(clean_text(sysctl("hw.model") or profile.get("machine_model"), 40)),
        chip=fact(clean_text(sysctl("machdep.cpu.brand_string") or profile.get("chip_type"))),
        performance_cores=fact(perf),
        efficiency_cores=fact(eff if perf else None),
        physical_cores=fact(parse_int(sysctl("hw.physicalcpu"), _CORES)),
        logical_cpus=fact(parse_int(sysctl("hw.logicalcpu"), _CORES)),
        memory_bytes=fact(parse_int(sysctl("hw.memsize"), _MEMORY)),
        os_version=fact(parse_version(run([SW_VERS, "-productVersion"]))),
        arch=fact("arm64" if translated else parse_arch(machine)),
    )


def merge(primary: HostFacts, fallback: HostFacts) -> HostFacts:
    """Each fact from `primary` when it is known, else from `fallback`."""
    return HostFacts(**{name: f if f.known else getattr(fallback, name) for name, f in vars(primary).items()})


def detect(root: Path = Path("/"), environ: Mapping[str, str] | None = None, platform: str = sys.platform,
           run: Callable[[list[str]], str | None] = _run,
           affinity: Callable[[], tuple[int, str]] = _affinity) -> Detection:
    environ = os.environ if environ is None else environ
    launcher = read_launcher(environ)
    if platform == "darwin":
        host = merge(read_macos(run), launcher)
        container = read_container(root, environ, affinity, macos_memory=host.memory_bytes.value)
    else:
        host = launcher
        container = read_container(root, environ, affinity)
    notes = []
    if not any(f.known for f in vars(host).values()):
        notes.append("host_unknown")
    return Detection(host=host, container=container, notes=notes)


@lru_cache
def detection() -> Detection:
    """Detected once per process: the CPUs and memory of a container change only when it restarts."""
    return detect()
