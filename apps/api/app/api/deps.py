from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AnalysisJob, Project, RawFile, Sample


def get_or_404(db: Session, model, obj_id: str, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return obj


def project_or_404(db: Session, project_id: str) -> Project:
    return get_or_404(db, Project, project_id, "Project")


def sample_or_404(db: Session, sample_id: str) -> Sample:
    return get_or_404(db, Sample, sample_id, "Sample")


def raw_file_or_404(db: Session, file_id: str) -> RawFile:
    return get_or_404(db, RawFile, file_id, "File")


def job_or_404(db: Session, job_id: str) -> AnalysisJob:
    return get_or_404(db, AnalysisJob, job_id, "Analysis job")
