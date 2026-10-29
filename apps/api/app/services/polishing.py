"""Polishing requests: the draft assembly, the reads by role, the strategy their technology calls for, and the tools
each strategy needs.

Strategies follow the reads, not one recipe for every technology: long reads → Racon (generic consensus; no
technology-specific error model), short reads → Pilon, both → Racon, then Pilon on Racon's result. Every check uses
recorded evidence only and never changes what the user chose; suggestions are labelled as such.
"""
from __future__ import annotations

from typing import Any

from arva_tools import ToolStatus
from arva_tools.pilon import java_executable, java_version
from arva_tools.registry import detect
from sqlalchemy.orm import Session

from app.models import Assembly, Sample, SequencingTechnology
from app.services import short_hybrid
from app.services.flye import CONFIDENT, InputError, read_type_suggestion
from app.services.performance import Resources, effective_resources
from app.storage import get_storage

STRATEGIES = ("racon", "pilon", "hybrid")
STRATEGY_TOOLS = {"racon": ("racon", "minimap2", "samtools"), "pilon": ("pilon", "bwa", "samtools"),
                  "hybrid": ("racon", "minimap2", "pilon", "bwa", "samtools")}
OPTIONAL_TOOLS = ("dnadiff",)
# Each minimap2 preset and the platform of its reads.
PRESET_PLATFORM = {"map-ont": "nanopore", "map-pb": "pacbio", "map-hifi": "pacbio"}
# Flye's read types (ARVA's suggestion for the same reads) and the matching minimap2 preset.
FLYE_TO_PRESET = {"nano-raw": "map-ont", "nano-corr": "map-ont", "nano-hq": "map-ont", "pacbio-raw": "map-pb",
                  "pacbio-corr": "map-pb", "pacbio-hifi": "map-hifi"}
# Debian's pilon launcher runs Java with a 16 GB heap; ARVA uses the same default unless the computer has less.
DEBIAN_PILON_HEAP_GB = 16


def draft_for(db: Session, sample: Sample, assembly_id: str) -> Assembly:
    a = db.get(Assembly, assembly_id)
    if a is None or a.sample_id != sample.id:
        raise InputError(f"Assembly {assembly_id} does not belong to this sample")
    if not get_storage().resolve(a.contigs_path).is_file():
        raise InputError(f"The contigs file of assembly {assembly_id} is missing on disk")
    return a


def strategy_of(inputs: short_hybrid.Inputs) -> str | None:
    """The strategy the chosen reads imply."""
    if inputs.long and inputs.short:
        return "hybrid"
    return "racon" if inputs.long else "pilon" if inputs.short else None


def suggested_strategy(sample: Sample) -> str | None:
    """The strategy the sample's sequencing technology calls for (its metadata), or None when it is unknown."""
    return {SequencingTechnology.nanopore: "racon", SequencingTechnology.pacbio: "racon",
            SequencingTechnology.illumina: "pilon", SequencingTechnology.hybrid: "hybrid"}.get(sample.sequencing_technology)


def preset_suggestion(sample: Sample, ev: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristic minimap2 preset for the long reads: Flye's read-type suggestion for the same evidence, mapped to
    the preset of that platform and accuracy."""
    long = [e for e in ev if e.get("role") == "long"]
    if not long:
        return {"heuristic": True, "value": None, "basis": "no long reads chosen", "flye_read_type": None}
    s = read_type_suggestion(sample, long)
    return {"heuristic": True, "value": FLYE_TO_PRESET.get(s["value"]) if s["value"] else None, "basis": s["basis"],
            "flye_read_type": s["value"], "platform": s["platform"]}


def check_request(sample: Sample, inputs: short_hybrid.Inputs, ev: list[dict[str, Any]], strategy: str,
                  preset: str | None, confirmed: bool, preset_required: bool = True) -> None:
    """Raise InputError when the reads cannot play their roles for the strategy, or contradict the preset or the
    sample's sequencing technology."""
    if strategy not in STRATEGIES:
        raise InputError(f"strategy must be one of {', '.join(STRATEGIES)}")
    implied = strategy_of(inputs)
    if implied != strategy:
        needs = {"racon": "long reads and no short reads", "pilon": "short reads and no long reads",
                 "hybrid": "both long reads (for Racon) and short reads (for Pilon)"}
        raise InputError(f"The {strategy} strategy needs {needs[strategy]}")
    tool = {"racon": "Racon", "pilon": "Pilon", "hybrid": "Racon and Pilon"}[strategy]
    short_hybrid.check_inputs(sample, inputs, ev, tool, confirmed)
    if inputs.long is None or (preset is None and not preset_required):
        return
    if preset not in PRESET_PLATFORM:
        raise InputError(f"Choose the long reads' type (minimap2 preset {', '.join(PRESET_PLATFORM)})")
    platform = PRESET_PLATFORM[preset]
    technology = sample.sequencing_technology.value
    if technology in ("nanopore", "pacbio") and technology != platform:
        raise InputError(f"The read type {preset} is for {platform} reads, but this sample's sequencing technology is "
                         f"'{technology}'")
    e = next(x for x in ev if x["role"] == "long")
    if e["header_platform"] in ("nanopore", "pacbio") and e["header_platform"] != platform \
            and e["header_confidence"] in CONFIDENT:
        raise InputError(f"{e['name']}: its read headers identify {e['header_platform']} reads "
                         f"({e['header_confidence']} confidence); the read type {preset} is for {platform} reads")


def _tool(tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=True)
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "path": d.path}


def tools_status() -> dict[str, Any]:
    """Every tool a polishing strategy can use, detected afresh, with Java for Pilon."""
    tools = {t: _tool(t) for t in ("racon", "minimap2", "pilon", "bwa", "samtools", "dnadiff")}
    java = java_executable()
    tools["java"] = {"status": ToolStatus.available.value if java else ToolStatus.not_installed.value,
                     "version": java_version(java) if java else None, "version_validated": False,
                     "message": "" if java else "Java was not found", "reason": None, "path": java}
    return tools


def strategies_available(tools: dict[str, Any]) -> list[str]:
    ok = {t for t, d in tools.items() if d["status"] == ToolStatus.available.value}
    return [s for s, needed in STRATEGY_TOOLS.items() if set(needed) <= ok and (s == "racon" or "java" in ok)]


def resources(res: Resources) -> dict[str, int]:
    return {"max_threads": res.max_threads, "default_threads": res.threads, "max_memory_gb": res.max_memory_gb,
            "default_heap_gb": min(DEBIAN_PILON_HEAP_GB, res.memory_gb)}


def draft_summary(a: Assembly) -> dict[str, Any]:
    s = a.stats
    return {"assembly_id": a.id, "kind": a.kind, "assembler": a.assembler, "assembler_version": a.assembler_version,
            "mode": a.mode, "read_type": a.read_type, "parent_assembly_id": a.parent_assembly_id,
            "contig_count": s["contig_count"], "total_length": s["total_length"], "n50": s["n50"],
            "circular_contigs": s["circularity"]["circular_contigs"], "created_at": a.created_at}


def plan(db: Session, sample: Sample, draft: Assembly, inputs: short_hybrid.Inputs, preset: str | None) -> dict[str, Any]:
    """What ARVA knows before polishing (nothing is run); a problem with the inputs is returned, not raised."""
    ev = short_hybrid.file_evidence(db, inputs)
    strategy = strategy_of(inputs)
    try:
        if strategy is None:
            raise InputError("Choose the reads to polish with: long reads (Racon), short reads (Pilon), or both")
        check_request(sample, inputs, ev, strategy, preset, confirmed=True, preset_required=False)
        problem = None
    except InputError as exc:
        problem = str(exc)
    tools = tools_status()
    return {
        "draft": draft_summary(draft),
        "tools": tools,
        "strategies_available": strategies_available(tools),
        "files": ev,
        "strategy": strategy,
        "suggested_strategy": suggested_strategy(sample),
        "preset_suggestion": preset_suggestion(sample, ev),
        "problem": problem,
        "sample_technology": sample.sequencing_technology,
        "confirmation_required": short_hybrid.needs_confirmation(sample),
        **resources(effective_resources(db)),
    }
