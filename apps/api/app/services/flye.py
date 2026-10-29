"""Flye assembly requests: which files may be assembled, the read-type suggestion and the genome-size options.

Every check here uses recorded evidence only (the sample's metadata, read-header summaries, ARVA read
statistics); a suggestion never changes what the user chose, and a genome size is never assumed.
"""
from __future__ import annotations

import math
import subprocess
from typing import Any

from arva_tools import ToolStatus
from arva_tools.flye import FlyeAdapter, FlyeParams, pooled_error_rate, suggest_read_type
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
    stats = _latest_stats(db, [f.id for f in files])
    out = []
    for f in files:
        platform, confidence, models, pacbio = _header(f)
        job_id, m = stats.get(f.id, (None, None))
        quality = (m or {}).get("quality") or {}
        out.append({
            "file_id": f.id, "name": f.original_filename, "origin": f.origin, "read_mate": f.read_mate,
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
        if e["read_mate"]:
            raise InputError(f"{e['name']} is marked as read {e['read_mate']} of a pair: paired-end files hold short "
                             "reads, which Flye does not assemble")
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
            "message": d.message, "reason": d.reason, "options": options, "max_threads": res.max_threads,
            "default_threads": res.threads}


def plan(db: Session, sample: Sample, files: list[RawFile], depth_x: float | None) -> dict[str, Any]:
    ev = evidence(db, files)
    check_files(sample, files, ev)
    return {
        "tool": tool_status(effective_resources(db)),
        "files": ev,
        "read_type_suggestion": read_type_suggestion(sample, ev),
        "genome_size": genome_size_options(db, sample, ev, depth_x),
        "sample_technology": sample.sequencing_technology,
        "long_reads_confirmation_required": needs_confirmation(sample),
    }
