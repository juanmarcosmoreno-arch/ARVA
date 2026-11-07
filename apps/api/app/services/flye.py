"""Flye assembly requests: which files may be assembled, the read-type suggestion and the genome-size options.

Every check here uses recorded evidence only (the sample's metadata, read-header summaries, ARVA read
statistics); a suggestion never changes what the user chose, and a genome size is never assumed.
"""
from __future__ import annotations

import math
import subprocess
from typing import Any

from arva_tools import ToolStatus
from arva_tools.flye import (
    FlyeAdapter,
    FlyeParams,
    memory_estimate,
    pooled_error_rate,
    suggest_read_type,
)
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    FileFormat,
    JobStatus,
    QCResult,
    RawFile,
    Sample,
    SequencingTechnology,
)
from app.services.assemblies import expected_genome_size
from app.services.jobs import FASTQ_STATS_JOB
from app.services.performance import Resources, effective_resources
from app.services.raw_signal import is_raw_signal, not_reads_message

LONG_READ_PLATFORMS = ("nanopore", "pacbio")
CONFIDENT = ("high", "medium")
# Flye counts only reads longer than its smallest minimum overlap (configurator.py, min_overlap_range).
FLYE_MIN_OVERLAP_FLOOR = 1_000
OPTIONAL_OPTIONS = ("--genome-size", "--min-overlap", "--asm-coverage", "--read-error", "--meta",
                    "--keep-haplotypes", "--no-alt-contigs", "--scaffold")
CONFIRMATION_FREE = {SequencingTechnology.nanopore, SequencingTechnology.pacbio, SequencingTechnology.hybrid}


class InputError(ValueError):
    """The selected files cannot be assembled with Flye as requested (HTTP 400)."""


def _latest_stats(db: Session, file_ids: list[str]) -> dict[str, tuple[str, dict[str, Any]]]:
    rows = db.execute(
        select(QCResult.raw_file_id, AnalysisJob.id, QCResult.metrics)
        .join(AnalysisJob, QCResult.analysis_job_id == AnalysisJob.id)
        .where(QCResult.raw_file_id.in_(file_ids), AnalysisJob.status == JobStatus.completed,
               AnalysisJob.job_type == FASTQ_STATS_JOB)
        .order_by(AnalysisJob.finished_at.desc().nulls_last(), AnalysisJob.created_at.desc())
    ).all()
    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for file_id, job_id, metrics in rows:
        latest.setdefault(file_id, (job_id, metrics))
    return latest


def _header(f: RawFile) -> tuple[str | None, str, list[str], list[str]]:
    hm = f.header_metadata or {}
    suggestion = hm.get("suggested_technology") or {}
    distinct = hm.get("distinct") or {}
    values = lambda key: [str(v) for v in (distinct.get(key) or {}).get("values", [])]  # noqa: E731
    return suggestion.get("value"), suggestion.get("confidence") or "none", values("basecall_model"), values("read_type")


def evidence(db: Session, files: list[RawFile]) -> list[dict[str, Any]]:
    from app.services.imports import not_a_mate, sample_lone_mates

    stats = _latest_stats(db, [f.id for f in files])
    lone, fastq_files = sample_lone_mates(db, {f.sample_id for f in files if f.read_mate})
    out = []
    for f in files:
        platform, confidence, models, pacbio = _header(f)
        job_id, m = stats.get(f.id, (None, None))
        quality = (m or {}).get("quality") or {}
        out.append({
            "file_id": f.id, "name": f.original_filename, "origin": f.origin, "read_mate": f.read_mate,
            "lone_mate": not_a_mate(f.id in lone, fastq_files.get(f.sample_id, 0), m["max_length"] if m else None,
                                    platform, confidence),
            "header_platform": platform, "header_confidence": confidence, "basecall_models": models,
            "pacbio_read_types": pacbio, "stats_job_id": job_id,
            "read_count": m["read_count"] if m else None,
            "total_bases": m["total_bases"] if m else None, "max_read_length": m["max_length"] if m else None,
            "read_n50": m["n50"] if m else None, "mean_base_quality": quality.get("mean_base_quality"),
        })
    return out


def check_files(sample: Sample, files: list[RawFile], ev: list[dict[str, Any]], read_type: str | None = None) -> None:
    """Raise InputError when a file cannot be a long-read input for Flye, or contradicts the read type."""
    for f in files:
        if is_raw_signal(f):
            raise InputError(not_reads_message(f, "Flye"))
        if f.file_format not in (FileFormat.fastq, FileFormat.fastq_gz):
            raise InputError(f"{f.original_filename} is not a FASTQ file; ARVA runs Flye on FASTQ reads")
        if not f.is_valid:
            raise InputError(f"{f.original_filename} failed validation and cannot be assembled: {f.validation_message}")
    technology = sample.sequencing_technology
    if technology is SequencingTechnology.illumina:
        raise InputError("This sample's sequencing technology is 'illumina'. Flye assembles long reads (Oxford "
                         "Nanopore or PacBio); correct the technology in the sample's metadata if the files hold "
                         "long reads.")
    for e in ev:
        # A lone mate (no file of the sample is its other half, e.g. ENA's <run>_1.fastq.gz of a single long-read
        # run) is not half of a pair when it is the sample's only FASTQ file or holds long reads (imports.not_a_mate);
        # the length and header checks below still apply.
        if e["read_mate"] and not e.get("lone_mate"):
            raise InputError(f"{e['name']} is marked as read {e['read_mate']} of a pair: paired-end files hold short "
                             "reads, which Flye does not assemble (if it holds long reads, set its mate role to none)")
        if e["header_platform"] == "illumina" and e["header_confidence"] in CONFIDENT:
            raise InputError(f"{e['name']}: its read headers identify Illumina reads ({e['header_confidence']} "
                             "confidence). Flye assembles long reads only")
    platforms = {e["header_platform"]: e["name"] for e in ev
                 if e["header_platform"] in LONG_READ_PLATFORMS and e["header_confidence"] in CONFIDENT}
    if len(platforms) > 1:
        raise InputError("The selected files hold reads of different platforms (" + ", ".join(
            f"{p}: {name}" for p, name in sorted(platforms.items())) + "); Flye assembles one read type per run")
    lengths = [e["max_read_length"] for e in ev]
    if all(n is not None for n in lengths) and max(lengths) <= FLYE_MIN_OVERLAP_FLOOR:
        raise InputError(f"No selected file has a read longer than {FLYE_MIN_OVERLAP_FLOOR:,} bp (ARVA read "
                         "statistics). Flye only uses reads longer than its minimum overlap, which is at least "
                         f"{FLYE_MIN_OVERLAP_FLOOR:,} bp, so these reads cannot be assembled with Flye")
    if read_type is None:
        return
    family = "nanopore" if read_type.startswith("nano") else "pacbio"
    if technology.value in LONG_READ_PLATFORMS and technology.value != family:
        raise InputError(f"Read type {read_type} is for {family} reads, but this sample's sequencing technology is "
                         f"'{technology.value}'")
    for e in ev:
        if e["header_platform"] in LONG_READ_PLATFORMS and e["header_platform"] != family \
                and e["header_confidence"] == "high":
            raise InputError(f"{e['name']}: its read headers identify {e['header_platform']} reads (high confidence); "
                             f"read type {read_type} is for {family} reads")


def check_not_twice(sample: Sample, files: list[RawFile]) -> None:
    """Refuse a filtered file together with a file it was filtered from: Flye stops on the duplicated read IDs."""
    by_id = {f.id: f for f in sample.raw_files}
    selected = {f.id for f in files}
    for f in files:
        seen: set[str] = set()
        parent = by_id.get(f.parent_file_id) if f.parent_file_id else None
        while parent is not None and parent.id not in seen:
            if parent.id in selected:
                raise InputError(f"{f.original_filename} was filtered from {parent.original_filename}, which is selected "
                                 "too: both hold the same reads under the same names, and Flye stops on duplicated "
                                 "read IDs. Select one of them.")
            seen.add(parent.id)
            parent = by_id.get(parent.parent_file_id) if parent.parent_file_id else None


def needs_confirmation(sample: Sample) -> bool:
    return sample.sequencing_technology not in CONFIRMATION_FREE


def _platform(sample: Sample, ev: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    if sample.sequencing_technology.value in LONG_READ_PLATFORMS:
        return sample.sequencing_technology.value, "sample_metadata"
    found = {e["header_platform"] for e in ev}
    if len(found) == 1 and (p := next(iter(found))) in LONG_READ_PLATFORMS \
            and all(e["header_confidence"] in CONFIDENT for e in ev):
        return p, "read_headers"
    return None, None


def read_type_suggestion(sample: Sample, ev: list[dict[str, Any]]) -> dict[str, Any]:
    platform, source = _platform(sample, ev)
    qualities = [(e["mean_base_quality"], e["total_bases"]) for e in ev]
    error = pooled_error_rate(qualities) if all(q is not None and b for q, b in qualities) else None
    out = suggest_read_type(platform, error, sorted({m for e in ev for m in e["basecall_models"]}),
                            sorted({t for e in ev for t in e["pacbio_read_types"]}))
    return {**out, "platform_source": source}


def depth_estimate(total_bases: int, depth_x: float) -> int:
    # Half up, like the interface's Math.round.
    return math.floor(total_bases / depth_x + 0.5)


def genome_size_options(db: Session, sample: Sample, ev: list[dict[str, Any]], depth_x: float | None) -> dict[str, Any]:
    missing = [e["name"] for e in ev if e["total_bases"] is None]
    total = None if missing else sum(e["total_bases"] for e in ev)
    from_depth = None
    if total and depth_x:
        from_depth = {"depth_x": depth_x, "total_read_bases": total, "bp": depth_estimate(total, depth_x)}
    return {"expected": expected_genome_size(db, sample.id, None), "total_read_bases": total,
            "files_without_stats": missing, "from_depth": from_depth}


def check_genome_size(db: Session, sample: Sample, ev: list[dict[str, Any]], params: FlyeParams) -> None:
    """A genome size said to come from the sample or from reads ÷ depth must equal what that gives now."""
    if params.genome_size_basis == "expected_genome_size":
        expected = expected_genome_size(db, sample.id, None)
        if expected["bp"] != params.genome_size_bp:
            known = f"{expected['bp']:,} bp" if expected["bp"] else f"not known ({expected['status'].replace('_', ' ')})"
            raise InputError(f"The sample's expected genome size is {known}, not {params.genome_size_bp:,} bp")
    elif params.genome_size_basis == "reads_over_depth":
        options = genome_size_options(db, sample, ev, params.assumed_depth_x)
        if options["files_without_stats"]:
            raise InputError("A genome size from total read bases ÷ depth needs ARVA read statistics for every "
                             "selected file; compute them first (missing for: "
                             + ", ".join(options["files_without_stats"]) + ")")
        estimate = options["from_depth"]
        if estimate["bp"] != params.genome_size_bp:
            raise InputError(f"Total read bases {estimate['total_read_bases']:,} ÷ {params.assumed_depth_x:g}× = "
                             f"{estimate['bp']:,} bp, not {params.genome_size_bp:,} bp")


def read_bases(ev: list[dict[str, Any]]) -> int | None:
    """The selected files' bases by ARVA's read statistics (None when a file has none yet)."""
    if not ev or any(e["total_bases"] is None for e in ev):
        return None
    return sum(e["total_bases"] for e in ev)


def container_memory_gb(res: Resources) -> float | None:
    """The memory the container (or computer) running Flye has, as measured (cgroup limit or MemTotal), in GB to one
    decimal; None when it could not be read. Flye takes no memory limit, so this, not a profile's share, is what it
    can use."""
    return round(res.usable_memory_gb, 1) if res.memory_known else None


def memory(db: Session, sample: Sample, ev: list[dict[str, Any]], params: FlyeParams | None = None,
           res: Resources | None = None, available_gb: float | None = None) -> dict[str, Any]:
    """ARVA's estimate of whether this Flye run fits the memory the container has (arva_tools.flye.memory_estimate,
    with Flye's fixed k-mer counter floor): for the given parameters, or, for a preview, for the reads alone with the
    sample's expected genome size (when known) for the suggestion. available_gb: a smaller share (a batch's memory
    per job), compared with the part of the estimate that depends on the reads only; the fixed floor is compared with
    the container's memory, which Flye uses whatever a batch reserves."""
    res = res or effective_resources(db)
    if params is not None:
        size, asm, meta = params.genome_size_bp, params.asm_coverage, params.meta
    else:
        size, asm, meta = expected_genome_size(db, sample.id, None)["bp"], None, False
    container = container_memory_gb(res)
    available = container
    if available_gb is not None:
        available = available_gb if container is None else min(container, available_gb)
    out = memory_estimate(read_bases(ev), available, asm, size, meta, container_gb=container)
    out["container_memory_gb"] = container
    out["in_container"] = res.in_container
    out["expected_genome_size_bp"] = expected_genome_size(db, sample.id, None)["bp"]
    return out


# The memory verdicts (arva_tools.flye.memory_estimate) for which Docker has too little memory for this run: below
# Flye's fixed k-mer table floor (about 8.6 GB whatever the reads, log item 29), within a gigabyte of it, or short for
# these reads. Only then is running Flye natively on the Mac offered.
NATIVE_WHEN = ("below_floor", "tight", "may_not_fit")


def native_offer(estimate: dict[str, Any]) -> dict[str, Any]:
    """Whether the dialog offers "Run on this Mac (native)": when the memory estimate says Docker is short and
    ARVA.app's executor is known with a Flye; ready when it is open and can run it now (else `reason`, such as
    app_not_open, which the interface explains)."""
    from app.services import native

    st = native.status()
    tool = st["tools"].get("flye")
    short = estimate.get("verdict") in NATIVE_WHEN
    reason = tool["reason"] if tool else ("app_not_open" if st["known"] and not st["open"] else
                                          "not_installed" if st["known"] else "not_known")
    return {"memory_short": short, "offered": short and tool is not None, "ready": bool(tool and tool["ready"]),
            "app_open": st["open"], "reason": None if tool and tool["ready"] else reason,
            "flye": {k: tool[k] for k in ("version", "build", "lock_matches")} if tool else None,
            "mac_memory_bytes": st["memory_bytes"], "chip": st["chip"]}


def tool_status(res: Resources) -> dict[str, Any]:
    d = detect("flye")
    options: list[str] = []
    if d.status is ToolStatus.available and d.path:
        try:
            supported = FlyeAdapter.help_options(d.path)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            supported = frozenset()
        options = [o for o in OPTIONAL_OPTIONS if o in supported]
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "reason_params": d.reason_params, "options": options, "max_threads": res.max_threads,
            "default_threads": res.threads}


def plan(db: Session, sample: Sample, files: list[RawFile], depth_x: float | None) -> dict[str, Any]:
    ev = evidence(db, files)
    check_files(sample, files, ev)
    estimate = memory(db, sample, ev)
    return {
        "tool": tool_status(effective_resources(db)),
        "files": ev,
        "read_type_suggestion": read_type_suggestion(sample, ev),
        "genome_size": genome_size_options(db, sample, ev, depth_x),
        "memory": estimate,
        "sample_technology": sample.sequencing_technology,
        "long_reads_confirmation_required": needs_confirmation(sample),
        "native": native_offer(estimate),
    }
