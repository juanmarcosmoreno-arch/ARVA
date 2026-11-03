"""Polishing requests: the draft assembly, the reads by role, the strategy their technology calls for, and the tools
each strategy needs.

Strategies follow the reads, not one recipe for every technology: long reads → Racon (generic consensus; no
technology-specific error model) or, for Oxford Nanopore reads, Medaka (a neural network trained for the reads'
basecaller model), short reads → Pilon, both → Racon, then Pilon on Racon's result. Every check uses recorded evidence
only and never changes what the user chose; suggestions are labelled as such.

Medaka's model is never guessed: it is the one the user picks from the models Medaka's package ships, or, when none
is given, the one medaka's own mapping (medaka/options.py basecaller_models) gives for the basecall model ARVA read
from the reads' headers, and only when the package ships it.
"""
from __future__ import annotations

import subprocess
from typing import Any

from arva_tools import ToolStatus
from arva_tools.medaka import (
    DEFAULT_BATCH_SIZE,
    model_for_basecaller,
    offered_models,
    read_catalogue,
)
from arva_tools.pilon import java_executable, java_version
from arva_tools.registry import detect
from sqlalchemy.orm import Session

from app.models import Assembly, AssemblyMode, Sample, SequencingTechnology
from app.services import short_hybrid
from app.services.flye import CONFIDENT, InputError, read_type_suggestion
from app.services.performance import Resources, effective_resources
from app.storage import get_storage

STRATEGIES = ("racon", "medaka", "pilon", "hybrid")
# Medaka runs its own minimap2 (mini_align) inside its environment; ARVA's minimap2 and samtools align the reads to
# the draft and to the result for the indirect indicators, as for Racon.
STRATEGY_TOOLS = {"racon": ("racon", "minimap2", "samtools"), "medaka": ("medaka", "minimap2", "samtools"),
                  "pilon": ("pilon", "bwa", "samtools"), "hybrid": ("racon", "minimap2", "pilon", "bwa", "samtools")}
LONG_STRATEGIES = ("racon", "medaka")
TOOL_NAMES = {"racon": "Racon", "medaka": "Medaka", "pilon": "Pilon", "hybrid": "Racon and Pilon"}
# Medaka's models are for Oxford Nanopore reads; ARVA aligns them with minimap2's Nanopore preset.
MEDAKA_PRESET = "map-ont"
OPTIONAL_TOOLS = ("dnadiff",)
# Each minimap2 preset and the platform of its reads.
PRESET_PLATFORM = {"map-ont": "nanopore", "map-pb": "pacbio", "map-hifi": "pacbio"}
# Flye's read types (ARVA's suggestion for the same reads) and the matching minimap2 preset.
FLYE_TO_PRESET = {"nano-raw": "map-ont", "nano-corr": "map-ont", "nano-hq": "map-ont", "pacbio-raw": "map-pb",
                  "pacbio-corr": "map-pb", "pacbio-hifi": "map-hifi"}
# Debian's pilon launcher runs Java with a 16 GB heap; ARVA uses the same default unless the computer has less.
DEBIAN_PILON_HEAP_GB = 16
# Pilon's documentation (github.com/broadinstitute/pilon/wiki/Requirements-&-Usage): "Generally, bacterial genomes
# with ~200x of Illumina coverage will require at least 8GB, though 16GB is recommended", and "as a rule of thumb,
# try to allocate 1GB per megabase of input genome to be processed".
PILON_DOCUMENTED_MIN_GB = 8
# Memory kept back from the default heap: Java uses memory beyond -Xmx (metaspace, garbage-collector structures,
# thread stacks), and the database, Redis, the API and the worker share the same Docker VM, whose memory max_memory_gb
# counts in full (no container memory limit).
PILON_HEAP_HEADROOM_GB = 1


def default_heap_gb(memory_gb: int, max_memory_gb: int) -> int:
    """Pilon's Java heap when none is asked for: the profile's memory per job, raised towards the 8 GB Pilon documents
    for bacterial genomes when it is less (a light profile on a small Docker Desktop VM gives tools 1 GB, far below
    what Pilon documents, and Pilon would fail with an OutOfMemoryError), but never above the memory ARVA may give a
    tool less PILON_HEAP_HEADROOM_GB (so that Java's own overhead and the other containers fit) nor Debian's 16 GB.
    When even that is below 8 GB the plan says so."""
    cap = max(1, max_memory_gb - PILON_HEAP_HEADROOM_GB)
    return max(1, min(DEBIAN_PILON_HEAP_GB, cap, max(memory_gb, PILON_DOCUMENTED_MIN_GB)))


def draft_for(db: Session, sample: Sample, assembly_id: str) -> Assembly:
    a = db.get(Assembly, assembly_id)
    if a is None or a.sample_id != sample.id:
        raise InputError(f"Assembly {assembly_id} does not belong to this sample")
    if not get_storage().resolve(a.contigs_path).is_file():
        raise InputError(f"The contigs file of assembly {assembly_id} is missing on disk")
    if a.mode is AssemblyMode.imported:
        raise InputError("This is an imported genome, not an assembly of this sample's reads; ARVA polishes only its own "
                         "assemblies")
    return a


def strategy_of(inputs: short_hybrid.Inputs) -> str | None:
    """The strategy the chosen reads imply (with long reads only, Racon; Medaka is the other choice)."""
    if inputs.long and inputs.short:
        return "hybrid"
    return "racon" if inputs.long else "pilon" if inputs.short else None


def strategies_for(inputs: short_hybrid.Inputs) -> tuple[str, ...]:
    """Every strategy the chosen reads allow."""
    implied = strategy_of(inputs)
    return LONG_STRATEGIES if implied == "racon" else (implied,) if implied else ()


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
    if strategy not in strategies_for(inputs):
        needs = {"racon": "long reads and no short reads", "medaka": "Oxford Nanopore long reads and no short reads",
                 "pilon": "short reads and no long reads",
                 "hybrid": "both long reads (for Racon) and short reads (for Pilon)"}
        raise InputError(f"The {strategy} strategy needs {needs[strategy]}")
    short_hybrid.check_inputs(sample, inputs, ev, TOOL_NAMES[strategy], confirmed)
    if strategy == "medaka":
        preset = MEDAKA_PRESET if preset is None else preset
        if preset != MEDAKA_PRESET:
            raise InputError("Medaka polishes Oxford Nanopore assemblies; its reads are aligned with the map-ont preset")
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
    tools = {t: _tool(t) for t in ("racon", "medaka", "minimap2", "pilon", "bwa", "samtools", "dnadiff")}
    java = java_executable()
    tools["java"] = {"status": ToolStatus.available.value if java else ToolStatus.not_installed.value,
                     "version": java_version(java) if java else None, "version_validated": False,
                     "message": "" if java else "Java was not found", "reason": None, "path": java}
    return tools


def strategies_available(tools: dict[str, Any]) -> list[str]:
    ok = {t for t, d in tools.items() if d["status"] == ToolStatus.available.value}
    return [s for s, needed in STRATEGY_TOOLS.items() if set(needed) <= ok and (s in LONG_STRATEGIES or "java" in ok)]


# --- Medaka's model ---------------------------------------------------------------------------------------------

SUGGESTION_TEXT = {
    "no_basecall_model": "ARVA found no basecall model in the reads' headers",
    "several_basecall_models": "the reads' headers name several basecall models ({models})",
    "unknown_basecall_model": "medaka's own mapping has no model for the basecall model {basecall}",
    "fast_unsupported": "{basecall} is a 'fast' basecalling model, which Medaka does not support (medaka: basecall "
                        "again with a 'high accuracy' or 'super accuracy' model first)",
    "mapped_not_bundled": "medaka's model for the basecall model {basecall} is {model}, which its package does not "
                          "ship; ARVA does not let Medaka download models",
    "mapped": "medaka's model for the basecall model {basecall} is {model}",
}


def suggestion_text(s: dict[str, Any]) -> str:
    return SUGGESTION_TEXT[s["status"]].format(models=", ".join(s["basecall_models"]), basecall=s["basecall_model"],
                                               model=s["model"])


def medaka_catalogue() -> tuple[dict[str, Any] | None, str | None]:
    """Medaka's model lists and the models its package ships (arva_tools.medaka.read_catalogue), or why not."""
    d = detect("medaka", refresh=True)
    if d.status is not ToolStatus.available or not d.path:
        return None, d.message or "Medaka is not installed"
    try:
        return read_catalogue(d.path), None
    except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError, ValueError) as exc:
        return None, str(exc)


def _header_models(ev: list[dict[str, Any]]) -> list[str]:
    return sorted({m for e in ev if e.get("role") == "long" for m in e.get("basecall_models") or []})


def medaka_plan(ev: list[dict[str, Any]], catalogue: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    """The models ARVA can run Medaka with and the one medaka's mapping gives for the long reads' basecall model."""
    if catalogue is None:
        return {"available": False, "error": error, "version": None, "models": [], "bundled": [], "default_model": None,
                "suggestion": None, "default_batch_size": DEFAULT_BATCH_SIZE}
    has_long = any(e.get("role") == "long" for e in ev)
    return {"available": True, "error": None, "version": catalogue["version"], "models": offered_models(catalogue),
            "bundled": catalogue["bundled_models"], "default_model": catalogue["default_consensus"],
            "suggestion": model_for_basecaller(catalogue, _header_models(ev)) if has_long else None,
            "default_batch_size": DEFAULT_BATCH_SIZE}


def choose_medaka_model(catalogue: dict[str, Any], ev: list[dict[str, Any]], model: str | None,
                        accept_mismatch: bool) -> dict[str, Any]:
    """The model a Medaka run uses, and why. Without `model`, medaka's own mapping for the basecall model of the
    reads' headers, when the package ships that model; otherwise the user's choice among the shipped models, which
    must be confirmed when it differs from the mapping's. Raises InputError instead of guessing."""
    offered = offered_models(catalogue)
    suggestion = model_for_basecaller(catalogue, _header_models(ev))
    if suggestion["status"] == "fast_unsupported":
        raise InputError(f"Medaka cannot polish with these reads: {suggestion_text(suggestion)}")
    if model is None:
        if suggestion["status"] != "mapped":
            raise InputError(f"Choose the Medaka model: {suggestion_text(suggestion)}. Models ARVA can use: "
                             f"{', '.join(offered) or 'none'}")
        model, source = suggestion["model"], "basecall_model"
    else:
        source = "user"
    if model not in offered:
        raise InputError(f"The Medaka model {model} is not one of the models Medaka's package ships "
                         f"({', '.join(offered) or 'none'}); ARVA does not let Medaka download models")
    mismatch = suggestion["model"] is not None and suggestion["model"] != model
    if mismatch and not accept_mismatch:
        raise InputError(f"The model {model} is not the one for these reads: {suggestion_text(suggestion)}. Confirm "
                         "the choice to use it anyway")
    bundled = next(m for m in catalogue["bundled_models"] if m["name"] == model)
    return {"model": model, "source": source, "suggestion": suggestion, "mismatch_accepted": mismatch,
            "file": bundled["file"], "sha256": bundled["sha256"], "medaka_version": catalogue["version"]}


def resources(res: Resources) -> dict[str, int]:
    return {"max_threads": res.max_threads, "default_threads": res.threads, "max_memory_gb": res.max_memory_gb,
            "default_heap_gb": default_heap_gb(res.memory_gb, res.max_memory_gb),
            "pilon_documented_min_gb": PILON_DOCUMENTED_MIN_GB}


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
    medaka_problem = None
    if "medaka" in strategies_for(inputs):
        try:
            check_request(sample, inputs, ev, "medaka", None, confirmed=True)
        except InputError as exc:
            medaka_problem = str(exc)
    catalogue, error = medaka_catalogue() if tools["medaka"]["status"] == ToolStatus.available.value else \
        (None, tools["medaka"]["message"] or "Medaka is not installed")
    return {
        "draft": draft_summary(draft),
        "tools": tools,
        "strategies_available": strategies_available(tools),
        "files": ev,
        "strategy": strategy,
        "strategies_for_reads": list(strategies_for(inputs)),
        "suggested_strategy": suggested_strategy(sample),
        "preset_suggestion": preset_suggestion(sample, ev),
        "problem": problem,
        "medaka": {**medaka_plan(ev, catalogue, error), "problem": medaka_problem,
                   "draft_is_flye": draft.assembler == "Flye" and draft.parent_assembly_id is None},
        "sample_technology": sample.sequencing_technology,
        "confirmation_required": short_hybrid.needs_confirmation(sample),
        **resources(effective_resources(db)),
    }
