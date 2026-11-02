from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import visible_projects
from app.api.routes.projects import to_project_read
from app.db.session import get_db
from app.models import AnalysisJob, JobStatus, Project, RawFile, Sample
from app.schemas.schemas import AnalysisJobRead, DashboardSummary
from app.storage import get_storage

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(request: Request, db: Session = Depends(get_db)):
    visible = visible_projects(request)

    def only(q, col):
        return q if visible is None else q.where(col.in_(visible))

    status_counts = dict(db.execute(only(select(AnalysisJob.status, func.count(AnalysisJob.id)), AnalysisJob.project_id)
                                    .group_by(AnalysisJob.status)).all())
    recent_jobs = db.scalars(only(select(AnalysisJob), AnalysisJob.project_id)
                             .order_by(AnalysisJob.created_at.desc()).limit(8)).all()
    recent_projects = db.scalars(only(select(Project), Project.id).order_by(Project.updated_at.desc()).limit(5)).all()
    files = select(RawFile).join(Sample, Sample.id == RawFile.sample_id)
    return DashboardSummary(
        project_count=db.scalar(only(select(func.count(Project.id)), Project.id)) or 0,
        sample_count=db.scalar(only(select(func.count(Sample.id)), Sample.project_id)) or 0,
        raw_file_count=db.scalar(only(files.with_only_columns(func.count(RawFile.id)), Sample.project_id)) or 0,
        total_raw_bytes=db.scalar(only(files.with_only_columns(func.coalesce(func.sum(RawFile.size_bytes), 0)),
                                       Sample.project_id)) or 0,
        jobs_running=status_counts.get(JobStatus.running, 0) + status_counts.get(JobStatus.pending, 0),
        jobs_completed=status_counts.get(JobStatus.completed, 0),
        jobs_failed=status_counts.get(JobStatus.failed, 0),
        storage_used_bytes=get_storage().usage_bytes(),
        recent_jobs=[AnalysisJobRead.model_validate(j) for j in recent_jobs],
        recent_projects=to_project_read(db, list(recent_projects)),
    )
