from arva_core.seqstats import StatsParameters
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import job_or_404, project_or_404, sample_or_404
from app.db.session import get_db
from app.models import AnalysisJob, FileFormat, JobStatus, RawFile
from app.schemas.schemas import (
    AnalysisJobDetail,
    AnalysisJobRead,
    BatchQcPlanRead,
    BatchQcRequest,
    SequenceStatsRequest,
)
from app.services import batch_qc
from app.services.jobs import (
    JobStateError,
    ToolUnavailableError,
    cancel_job,
    create_sequence_stats_jobs,
    discard_checkpoint,
    resume_flye_job,
)
from app.services.raw_signal import is_raw_signal, not_reads_message
from app.storage import get_storage
from app.storage.local import StoragePathError

router = APIRouter(tags=["analyses"])


@router.post(
    "/samples/{sample_id}/analyses/sequence-stats",
    response_model=list[AnalysisJobRead],
    status_code=status.HTTP_202_ACCEPTED,
)
def start_sequence_stats(
    sample_id: str, payload: SequenceStatsRequest, db: Session = Depends(get_db)
):
    sample = sample_or_404(db, sample_id)
    query = select(RawFile).where(
        RawFile.sample_id == sample.id, RawFile.file_format != FileFormat.unknown
    )
    if payload.raw_file_ids is not None:
        query = query.where(RawFile.id.in_(payload.raw_file_ids))
    files = list(db.scalars(query).all())
    signal = [f for f in files if is_raw_signal(f)]
    if payload.raw_file_ids is not None and signal:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, not_reads_message(signal[0], "read statistics"))
    files = [f for f in files if not is_raw_signal(f)]
    if payload.raw_file_ids is not None and len(files) != len(set(payload.raw_file_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Some requested files do not belong to this sample or are not FASTQ/FASTA",
        )
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No FASTQ/FASTA files to analyse")

    params = StatsParameters(
        length_bins=payload.length_bins,
        expected_genome_size_bp=payload.expected_genome_size_bp,
    )
    return create_sequence_stats_jobs(db, sample, files, params.as_dict())


@router.get("/samples/{sample_id}/jobs", response_model=list[AnalysisJobDetail])
def list_sample_jobs(sample_id: str, db: Session = Depends(get_db)):
    sample_or_404(db, sample_id)
    return db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.sample_id == sample_id)
        .options(selectinload(AnalysisJob.qc_results))
        .order_by(AnalysisJob.created_at.desc())
    ).all()


@router.get("/projects/{project_id}/jobs", response_model=list[AnalysisJobRead])
def list_project_jobs(project_id: str, db: Session = Depends(get_db)):
    """Project-level jobs (e.g. MultiQC reports), newest first; per-sample jobs are under each sample."""
    project_or_404(db, project_id)
    return db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.project_id == project_id, AnalysisJob.sample_id.is_(None))
        .order_by(AnalysisJob.created_at.desc())
    ).all()


@router.get("/jobs", response_model=list[AnalysisJobRead])
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(AnalysisJob).order_by(AnalysisJob.created_at.desc()).limit(limit)
    if status_filter is not None:
        query = query.where(AnalysisJob.status == status_filter)
    return db.scalars(query).all()


@router.get("/jobs/{job_id}", response_model=AnalysisJobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return job_or_404(db, job_id)


LOG_TAIL_BYTES = 1 << 20


def _tail_lines(text: str, n: int) -> str:
    return "\n".join(text.splitlines()[-n:])


@router.get("/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: str, tail: int = Query(default=200, ge=1, le=5000), db: Session = Depends(get_db)):
    """The last `tail` lines of the job's live tool log while it exists (read from its last MiB), else of the ARVA
    job log. The X-ARVA-Log-Source header says which ("tool" or "job")."""
    job = job_or_404(db, job_id)
    rel = (job.progress or {}).get("log")
    scope = f"results/{job.project_id}/{job.sample_id or '_project'}/{job.id}/"
    if isinstance(rel, str) and rel.startswith(scope) and ".." not in rel.split("/"):
        try:
            path = get_storage().resolve(rel)
        except StoragePathError:
            path = None
        if path is not None and path.is_file():
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - LOG_TAIL_BYTES))
                text = fh.read().decode("utf-8", "replace")
            return PlainTextResponse(_tail_lines(text, tail), headers={
                "X-ARVA-Log-Source": "tool", "X-ARVA-Log-Name": path.name, "Cache-Control": "no-store"})
    return PlainTextResponse(_tail_lines(job.log_text or "", tail),
                             headers={"X-ARVA-Log-Source": "job", "Cache-Control": "no-store"})


@router.post("/jobs/{job_id}/cancel", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def cancel(job_id: str, db: Session = Depends(get_db)):
    """Cancel a queued or running job. A queued job is cancelled at once. A running one keeps status 'running', with
    cancel_requested_at set, until the worker has stopped its tool (within a few seconds) and removed its partial
    outputs; the job log is kept. Cancelling a stopped Flye run after its first stages keeps its work folder so it
    can be resumed."""
    try:
        return cancel_job(db, job_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis job not found") from None
    except JobStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/jobs/{job_id}/resume", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def resume(job_id: str, db: Session = Depends(get_db)):
    """Continue a stopped Flye run in a new job with Flye's --resume, from the work folder the run kept: same reads,
    options, thread count and Flye version."""
    job = job_or_404(db, job_id)
    try:
        return resume_flye_job(db, job)
    except (JobStateError, ToolUnavailableError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete("/jobs/{job_id}/checkpoint", response_model=AnalysisJobRead)
def delete_checkpoint(job_id: str, db: Session = Depends(get_db)):
    """Delete the Flye work folder a stopped run kept for resuming."""
    job = job_or_404(db, job_id)
    try:
        return discard_checkpoint(db, job)
    except JobStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/projects/{project_id}/analyses/batch", response_model=BatchQcPlanRead)
def batch_analyses(project_id: str, payload: BatchQcRequest, response: Response, db: Session = Depends(get_db)):
    """Run ARVA's read statistics, SeqKit and/or FastQC on the files of every sample (or of `sample_ids`). With
    dry_run (the default) only the plan is returned: per file and analysis, 'run' or why no job would be created,
    and the number of jobs per sample. Files with a completed result are skipped unless `recompute`; files with a
    queued or running job of the same analysis are always skipped. To create the jobs (ordinary per-sample jobs),
    send the same selection with dry_run false and the preview's plan_id; if anything changed since, 409 returns
    the new plan."""
    project = project_or_404(db, project_id)
    sel = batch_qc.Selection(tuple(payload.analyses), payload.include_derived, payload.recompute,
                             tuple(payload.sample_ids) if payload.sample_ids else None)
    try:
        if payload.dry_run:
            preview, _ = batch_qc.plan(db, project, sel)
            return {**preview, "dry_run": True}
        preview, jobs = batch_qc.create(db, project, sel, payload.plan_id or "")
    except batch_qc.SelectionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except batch_qc.PlanChangedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": str(exc), "plan": {**exc.plan, "dry_run": True}}) from exc
    except ToolUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    response.status_code = status.HTTP_202_ACCEPTED
    return {**preview, "dry_run": False, "created_job_ids": [j.id for j in jobs]}
