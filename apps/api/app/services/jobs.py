"""Creation and dispatch of analysis jobs."""
from __future__ import annotations

from arva_core.seqstats import TOOL_NAME, TOOL_VERSION
from sqlalchemy.orm import Session

from app.models import AnalysisJob, JobStatus, RawFile, Sample
from app.services.queue import get_queue

FASTQ_STATS_JOB = "sequence_stats"


def create_sequence_stats_jobs(
    db: Session,
    sample: Sample,
    raw_files: list[RawFile],
    parameters: dict,
) -> list[AnalysisJob]:
    """Create one job per input file and enqueue them for the worker."""
    jobs = []
    for raw in raw_files:
        job = AnalysisJob(
            sample_id=sample.id,
            job_type=FASTQ_STATS_JOB,
            tool_name=TOOL_NAME,
            tool_version=TOOL_VERSION,
            parameters=parameters,
            input_raw_file_ids=[raw.id],
            status=JobStatus.pending,
            log_text="",
        )
        db.add(job)
        jobs.append(job)
    db.commit()

    from app.tasks.seqstats import run_sequence_stats_job

    queue = get_queue()
    for job in jobs:
        queue.enqueue(run_sequence_stats_job, job.id, job_id=f"arva-{job.id}")
    for job in jobs:
        db.refresh(job)
    return jobs
