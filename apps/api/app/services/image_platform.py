"""Which image architecture ARVA runs on and why (Settings → Performance, Diagnostics, the launcher's summary).

scripts/start.sh chooses linux/amd64 or linux/arm64 and passes the choice, its reason, Docker Desktop's Rosetta
setting as it read it and where the images came from as ARVA_HOST_IMAGE_PLATFORM, ARVA_HOST_IMAGE_REASON,
ARVA_HOST_DOCKER_ROSETTA and ARVA_HOST_IMAGE_SOURCE. The architecture the process actually runs on is this
process's own machine type: an amd64 image on an arm64 computer is translated (by Rosetta when Docker Desktop's
setting is on, by QEMU otherwise), which ARVA can only infer from the launcher's facts.
"""
from __future__ import annotations

import platform
from collections.abc import Mapping
from typing import Any

from app.services.host import HostFacts

REASONS = ("chosen", "native", "rosetta_on", "rosetta_unknown", "rosetta_off", "unknown")
PLATFORMS = ("linux/amd64", "linux/arm64")
# Debian bookworm builds these packages for amd64 only (docker/api.Dockerfile): an arm64 image has none of them.
AMD64_ONLY_DEBIAN = ("prokka", "spades", "unicycler")


def machine_platform(machine: str | None = None) -> str | None:
    m = (machine if machine is not None else platform.machine()).lower()
    return {"x86_64": "linux/amd64", "amd64": "linux/amd64", "aarch64": "linux/arm64", "arm64": "linux/arm64"}.get(m)


def _one_of(value: str | None, allowed: tuple[str, ...]) -> str | None:
    value = (value or "").strip()
    return value if value in allowed else None


def unavailable_tools(running: str | None) -> list[str]:
    """Tools this image lacks because they have no build for its architecture (not tools merely not installed)."""
    from arva_tools.base import ToolStatus
    from arva_tools.registry import ADAPTERS, detect

    out = []
    for tool_id, adapter in ADAPTERS.items():
        candidate = bool(adapter.info.conda_platforms) or (running == "linux/arm64" and tool_id in AMD64_ONLY_DEBIAN)
        if not candidate:
            continue
        d = detect(tool_id)
        if d.reason == "no_conda_platform" or (tool_id in AMD64_ONLY_DEBIAN and d.status is ToolStatus.not_installed):
            out.append(tool_id)
    return out


def describe(host: HostFacts, environ: Mapping[str, str], machine: str | None = None,
             with_tools: bool = True) -> dict[str, Any]:
    running = machine_platform(machine)
    chosen = _one_of(environ.get("ARVA_HOST_IMAGE_PLATFORM"), PLATFORMS)
    host_arch = host.arch.value
    emulated = None
    if host_arch in ("arm64", "x86_64") and running is not None:
        emulated = (host_arch == "arm64") != (running == "linux/arm64")
    return {
        "running": running,
        "chosen": chosen,
        "reason": _one_of(environ.get("ARVA_HOST_IMAGE_REASON"), REASONS),
        "rosetta": _one_of(environ.get("ARVA_HOST_DOCKER_ROSETTA"), ("on", "off", "unknown")),
        "source": _one_of(environ.get("ARVA_HOST_IMAGE_SOURCE"), ("published", "local")),
        "host_arch": host_arch,
        "emulated": emulated,
        "mismatch": chosen is not None and running is not None and chosen != running,
        "unavailable_tools": unavailable_tools(running) if with_tools else [],
    }


_TEXT = {
    "en": {"title": "Image architecture", "running": "running", "translated": "translated: an amd64 image on an "
           "arm64 computer, through {how}", "rosetta": "Rosetta", "qemu": "QEMU (Rosetta is off)",
           "unknown_how": "Rosetta or QEMU", "missing": "Not available on this architecture",
           "mismatch": "scripts/start.sh chose {chosen}, but the containers run {running}"},
    "es": {"title": "Arquitectura de la imagen", "running": "en uso", "translated": "traducida: una imagen amd64 en un "
           "equipo arm64, mediante {how}", "rosetta": "Rosetta", "qemu": "QEMU (Rosetta está desactivado)",
           "unknown_how": "Rosetta o QEMU", "missing": "No disponibles en esta arquitectura",
           "mismatch": "scripts/start.sh eligió {chosen}, pero los contenedores usan {running}"},
}


def text_lines(info: dict[str, Any], lang: str = "en") -> list[str]:
    t = _TEXT[lang]
    line = f"  {t['title']}: {info['running'] or '?'} ({t['running']})"
    if info["emulated"]:
        how = {"on": t["rosetta"], "off": t["qemu"]}.get(info["rosetta"] or "", t["unknown_how"])
        line += "; " + t["translated"].format(how=how)
    lines = [line]
    if info["mismatch"]:
        lines.append("  " + t["mismatch"].format(chosen=info["chosen"], running=info["running"]))
    if info["unavailable_tools"]:
        lines.append(f"  {t['missing']}: {', '.join(info['unavailable_tools'])}")
    return lines
