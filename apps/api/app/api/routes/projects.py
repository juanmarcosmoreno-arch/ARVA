from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import project_or_404
from app.db.session import get_db
from app.models import Project, Sample
from app.schemas.schemas import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


def _sample_counts(db: Session, project_ids: list[str]) -> dict[str, int]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(Sample.project_id, func.count(Sample.id))
        .where(Sample.project_id.in_(project_ids))
        .group_by(Sample.project_id)
    )
    return dict(rows.all())


def to_project_read(db: Session, projects: list[Project]) -> list[ProjectRead]:
    counts = _sample_counts(db, [p.id for p in projects])
    return [
        ProjectRead.model_validate(p).model_copy(update={"sample_count": counts.get(p.id, 0)})
        for p in projects
    ]


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return to_project_read(db, list(projects))


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return to_project_read(db, [project])[0]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return to_project_read(db, [project_or_404(db, project_id)])[0]


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return to_project_read(db, [project])[0]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """Remove the project's records. Stored raw files remain on disk (raw data is never deleted)."""
    db.delete(project_or_404(db, project_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
