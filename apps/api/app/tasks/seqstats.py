"""Worker task: ARVA's own sequence statistics for one file (arva-core)."""
from __future__ import annotations

import json

import numpy as np
from arva_core.seqstats import (
    SequenceFormatError,
    StatsParameters,
    compute_sequence_stats,
    quick_validate,
)

from app.models import QCResult
from app.services.imports import header_metadata
from app.services.raw_signal import is_raw_signal, not_reads_message
from app.tasks.common import JobContext, JobFailure, run_job


def _body(ctx: JobContext) -> None:
    (raw,) = ctx.input_files()
    if is_raw_signal(raw):
        # Raised before parsing, so a valid POD5 is never marked invalid by the FASTQ/FASTA validator.
        raise JobFailure(not_reads_message(raw, "read statistics"), "pod5_not_reads", file=raw.original_filename)
    ctx.log(f"numpy {np.__version__}")
    ctx.log(f"Input: {raw.original_filename} ({raw.size_bytes} bytes, sha256 {raw.checksum_sha256})",
            flush=True)
    params = StatsParameters(**(ctx.job.parameters or {}))

    def progress(n: int) -> None:
        ctx.log(f"Processed {n:,} records", flush=True)
        ctx.check_cancelled()

    try:
        stats = compute_sequence_stats(ctx.path(raw.stored_path), params, progress=progress)
    except SequenceFormatError as exc:
        raise JobFailure(f"Invalid input: {exc}", "invalid_input", detail=str(exc)) from exc
    ctx.log(f"Processed {stats['read_count']:,} records, {stats['total_bases']:,} bases")
    for warning in stats["warnings"]:
        ctx.log(f"WARNING: {warning}")

    out_rel = f"{ctx.results_rel}/sequence_stats.json"
    ctx.storage.write_text(out_rel, json.dumps(stats, indent=1))
    ctx.job.output_paths = [out_rel]

    quality = stats["quality"] or {}
    ctx.db.add(
        QCResult(
            analysis_job_id=ctx.job.id,
            raw_file_id=raw.id,
            read_count=stats["read_count"],
            total_bases=stats["total_bases"],
            mean_length=stats["mean_length"],
            n50=stats["n50"],
            gc_percent=stats["gc_percent"],
            mean_quality=quality.get("mean_read_quality"),
            metrics=stats,
        )
    )
    raw.is_valid = True
    raw.validation_message = f"Entire file validated: {stats['read_count']:,} well-formed records."
    raw.validation_detail = {"code": "entire", "params": {"count": stats["read_count"]}}
    ctx.log(f"Result written to {out_rel}")
    if raw.header_metadata is None:
        # Files imported before read headers were summarised at import.
        raw.header_metadata = header_metadata(quick_validate(ctx.path(raw.stored_path)).headers)
        if raw.header_metadata is not None:
            ctx.log(f"Summarised the first {raw.header_metadata['n_headers_read']:,} read headers")


def _on_failure(ctx: JobContext, exc: BaseException) -> None:
    cause = exc.__cause__
    if isinstance(cause, SequenceFormatError):
        for raw in ctx.input_files():
            raw.is_valid = False
            raw.validation_message = f"Full validation failed: {cause}"
            raw.validation_detail = {"code": "full_failed", "params": {"detail": str(cause)}}


def run_sequence_stats_job(job_id: str) -> str:
    return run_job(job_id, _body, _on_failure)
