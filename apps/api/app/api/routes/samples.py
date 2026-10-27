from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import project_or_404, sample_or_404
from app.db.session import get_db
from app.models import RawFile, Sample
from app.schemas.schemas import SampleCreate, SampleRead, SampleUpdate

router = APIRouter(tags=["samples"])


def to_sample_read(db: Session, samples: list[Sample]) -> list[SampleRead]:
    ids = [s.id for s in samples]
    counts = (
        dict(
            db.execute(
                select(RawFile.sample_id, func.count(RawFile.id))
                .where(RawFile.sample_id.in_(ids))
                .group_by(RawFile.sample_id)
            ).all()
        )
        if ids
        else {}
    )
    return [
        SampleRead.model_validate(s).model_copy(
            update={"file_count": counts.get(s.id, 0), "project_name": s.project.name}
        )
        for s in samples
    ]


def _ensure_unique_code(db: Session, project_id: str, code: str, exclude_id: str | None = None):
    query = select(Sample.id).where(Sample.project_id == project_id, Sample.sample_code == code)
    if exclude_id:
        query = query.where(Sample.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Sample ID '{code}' already exists in this project")


@router.get("/samples", response_model=list[SampleRead])
def list_all_samples(db: Session = Depends(get_db)):
    samples = db.scalars(
        select(Sample).options(selectinload(Sample.project)).order_by(Sample.updated_at.desc())
    ).all()
    return to_sample_read(db, list(samples))


@router.get("/projects/{project_id}/samples", response_model=list[SampleRead])
def list_samples(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    samples = db.scalars(
        select(Sample).where(Sample.project_id == project_id).order_by(Sample.sample_code)
    ).all()
    return to_sample_read(db, list(samples))


@router.post(
    "/projects/{project_id}/samples", response_model=SampleRead, status_code=status.HTTP_201_CREATED
)
def create_sample(project_id: str, payload: SampleCreate, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    _ensure_unique_code(db, project_id, payload.sample_code)
    sample = Sample(project_id=project_id, **payload.model_dump())
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return to_sample_read(db, [sample])[0]


@router.get("/samples/{sample_id}", response_model=SampleRead)
def get_sample(sample_id: str, db: Session = Depends(get_db)):
    return to_sample_read(db, [sample_or_404(db, sample_id)])[0]


@router.patch("/samples/{sample_id}", response_model=SampleRead)
def update_sample(sample_id: str, payload: SampleUpdate, db: Session = Depends(get_db)):
    sample = sample_or_404(db, sample_id)
    changes = payload.model_dump(exclude_unset=True)
    if "sample_code" in changes:
        _ensure_unique_code(db, sample.project_id, changes["sample_code"], exclude_id=sample.id)
    for key, value in changes.items():
        setattr(sample, key, value)
    db.commit()
    db.refresh(sample)
    return to_sample_read(db, [sample])[0]


@router.delete("/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample(sample_id: str, db: Session = Depends(get_db)):
    """Remove the sample's records. Stored raw files remain on disk (raw data is never deleted)."""
    db.delete(sample_or_404(db, sample_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
