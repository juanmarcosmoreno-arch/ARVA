"""Creation and dispatch of analysis jobs.

Jobs are created in the request (status `pending`, with the tool version
detected at that moment) and executed by the worker.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from arva_core.seqstats import TOOL_NAME, TOOL_VERSION
from arva_tools import DetectedTool, ToolStatus
from arva_tools.fastp import FastpParams
from arva_tools.filtlong import FiltlongParams
from arva_tools.flye import FlyeAdapter, FlyeParams
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.models import AnalysisJob, JobStatus, Project, RawFile, Sample
from app.services.queue import get_queue
from app.services.raw_signal import POD5_INSTALL, is_raw_signal, pod5_versions

FASTQ_STATS_JOB = "sequence_stats"
SEQKIT_JOB = "seqkit_stats"
FASTQC_JOB = "fastqc"
FASTP_JOB = "fastp"
FILTLONG_JOB = "filtlong"
SERVER_IMPORT_JOB = "server_import"
SERVER_IMPORT_TOOL = "arva-import"
POD5_JOB = "pod5_summary"
POD5_TOOL = "pod5"
MULTIQC_JOB = "multiqc"
NANOPLOT_JOB = "nanoplot"
FLYE_JOB = "flye_assembly"


class ToolUnavailableError(RuntimeError):
    pass


def _enqueue(jobs: list[AnalysisJob], func) -> None:
    queue = get_queue()
    for job in jobs:
        queue.enqueue(func, job.id, job_id=f"arva-{job.id}")


def require_tool(tool_id: str) -> DetectedTool:
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available:
        raise ToolUnavailableError(f"{d.info.name} is not available ({d.status.value}): {d.message}")
    return d


def new_sequence_stats_job(sample: Sample, raw_id: str, parameters: dict, parent_job_id: str | None = None) -> AnalysisJob:
    return AnalysisJob(
        project_id=sample.project_id,
        sample_id=sample.id,
        job_type=FASTQ_STATS_JOB,
        tool_name=TOOL_NAME,
        tool_version=TOOL_VERSION,
        parameters=parameters,
        input_raw_file_ids=[raw_id],
        status=JobStatus.pending,
        log_text="",
        parent_job_id=parent_job_id,
    )


def enqueue_sequence_stats(jobs: list[AnalysisJob]) -> None:
    from app.tasks.seqstats import run_sequence_stats_job

    _enqueue(jobs, run_sequence_stats_job)


def create_sequence_stats_jobs(
    db: Session,
    sample: Sample,
    raw_files: list[RawFile],
    parameters: dict,
    parent_job_id: str | None = None,
) -> list[AnalysisJob]:
    """Create one ARVA statistics job per input file and enqueue them."""
    jobs = [new_sequence_stats_job(sample, raw.id, parameters, parent_job_id) for raw in raw_files]
    db.add_all(jobs)
    db.commit()
    enqueue_sequence_stats(jobs)
    for job in jobs:
        db.refresh(job)
    return jobs


def files_without_stats(db: Session, sample_id: str, files: list[RawFile]) -> list[RawFile]:
    """Read files with no pending, running or completed ARVA statistics job."""
    existing = db.scalars(
        select(AnalysisJob).where(
            AnalysisJob.sample_id == sample_id,
            AnalysisJob.job_type == FASTQ_STATS_JOB,
            AnalysisJob.status != JobStatus.failed,
        )
    ).all()
    covered = {fid for j in existing for fid in (j.input_raw_file_ids or [])}
    return [f for f in files if f.id not in covered and not is_raw_signal(f)]


def _tool_job(sample: Sample, job_type: str, tool: DetectedTool, parameters: dict, inputs: list[str]) -> AnalysisJob:
    return AnalysisJob(
        project_id=sample.project_id,
        sample_id=sample.id,
        job_type=job_type,
        tool_name=tool.info.name,
        tool_version=tool.version or "unknown",
        tool_path=tool.path,
        parameters=parameters,
        input_raw_file_ids=inputs,
        status=JobStatus.pending,
        log_text="",
    )


def create_per_file_tool_jobs(
    db: Session, sample: Sample, files: list[RawFile], tool_id: str, parameters: dict | None = None
) -> list[AnalysisJob]:
    from app.tasks.tools import run_fastqc_job, run_nanoplot_job, run_seqkit_job

    job_type, func = {
        "seqkit": (SEQKIT_JOB, run_seqkit_job),
        "fastqc": (FASTQC_JOB, run_fastqc_job),
        "nanoplot": (NANOPLOT_JOB, run_nanoplot_job),
    }[tool_id]
    tool = require_tool(tool_id)
    threads = get_settings().tool_threads
    jobs = [_tool_job(sample, job_type, tool, {"threads": threads, **(parameters or {})}, [f.id]) for f in files]
    db.add_all(jobs)
    db.commit()
    _enqueue(jobs, func)
    for job in jobs:
        db.refresh(job)
    return jobs


def create_fastp_job(db: Session, sample: Sample, r1: RawFile, r2: RawFile | None, params: FastpParams) -> AnalysisJob:
    from app.tasks.tools import run_fastp_job

    params.threads = min(params.threads, get_settings().tool_threads)
    params.validate(paired=r2 is not None)
    tool = require_tool("fastp")
    inputs = [r1.id] + ([r2.id] if r2 else [])
    job = _tool_job(sample, FASTP_JOB, tool, params.as_dict(), inputs)
    db.add(job)
    db.commit()
    _enqueue([job], run_fastp_job)
    db.refresh(job)
    return job


def create_filtlong_job(db: Session, sample: Sample, f: RawFile, params: FiltlongParams) -> AnalysisJob:
    from app.tasks.tools import run_filtlong_job

    params.validate()
    tool = require_tool("filtlong")
    job = _tool_job(sample, FILTLONG_JOB, tool, params.as_dict(), [f.id])
    db.add(job)
    db.commit()
    _enqueue([job], run_filtlong_job)
    db.refresh(job)
    return job


def create_flye_job(db: Session, sample: Sample, files: list[RawFile], params: FlyeParams,
                    provenance: dict) -> AnalysisJob:
    """One assembly job; `provenance` (request evidence such as ARVA's read-type suggestion) is stored with the
    parameters and never passed to Flye."""
    from app.tasks.tools import run_flye_job

    tool = require_tool("flye")
    try:
        supported = FlyeAdapter.help_options(tool.path or "flye")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailableError(f"Flye's --help could not be read to check its options: {exc}") from exc
    params.threads = min(params.threads, get_settings().tool_threads)
    params.validate(supported)
    job = _tool_job(sample, FLYE_JOB, tool, {**params.as_dict(), **provenance}, [f.id for f in files])
    db.add(job)
    db.commit()
    _enqueue([job], run_flye_job)
    db.refresh(job)
    return job


def create_server_import_job(db: Session, sample: Sample, root: Path, paths: list[str]) -> AnalysisJob:
    """One job copies every selected file of a server folder into the sample."""
    from app.tasks.server_import import run_server_import_job

    job = AnalysisJob(
        project_id=sample.project_id,
        sample_id=sample.id,
        job_type=SERVER_IMPORT_JOB,
        tool_name=SERVER_IMPORT_TOOL,
        tool_version=__version__,
        parameters={"root": str(root), "paths": paths},
        input_raw_file_ids=[],
        status=JobStatus.pending,
        log_text="",
    )
    db.add(job)
    db.commit()
    _enqueue([job], run_server_import_job)
    db.refresh(job)
    return job


def create_pod5_jobs(db: Session, sample: Sample, files: list[RawFile]) -> list[AnalysisJob]:
    """One run-metadata job per POD5 file, read by the worker with the optional pod5 library."""
    from app.tasks.pod5_summary import run_pod5_summary_job

    versions = pod5_versions()
    if versions["pod5"] is None:
        raise ToolUnavailableError(
            f"The optional pod5 library is not installed in ARVA's Python environment. Install it with: {POD5_INSTALL}"
        )
    jobs = [
        AnalysisJob(
            project_id=sample.project_id,
            sample_id=sample.id,
            job_type=POD5_JOB,
            tool_name=POD5_TOOL,
            tool_version=versions["pod5"],
            parameters={"lib_pod5_version": versions["lib_pod5"], "signal_decoded": False},
            input_raw_file_ids=[f.id],
            status=JobStatus.pending,
            log_text="",
        )
        for f in files
    ]
    db.add_all(jobs)
    db.commit()
    _enqueue(jobs, run_pod5_summary_job)
    for job in jobs:
        db.refresh(job)
    return jobs


def create_multiqc_job(db: Session, project: Project, parameters: dict, file_ids: list[str]) -> AnalysisJob:
    """One project-level job: the inputs were chosen in the request and are recorded in `parameters`."""
    from app.tasks.tools import run_multiqc_job

    tool = require_tool("multiqc")
    job = AnalysisJob(
        project_id=project.id,
        sample_id=None,
        job_type=MULTIQC_JOB,
        tool_name=tool.info.name,
        tool_version=tool.version or "unknown",
        tool_path=tool.path,
        parameters=parameters,
        input_raw_file_ids=file_ids,
        status=JobStatus.pending,
        log_text="",
    )
    db.add(job)
    db.commit()
    _enqueue([job], run_multiqc_job)
    db.refresh(job)
    return job
