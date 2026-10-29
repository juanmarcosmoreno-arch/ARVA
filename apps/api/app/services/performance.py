"""Performance profiles: the CPU threads, memory limit and CPU priority ARVA gives each tool run.

The profiles, the automatic choice and the Docker Desktop recommendation are ARVA's own heuristics, not
measurements and not tool documentation:

* Automatic choice: MacBook Air and the 12-inch MacBook (fanless on Apple silicon) -> light; MacBook Pro, Mac mini
  and iMac -> balanced; Mac Studio and Mac Pro -> maximum; any other or unknown computer by its usable cores and
  memory.
* Threads start from the performance cores (Apple silicon) or the physical cores of the host, else the CPUs the
  container can use: light half of them, balanced three quarters, maximum all performance cores when efficiency
  cores are left for macOS, else all but one. Never more than the CPUs ARVA can actually use.
* Memory per job (the limit given to tools that take one: SPAdes -m, Unicycler's SPAdes, Pilon's Java heap,
  samtools sort per thread): a share of the memory ARVA can use (50 %, 70 %, 85 %).
* CPU priority: tools start through `nice` (light 15, balanced 10, maximum 5).

ARVA_TOOL_THREADS and ARVA_TOOL_MEMORY_GB, when set, cap every value.
"""
from __future__ import annotations

import argparse
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.host import GIB, ContainerFacts, Detection, HostFacts, detection

PROFILES = ("light", "balanced", "maximum")
CHOICES = ("auto", *PROFILES, "custom")
SETTING_KEY = "performance"
MAX_CUSTOM_THREADS = 256
MAX_CUSTOM_MEMORY_GB = 4096
# Used when the memory ARVA can use cannot be read.
FALLBACK_MEMORY_GB = 8

MEMORY_SHARE = {"light": 0.5, "balanced": 0.7, "maximum": 0.85}
NICE = {"light": 15, "balanced": 10, "maximum": 5, "custom": 10}
# Docker Desktop's virtual machine: the share of the Mac's memory recommended for each profile, and the most that
# still leaves macOS a quarter of it.
DOCKER_MEMORY_SHARE = {"light": 0.5, "balanced": 0.6, "maximum": 0.75}
DOCKER_MEMORY_MOST = 0.75
# The VM's kernel reports a little less memory than Docker Desktop's setting; within this share it counts as set.
DOCKER_MEMORY_TOLERANCE = 0.9

MAC_PROFILE = {"macbook_air": "light", "macbook": "light", "macbook_pro": "balanced", "mac_mini": "balanced",
               "imac": "balanced", "mac_studio": "maximum", "mac_pro": "maximum"}
_NAMES = (("macbook air", "macbook_air"), ("macbook pro", "macbook_pro"), ("macbook", "macbook"),
          ("mac mini", "mac_mini"), ("imac", "imac"), ("mac studio", "mac_studio"), ("mac pro", "mac_pro"))
# Model identifiers up to 2021 name the family ("MacBookAir10,1"); later ones do not ("Mac14,2" is a MacBook Air;
# Apple's "Identify your MacBook Air model"), so system_profiler's model name comes first.
_IDENTIFIERS = ((r"MacBookAir\d", "macbook_air"), (r"MacBookPro\d", "macbook_pro"), (r"Macmini\d", "mac_mini"),
                (r"iMac(?:Pro)?\d", "imac"), (r"MacPro\d", "mac_pro"), (r"MacBook\d", "macbook"))


def mac_class(host: HostFacts) -> str | None:
    name = (host.model_name.value or "").lower()
    for prefix, cls in _NAMES:
        if name.startswith(prefix):
            return cls
    ident = host.model_id.value or ""
    return next((cls for pattern, cls in _IDENTIFIERS if re.match(pattern, ident)), None)


def core_basis(host: HostFacts, container: ContainerFacts) -> tuple[int, str]:
    if host.performance_cores.known:
        return host.performance_cores.value, "performance_cores"
    if host.physical_cores.known:
        return host.physical_cores.value, "physical_cores"
    return container.usable_cpus, "usable_cpus"


def automatic_profile(host: HostFacts, container: ContainerFacts) -> tuple[str, str]:
    """(profile, reason): the Mac's family when it is known, else the cores and memory ARVA can use."""
    cls = mac_class(host)
    if cls is not None:
        return MAC_PROFILE[cls], cls
    cores = min(core_basis(host, container)[0], container.usable_cpus)
    memory = container.memory_gb or FALLBACK_MEMORY_GB
    if cores <= 4 or memory < 8:
        return "light", "few_resources"
    if cores >= 12 and memory >= 32:
        return "maximum", "many_resources"
    return "balanced", "default"


def profile_threads(profile: str, cores: int, efficiency_cores: int = 0) -> int:
    if profile == "light":
        n = cores // 2
    elif profile == "balanced":
        n = cores - max(1, cores // 4)
    else:
        n = cores if efficiency_cores else cores - 1
    return max(1, n)


def profile_memory_gb(profile: str, usable_gb: float) -> int:
    return max(1, math.floor(usable_gb * MEMORY_SHARE[profile]))


def host_summary(host: HostFacts) -> str:
    parts = []
    if host.model_name.known or host.model_id.known:
        name = host.model_name.value or host.model_id.value
        parts.append(f"{name} ({host.model_id.value})" if host.model_name.known and host.model_id.known else name)
    if host.chip.known:
        parts.append(host.chip.value)
    if host.performance_cores.known:
        parts.append(f"{host.performance_cores.value} performance + {host.efficiency_cores.value or 0} efficiency cores")
    elif host.physical_cores.known:
        parts.append(f"{host.physical_cores.value} cores")
    if host.memory_bytes.known:
        parts.append(f"{host.memory_bytes.value / GIB:.0f} GB")
    if host.os_version.known:
        parts.append(f"macOS {host.os_version.value}" if host.is_mac else host.os_version.value)
    return " · ".join(parts) or "unknown computer"


@dataclass(frozen=True)
class Resources:
    """What ARVA gives one tool run now: `threads` and `memory_gb` are the defaults a run gets, `max_threads` and
    `max_memory_gb` the most a request may ask for (the CPUs and memory ARVA can use, within the caps)."""
    profile: str
    choice: str
    automatic_profile: str
    reason: str
    threads: int
    max_threads: int
    memory_gb: int
    max_memory_gb: int
    nice: int
    usable_cpus: int
    usable_memory_gb: float
    in_container: bool
    host: str
    core_basis: str
    cores: int
    requested_threads: int
    requested_memory_gb: int
    exceeds: list[str] = field(default_factory=list)
    admin_threads: int | None = None
    admin_memory_gb: int | None = None

    def cap_threads(self, threads: int | None) -> int:
        return max(1, min(threads or self.threads, self.max_threads))

    def record(self, threads: int | None, memory_gb: int | None = None, memory_option: str | None = None) -> dict:
        """What a job records about the resources it was given (analysis_jobs.resources)."""
        return {
            "profile": self.profile, "choice": self.choice, "threads": threads,
            "memory_gb": self.memory_gb, "memory_limit_gb": memory_gb, "memory_option": memory_option,
            "nice": self.nice, "usable_cpus": self.usable_cpus, "usable_memory_gb": round(self.usable_memory_gb, 1),
            "in_container": self.in_container, "host": self.host,
        }


def validate_choice(value: Any) -> dict[str, Any]:
    """A stored or requested choice, checked: {"profile": one of CHOICES} plus threads and memory_gb for custom."""
    if not isinstance(value, dict) or value.get("profile") not in CHOICES:
        raise ValueError(f"profile must be one of {', '.join(CHOICES)}")
    profile = value["profile"]
    if profile != "custom":
        return {"profile": profile}
    out = {"profile": profile}
    for name, top in (("threads", MAX_CUSTOM_THREADS), ("memory_gb", MAX_CUSTOM_MEMORY_GB)):
        n = value.get(name)
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= top:
            raise ValueError(f"a custom profile needs {name} between 1 and {top}")
        out[name] = n
    return out


def compute(det: Detection, choice: dict[str, Any], admin_threads: int | None = None,
            admin_memory_gb: int | None = None) -> Resources:
    host, c = det.host, det.container
    auto, reason = automatic_profile(host, c)
    cores, basis = core_basis(host, c)
    usable_gb = c.memory_gb or FALLBACK_MEMORY_GB
    selected = choice.get("profile", "auto")
    profile = auto if selected == "auto" else selected
    if profile == "custom":
        threads, memory = choice["threads"], choice["memory_gb"]
    else:
        threads = profile_threads(profile, cores, host.efficiency_cores.value or 0)
        memory = profile_memory_gb(profile, usable_gb)
    usable_memory = max(1, math.floor(usable_gb))
    exceeds = [name for name, want, have in (("threads", threads, c.usable_cpus), ("memory_gb", memory, usable_memory))
               if want > have]
    max_threads = min(c.usable_cpus, admin_threads or c.usable_cpus)
    max_memory = min(usable_memory, admin_memory_gb or usable_memory)
    return Resources(
        profile=profile, choice=selected, automatic_profile=auto, reason=reason,
        threads=max(1, min(threads, max_threads)), max_threads=max_threads,
        memory_gb=max(1, min(memory, max_memory)), max_memory_gb=max_memory, nice=NICE[profile],
        usable_cpus=c.usable_cpus, usable_memory_gb=usable_gb, in_container=c.in_container, host=host_summary(host),
        core_basis=basis, cores=cores, requested_threads=threads, requested_memory_gb=memory, exceeds=exceeds,
        admin_threads=admin_threads, admin_memory_gb=admin_memory_gb,
    )


def docker_advice(det: Detection, res: Resources) -> dict[str, Any]:
    """What Docker Desktop should give its virtual machine for the profile in use on this Mac: "increase" when it
    gives fewer CPUs or less memory, "decrease" when its memory leaves macOS less than a quarter. Unknown without
    the launcher's facts. More CPUs than recommended are fine: ARVA's thread count is the limit for its tools."""
    host, c = det.host, det.container
    if not c.in_container:
        return {"status": "not_container"}
    if not host.is_mac:
        return {"status": "host_unknown"}
    cores = host.performance_cores.value or host.physical_cores.value
    threads = res.requested_threads if res.profile == "custom" else (
        profile_threads(res.profile, cores, host.efficiency_cores.value or 0) if cores else None)
    cpus = None
    if threads is not None:
        recommended = threads + 1
        if host.logical_cpus.known:
            recommended = min(recommended, host.logical_cpus.value)
        current = host.docker_cpus.value or c.usable_cpus
        cpus = {"current": current, "recommended": recommended,
                "status": "increase" if current < recommended else "ok"}
    memory = None
    if host.memory_bytes.known:
        mac_gb = host.memory_bytes.value / GIB
        share = DOCKER_MEMORY_SHARE["balanced" if res.profile == "custom" else res.profile]
        recommended_gb = max(1, math.floor(mac_gb * share))
        current = host.docker_memory_bytes.value or c.memory_bytes
        status = "unknown"
        if current is not None:
            current_gb = current / GIB
            status = ("increase" if current_gb < recommended_gb * DOCKER_MEMORY_TOLERANCE else
                      "decrease" if current_gb > mac_gb * DOCKER_MEMORY_MOST else "ok")
        memory = {"current_bytes": current, "recommended_gb": recommended_gb,
                  "most_gb": math.floor(mac_gb * DOCKER_MEMORY_MOST), "status": status}
    statuses = {x["status"] for x in (cpus, memory) if x}
    overall = ("adjust" if statuses & {"increase", "decrease"} else "ok" if statuses == {"ok"} else "partial")
    return {"status": overall, "cpus": cpus, "memory": memory}


def load_choice(db: Session) -> dict[str, Any]:
    from app.models import AppSetting

    row = db.get(AppSetting, SETTING_KEY)
    try:
        return validate_choice(row.value) if row is not None else {"profile": "auto"}
    except ValueError:
        return {"profile": "auto"}


def save_choice(db: Session, choice: dict[str, Any]) -> None:
    from app.models import AppSetting

    value = validate_choice(choice)
    row = db.get(AppSetting, SETTING_KEY, with_for_update=True)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    db.commit()


def effective_resources(db: Session) -> Resources:
    """The one place every job, preview and dialog default reads its threads and memory from."""
    s = get_settings()
    return compute(detection(), load_choice(db), s.tool_threads, s.tool_memory_gb)


def overview(db: Session) -> dict[str, Any]:
    """GET /system/performance: every detected fact with its source, the automatic profile and why, the choice,
    what each profile would give here, the effective values and the Docker Desktop recommendation."""
    from app.models import AppSetting

    det = detection()
    choice = load_choice(db)
    s = get_settings()
    res = compute(det, choice, s.tool_threads, s.tool_memory_gb)
    row = db.get(AppSetting, SETTING_KEY)
    profiles = {p: compute(det, {"profile": p}, s.tool_threads, s.tool_memory_gb) for p in PROFILES}
    return {
        "host": det.host.as_dict(),
        "mac_class": mac_class(det.host),
        "container": asdict(det.container),
        "automatic": {"profile": res.automatic_profile, "reason": res.reason, "core_basis": res.core_basis,
                      "cores": res.cores},
        "choice": {**choice, "updated_at": row.updated_at if row is not None else None},
        "effective": {k: getattr(res, k) for k in (
            "profile", "choice", "threads", "max_threads", "memory_gb", "max_memory_gb", "nice", "usable_cpus",
            "usable_memory_gb", "requested_threads", "requested_memory_gb", "exceeds", "admin_threads",
            "admin_memory_gb", "host")},
        "profiles": [{"profile": p, "threads": r.threads, "memory_gb": r.memory_gb, "nice": r.nice}
                     for p, r in profiles.items()],
        "docker": docker_advice(det, res),
    }


def memory_advice(record: dict[str, Any] | None) -> str:
    """The memory a job could use and what to change, for a tool killed by SIGKILL (exit status -9 or 137)."""
    r = record or {}
    text = ""
    if r:
        limit = f", a memory limit of {r['memory_limit_gb']} GB" if r.get("memory_limit_gb") else ""
        text = (f"ARVA could use {r.get('usable_memory_gb', '?')} GB of memory here"
                + (" (the container's limit)" if r.get("in_container") else "")
                + f"; this job ran with {r.get('threads') or '?'} thread(s){limit} ({r.get('profile', '?')} profile). ")
    text += "Choose a lighter performance profile or fewer threads in Settings → Performance"
    if r.get("in_container", True):
        text += ", or give Docker Desktop more memory (Docker Desktop → Settings → Resources)"
    return text + "."


def out_of_memory_reason(tool: str, record: dict[str, Any] | None) -> str:
    return (f"{tool} was stopped by the operating system with SIGKILL, which usually means the computer (or the "
            f"container) ran out of memory. {memory_advice(record)}")


# --- Text summary for the launcher (python -m app.services.performance) ---------------------------------------

_TEXT = {
    "en": {
        "title": "ARVA performance profile", "detected": "Computer", "unknown": "unknown (start ARVA with "
        "scripts/start.sh on a Mac to detect it)", "usable": "ARVA can use", "cpus": "CPUs", "auto": "Automatic profile",
        "inuse": "In use", "auto_word": "automatic", "per_tool": "threads per tool, memory limit up to",
        "priority": "CPU priority nice", "docker_ok": "Docker Desktop: its CPUs and memory suit this profile.",
        "docker_adjust": "Recommendation for Docker Desktop (Settings → Resources → Advanced), then run "
        "scripts/start.sh again:", "cpu_limit": "CPU limit", "memory_limit": "Memory limit",
        "increase": "now {current}; set it to {recommended}",
        "decrease": "now {current}; at most {most} leaves macOS a quarter of the memory, {recommended} suits this "
        "profile", "change": "Change it in ARVA: Settings → Performance.", "saved_unreadable":
        "(the saved choice could not be read; showing the automatic profile)",
        "light": "Light", "balanced": "Balanced", "maximum": "Maximum", "custom": "Custom",
    },
    "es": {
        "title": "Perfil de rendimiento de ARVA", "detected": "Equipo", "unknown": "desconocido (inicia ARVA con "
        "scripts/start.sh en un Mac para detectarlo)", "usable": "ARVA puede usar", "cpus": "CPU",
        "auto": "Perfil automático", "inuse": "En uso", "auto_word": "automático",
        "per_tool": "hilos por herramienta, límite de memoria de hasta", "priority": "prioridad de CPU nice",
        "docker_ok": "Docker Desktop: sus CPU y su memoria son adecuadas para este perfil.",
        "docker_adjust": "Recomendación para Docker Desktop (Settings → Resources → Advanced); después vuelve a "
        "ejecutar scripts/start.sh:", "cpu_limit": "CPU limit", "memory_limit": "Memory limit",
        "increase": "ahora {current}; ponlo en {recommended}",
        "decrease": "ahora {current}; como mucho {most} deja a macOS una cuarta parte de la memoria, {recommended} "
        "es adecuado para este perfil", "change": "Cámbialo en ARVA: Ajustes → Rendimiento.",
        "saved_unreadable": "(no se pudo leer la elección guardada; se muestra el perfil automático)",
        "light": "Ligero", "balanced": "Equilibrado", "maximum": "Máximo", "custom": "Personalizado",
    },
}
_REASONS = {
    "en": {"macbook_air": "MacBook Air: fanless on Apple silicon", "macbook": "MacBook: fanless",
           "macbook_pro": "MacBook Pro", "mac_mini": "Mac mini", "imac": "iMac", "mac_studio": "Mac Studio",
           "mac_pro": "Mac Pro", "few_resources": "4 cores or fewer, or less than 8 GB of memory",
           "many_resources": "12 cores or more and 32 GB of memory or more", "default": "unknown computer"},
    "es": {"macbook_air": "MacBook Air: sin ventilador en Apple silicon", "macbook": "MacBook: sin ventilador",
           "macbook_pro": "MacBook Pro", "mac_mini": "Mac mini", "imac": "iMac", "mac_studio": "Mac Studio",
           "mac_pro": "Mac Pro", "few_resources": "4 núcleos o menos, o menos de 8 GB de memoria",
           "many_resources": "12 núcleos o más y 32 GB de memoria o más", "default": "equipo desconocido"},
}


def text_report(det: Detection, res: Resources, lang: str = "en", saved_unreadable: bool = False) -> str:
    t, reasons = _TEXT[lang], _REASONS[lang]
    c = det.container

    def gb(value: float) -> str:
        text = f"{value:.1f} GB"
        return text.replace(".", ",") if lang == "es" else text

    known = any(f.known for f in vars(det.host).values())
    lines = [t["title"],
             f"  {t['detected']}: {res.host if known else t['unknown']}",
             f"  {t['usable']}: {c.usable_cpus} {t['cpus']}, {gb(res.usable_memory_gb)}",
             f"  {t['auto']}: {t[res.automatic_profile]} ({reasons[res.reason]})",
             f"  {t['inuse']}: {t[res.profile]}" + (f" ({t['auto_word']})" if res.choice == "auto" else "")
             + f" → {res.threads} {t['per_tool']} {res.memory_gb} GB, {t['priority']} {res.nice}"
             + (f" {t['saved_unreadable']}" if saved_unreadable else "")]
    advice = docker_advice(det, res)
    if advice["status"] == "ok":
        lines.append(f"  {t['docker_ok']}")
    elif advice["status"] in ("adjust", "partial"):
        rows = []
        if (cpu := advice.get("cpus")) and cpu["status"] == "increase":
            rows.append(f"    {t['cpu_limit']}: " + t["increase"].format(current=cpu["current"],
                                                                         recommended=cpu["recommended"]))
        if (mem := advice.get("memory")) and mem["status"] in ("increase", "decrease"):
            current = gb(mem["current_bytes"] / GIB)
            rows.append(f"    {t['memory_limit']}: " + t[mem["status"]].format(
                current=current, recommended=f"{mem['recommended_gb']} GB", most=f"{mem['most_gb']} GB"))
        if rows:
            lines += [f"  {t['docker_adjust']}", *rows]
    lines.append(f"  {t['change']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the performance profile ARVA uses on this computer.")
    parser.add_argument("--lang", choices=sorted(_TEXT), default="en")
    args = parser.parse_args(argv)
    from app.db.session import SessionLocal

    det, s, unreadable = detection(), get_settings(), False
    try:
        with SessionLocal() as db:
            choice = load_choice(db)
    except SQLAlchemyError:
        choice, unreadable = {"profile": "auto"}, True
    print(text_report(det, compute(det, choice, s.tool_threads, s.tool_memory_gb), args.lang, unreadable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
