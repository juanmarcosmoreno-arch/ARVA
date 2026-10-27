from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arva_core.seqstats import StatsParameters

from app.api.deps import job_or_404, sample_or_404
from app.db.session import get_db
from app.models import AnalysisJob, FileFormat, JobStatus, RawFile
from app.schemas.schemas import AnalysisJobDetail, AnalysisJobRead, SequenceStatsRequest
from app.services.jobs import create_sequence_stats_jobs

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
