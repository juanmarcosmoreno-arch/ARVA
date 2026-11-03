from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import current_user, visible_projects
from app.api.deps import project_or_404
from app.db.session import get_db
from app.models import Project, Sample
from app.schemas.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import auth, deletion

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
def list_projects(request: Request, db: Session = Depends(get_db)):
    q = select(Project).order_by(Project.updated_at.desc())
    visible = visible_projects(request)
    if visible is not None:
        q = q.where(Project.id.in_(visible))
    projects = db.scalars(q).all()
    return to_project_read(db, list(projects))


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    project = Project(**payload.model_dump(), owner_id=user.id if user else None)
    db.add(project)
    db.commit()
    db.refresh(project)
    return to_project_read(db, [project])[0]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return to_project_read(db, [project_or_404(db, project_id)])[0]


def _owner_or_admin(request: Request, project: Project) -> None:
    """A write share lets a collaborator add and analyse samples; renaming or deleting the project, like sharing it,
    is for its owner or an administrator."""
    me = current_user(request)
    if me is not None and me.role != "admin" and project.owner_id != me.id:
        raise auth.AuthError("auth_project_owner_only", 403)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, payload: ProjectUpdate, request: Request, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    _owner_or_admin(request, project)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return to_project_read(db, [project])[0]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    """Remove the project's records and its derived outputs (results, processed files, kept work folders, archived
    reports). Stored raw files remain on disk (raw data is never deleted). Refused while one of its jobs is queued
    or running, since the tool would otherwise go on writing for a job that no longer exists."""
    project = project_or_404(db, project_id)
    _owner_or_admin(request, project)
    active = deletion.active_jobs(db, project.id)
    if active:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={
            "detail": f"{active} job(s) of this project are queued or running. Cancel them first.",
            "code": "delete_active_jobs", "params": {"count": active}})
    db.delete(project)
    db.commit()
    deletion.remove_outputs(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
