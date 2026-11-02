from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.access import current_user, visible_projects
from app.db.session import get_db
from app.models import Project, Sample
from app.services import assist as svc
from app.services import auth

router = APIRouter(tags=["assist"])


class SettingsIn(BaseModel):
    enabled: bool
    provider: str | None = Field(default=None, max_length=64)
    endpoint: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=4000)
    clear_key: bool = False


class GuideItem(BaseModel):
    id: str = Field(max_length=100)
    title: str = Field(max_length=200)
    text: str = Field(max_length=svc.MAX_GUIDE_CHARS)


class SequenceRef(BaseModel):
    annotation_id: str = Field(max_length=36)
    feature_id: str = Field(max_length=20)


class AskIn(BaseModel):
    question: str = Field(max_length=svc.MAX_QUESTION)
    # Named about_* so that access control asks for read access only (asking changes nothing in the project).
    about_project_id: str | None = Field(default=None, max_length=36)
    about_sample_id: str | None = Field(default=None, max_length=36)
    guide: list[GuideItem] = Field(default_factory=list, max_length=svc.MAX_GUIDE_ITEMS)
    sequence_refs: list[SequenceRef] = Field(default_factory=list, max_length=5)
    sequence_consent: bool = False


@router.get("/assist/status")
def assist_status(db: Session = Depends(get_db)):
    return svc.status(db)


@router.get("/assist/settings")
def get_settings_(db: Session = Depends(get_db)):
    return svc.settings_view(db)


@router.put("/assist/settings")
def put_settings(payload: SettingsIn, request: Request, db: Session = Depends(get_db)):
    """Enable or disable ARVA Assist; the key is written to an owner-only file and never returned."""
    view = svc.save_settings(db, payload.enabled, payload.provider, payload.endpoint, payload.model,
                             payload.api_key, payload.clear_key)
    auth.audit(db, "assist_settings", "allowed", current_user(request), enabled=payload.enabled,
               provider=payload.provider, key_changed=bool(payload.api_key) or payload.clear_key)
    db.commit()
    return view


def _payload(db: Session, request: Request, body: AskIn) -> tuple[dict, str | None]:
    visible = visible_projects(request)

    def can_read(pid: str) -> bool:
        return visible is None or pid in visible

    project = None
    if body.about_project_id:
        project = db.get(Project, body.about_project_id)
        if project is None or not can_read(project.id):
            raise svc.AssistError("assist_not_found", 404)
    if body.about_sample_id:
        sample = db.get(Sample, body.about_sample_id)
        if sample is None or project is None or sample.project_id != project.id:
            raise svc.AssistError("assist_not_found", 404)
    payload = svc.build_payload(db, body.question, project, body.about_sample_id,
                                [g.model_dump() for g in body.guide], [r.model_dump() for r in body.sequence_refs],
                                body.sequence_consent, can_read)
    return payload, project.id if project else None


@router.post("/assist/preview")
def preview(body: AskIn, request: Request, db: Session = Depends(get_db)):
    """Exactly what would be sent, without sending anything."""
    payload, _ = _payload(db, request, body)
    return {"payload": payload, "status": svc.status(db)}


@router.post("/assist/ask")
def ask(body: AskIn, request: Request, db: Session = Depends(get_db)):
    payload, project_id = _payload(db, request, body)
    return svc.ask(db, current_user(request), payload, project_id)


@router.get("/assist/audit")
def assist_audit(limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)):
    return svc.audit_rows(db, limit)
