from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import current_user
from app.api.deps import project_or_404
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuditEvent, Project, ProjectShare, User
from app.services import auth

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=auth.MAX_PASSWORD)


class SetupIn(LoginIn):
    token: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=auth.MAX_PASSWORD)
    new: str = Field(min_length=1, max_length=auth.MAX_PASSWORD)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=auth.MAX_PASSWORD)
    role: Literal["admin", "analyst", "viewer"]
    display_name: str | None = Field(default=None, max_length=200)


class UserPatch(BaseModel):
    role: Literal["admin", "analyst", "viewer"] | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=1, max_length=auth.MAX_PASSWORD)


class ShareIn(BaseModel):
    user_id: str = Field(max_length=36)
    access: Literal["read", "write"] | None


def _user_row(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
            "is_active": u.is_active, "last_login_at": u.last_login_at, "created_at": u.created_at,
            "locked": u.locked_until is not None}


def _enabled() -> None:
    if not get_settings().auth_enabled:
        raise auth.AuthError("auth_disabled", 409)


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    age = s.session_hours * 3600
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=age, httponly=True, samesite="strict",
                        secure=s.cookie_secure, path="/")
    response.set_cookie(auth.CSRF_COOKIE, csrf, max_age=age, httponly=False, samesite="strict",
                        secure=s.cookie_secure, path="/")


@router.get("/auth/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    """Whether accounts are on, whether the first administrator still has to be created, and who is signed in."""
    s = get_settings()
    if not s.auth_enabled:
        return {"enabled": False, "setup_required": False, "user": None}
    found = auth.session_user(db, request.cookies.get(auth.SESSION_COOKIE))
    setup = auth.user_count(db) == 0
    if setup:
        auth.setup_token()
    return {"enabled": True, "setup_required": setup,
            "setup_token_file": str(s.secrets_dir / auth.SETUP_TOKEN_FILE) if setup else None,
            "user": _user_row(found[0]) if found else None}


@router.post("/auth/setup", status_code=status.HTTP_201_CREATED)
def auth_setup(payload: SetupIn, response: Response, db: Session = Depends(get_db)):
    _enabled()
    user = auth.setup_first_admin(db, payload.token, payload.username, payload.password, payload.display_name)
    auth.audit(db, "setup", "allowed", user)
    _, token, csrf = auth.login(db, payload.username, payload.password)
    db.commit()
    _set_cookies(response, token, csrf)
    return {"user": _user_row(user), "csrf_token": csrf}


@router.post("/auth/login")
def auth_login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    _enabled()
    try:
        user, token, csrf = auth.login(db, payload.username, payload.password)
    except auth.AuthError as exc:
        auth.audit(db, "login", "denied", username=payload.username[:64], code=exc.code)
        db.commit()
        raise
    auth.audit(db, "login", "allowed", user)
    db.commit()
    _set_cookies(response, token, csrf)
    return {"user": _user_row(user), "csrf_token": csrf}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def auth_logout(request: Request, db: Session = Depends(get_db)):
    found = auth.session_user(db, request.cookies.get(auth.SESSION_COOKIE))
    if found is not None:
        user, sess = found
        sess.revoked_at = auth.utcnow()
        auth.audit(db, "logout", "allowed", user)
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    response.delete_cookie(auth.CSRF_COOKIE, path="/")
    return response


@router.get("/auth/me")
def auth_me(request: Request):
    user = current_user(request)
    return {"enabled": get_settings().auth_enabled, "user": _user_row(user) if user else None}


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def auth_password(payload: PasswordIn, request: Request, db: Session = Depends(get_db)):
    _enabled()
    user = db.get(User, current_user(request).id)
    auth.change_password(db, user, payload.current, payload.new)
    auth.audit(db, "password_change", "allowed", user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [_user_row(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserIn, request: Request, db: Session = Depends(get_db)):
    _enabled()
    user = auth.create_user(db, payload.username, payload.password, payload.role, payload.display_name)
    auth.audit(db, "user_create", "allowed", current_user(request), target=user.username, role=user.role)
    db.commit()
    return _user_row(user)


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: UserPatch, request: Request, db: Session = Depends(get_db)):
    _enabled()
    user = db.get(User, user_id)
    if user is None:
        raise auth.AuthError("auth_user_not_found", 404)
    auth.update_user(db, user, payload.role, payload.is_active, payload.display_name, payload.password)
    changed = sorted(k for k, v in payload.model_dump(exclude_unset=True).items() if k != "password" or v)
    auth.audit(db, "user_update", "allowed", current_user(request), target=user.username, fields=changed)
    db.commit()
    return _user_row(user)


@router.get("/projects/{project_id}/shares")
def project_shares(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    owner = db.get(User, project.owner_id) if project.owner_id else None
    rows = db.execute(select(ProjectShare, User).join(User, User.id == ProjectShare.user_id)
                      .where(ProjectShare.project_id == project.id).order_by(User.username)).all()
    return {"owner": _user_row(owner) if owner else None,
            "shares": [{"user": _user_row(u), "access": s.access} for s, u in rows]}


@router.put("/projects/{project_id}/shares")
def share_project(project_id: str, payload: ShareIn, request: Request, db: Session = Depends(get_db)):
    """Give an account read or write access to the project, or remove it (access null). Only the owner or an
    administrator may share."""
    _enabled()
    project = project_or_404(db, project_id)
    me = current_user(request)
    if me.role != "admin" and project.owner_id != me.id:
        raise auth.AuthError("auth_share_owner_only", 403)
    target = db.get(User, payload.user_id)
    if target is None:
        raise auth.AuthError("auth_user_not_found", 404)
    auth.set_share(db, project, target, payload.access)
    auth.audit(db, "share", "allowed", me, project_id=project.id, target=target.username, access=payload.access)
    db.commit()
    return project_shares(project_id, db)


@router.get("/audit")
def audit_log(limit: int = Query(default=200, ge=1, le=2000), action: str | None = Query(None, max_length=40),
              db: Session = Depends(get_db)):
    q = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
    if action:
        q = q.where(AuditEvent.action == action)
    names = dict(db.execute(select(Project.id, Project.name)).all())
    return [{"id": e.id, "at": e.at, "username": e.username, "action": e.action, "outcome": e.outcome,
             "method": e.method, "route": e.route, "project_id": e.project_id,
             "project_name": names.get(e.project_id), "detail": e.detail} for e in db.scalars(q)]


@router.get("/auth/directory")
def user_directory(db: Session = Depends(get_db)):
    """Active accounts (name only), to pick whom to share a project with."""
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role}
            for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))]
