"""Worker task: compute sequence statistics for one raw file.

Runs in an RQ worker process (see apps/workers). Each execution records the
tool, version, parameters, input checksum, environment, timings and log in
the AnalysisJob row, and the full result as JSON on disk.
"""
from __future__ import annotations

import json
import platform
import time
import traceback
from datetime import datetime, timezone

import numpy as np

from arva_core.seqstats import SequenceFormatError, StatsParameters, compute_sequence_stats

from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus, QCResult, RawFile
from app.storage import get_storage


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _JobLog:
    def __init__(self, db, job: AnalysisJob):
        self.db = db
        self.job = job
        self.lines: list[str] = []

    def __call__(self, message: str, flush: bool = False) -> None:
        self.lines.append(f"[{_now().isoformat(timespec='seconds')}] {message}")
        if flush:
            self.flush()

    def flush(self) -> None:
        self.job.log_text = "\n".join(self.lines)
        self.db.commit()


def run_sequence_stats_job(job_id: str) -> str:
    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, job_id)
        if job is None:
            raise LookupError(f"analysis job {job_id} not found")
        log = _JobLog(db, job)
        storage = get_storage()
        started = time.monotonic()
        job.status = JobStatus.running
        job.started_at = _now()
        log(f"Tool: {job.tool_name} {job.tool_version}")
        log(f"Environment: Python {platform.python_version()}, numpy {np.__version__}, "
            f"{platform.system()} {platform.machine()}")
        log(f"Parameters: {json.dumps(job.parameters, sort_keys=True)}", flush=True)

        raw: RawFile | None = None
        try:
            raw = db.get(RawFile, (job.input_raw_file_ids or [None])[0])
            if raw is None:
                raise LookupError("input raw file not found")
            log(f"Input: {raw.original_filename} ({raw.size_bytes} bytes, sha256 {raw.checksum_sha256})",
                flush=True)
            params = StatsParameters(**(job.parameters or {}))
            stats = compute_sequence_stats(
                storage.resolve(raw.stored_path),
                params,
                progress=lambda n: log(f"Processed {n:,} records", flush=True),
            )
            log(f"Processed {stats['read_count']:,} records, {stats['total_bases']:,} bases")
            for warning in stats["warnings"]:
                log(f"WARNING: {warning}")

            sample = job.sample
            out_rel = f"results/{sample.project_id}/{sample.id}/{job.id}/sequence_stats.json"
            storage.write_text(out_rel, json.dumps(stats, indent=1))
            job.output_paths = [out_rel]

            quality = stats["quality"] or {}
            db.add(
                QCResult(
                    analysis_job_id=job.id,
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
            raw.validation_message = (
                f"Entire file validated: {stats['read_count']:,} well-formed records."
            )
            job.status = JobStatus.completed
            log(f"Result written to {out_rel}")
        except SequenceFormatError as exc:
            job.status = JobStatus.failed
            job.error_message = f"Invalid input: {exc}"
            if raw is not None:
                raw.is_valid = False
                raw.validation_message = f"Full validation failed: {exc}"
            log(f"ERROR: {job.error_message}")
        except Exception as exc:  # noqa: BLE001 - record any failure on the job
            job.status = JobStatus.failed
            job.error_message = f"{type(exc).__name__}: {exc}"
            log("ERROR: unexpected failure\n" + traceback.format_exc())

        job.finished_at = _now()
        job.duration_seconds = round(time.monotonic() - started, 3)
        log(f"Finished with status '{job.status.value}' in {job.duration_seconds:.2f}s")
        log.flush()
        storage.write_text(f"logs/{job.id}.log", job.log_text or "")
        return job.status.value
    finally:
        db.close()
