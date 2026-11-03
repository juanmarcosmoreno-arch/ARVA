"""Optional accounts: Argon2id password hashes (argon2-cffi, its RFC 9106 low-memory defaults), server-side sessions
held by an HttpOnly cookie, a CSRF token per session (double submit: cookie + X-CSRF-Token header, compared with the
stored hash), lockout after repeated failed sign-ins, project access by ownership and sharing, and the audit log.

The first administrator is created with a one-time setup token that ARVA writes to <storage>/secrets/ (owner-only)
while authentication is on and no account exists: only someone who can read the server's files can claim it."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.models import AuditEvent, Project, ProjectShare, User, UserSession
from app.models.auth import ROLES, SHARE_ACCESS

SESSION_COOKIE = "arva_session"
CSRF_COOKIE = "arva_csrf"
CSRF_HEADER = "x-csrf-token"
SETUP_TOKEN_FILE = "auth-setup-token"
USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
MIN_PASSWORD = 12
MAX_PASSWORD = 1024

_hasher = PasswordHasher()
# A hash of a random password, verified when the username does not exist so that both cases take as long.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class AuthError(Exception):
    def __init__(self, code: str, status: int = 400, **params: Any):
        super().__init__(code)
        self.code, self.status, self.params = code, status, params


MESSAGES = {
    "auth_password_too_short": "The password needs at least {minimum} characters.",
    "auth_password_too_long": "The password can have at most {maximum} characters.",
    "auth_username_invalid": "User names have 3 to 64 letters, digits, dots, hyphens or underscores.",
    "auth_role_invalid": "The role must be admin, analyst or viewer.",
    "auth_username_taken": "That user name is already in use.",
    "auth_setup_done": "An account already exists; sign in instead.",
    "auth_setup_token_invalid": "The setup token is not the one ARVA wrote to its secrets folder.",
    "auth_last_admin": "At least one active administrator must remain.",
    "auth_password_wrong": "The current password is not correct.",
    "auth_invalid_credentials": "Wrong user name or password.",
    "auth_locked": "Too many failed sign-ins. Try again in {seconds} seconds.",
    "auth_share_access_invalid": "Access must be read or write.",
    "auth_disabled": "Authentication is off: ARVA runs for one local user.",
    "auth_user_not_found": "No such account.",
    "auth_share_owner_only": "Only the project's owner or an administrator can share it.",
    "auth_project_owner_only": "Only the project's owner or an administrator can rename or delete it.",
}


def message(exc: AuthError) -> str:
    return MESSAGES[exc.code].format(**exc.params)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hash_password(password: str) -> str:
    check_password(password)
    return _hasher.hash(password)


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError("auth_password_too_short", minimum=MIN_PASSWORD)
    if len(password) > MAX_PASSWORD:
        raise AuthError("auth_password_too_long", maximum=MAX_PASSWORD)


def check_username(username: str) -> str:
    if not USERNAME.match(username):
        raise AuthError("auth_username_invalid")
    return username


def check_role(role: str) -> str:
    if role not in ROLES:
        raise AuthError("auth_role_invalid")
    return role


# --- First administrator --------------------------------------------------------------------------------------------

def user_count(db: Session) -> int:
    return db.scalar(select(func.count(User.id))) or 0


def _setup_path() -> Path:
    return get_settings().secrets_dir / SETUP_TOKEN_FILE


def ensure_secrets_dir() -> Path:
    d = get_settings().secrets_dir
    d.mkdir(mode=0o700, parents=False, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def setup_token() -> str:
    """The pending setup token, created on first use."""
    ensure_secrets_dir()
    path = _setup_path()
    if path.is_file():
        return path.read_text().strip()
    token = secrets.token_urlsafe(24)
    write_private(path, token + "\n")
    return token


def setup_first_admin(db: Session, token: str, username: str, password: str, display_name: str | None) -> User:
    if user_count(db):
        raise AuthError("auth_setup_done", 409)
    if not hmac.compare_digest(token.strip(), setup_token()):
        raise AuthError("auth_setup_token_invalid", 403)
    user = create_user(db, username, password, "admin", display_name)
    _setup_path().unlink(missing_ok=True)
    return user


# --- Accounts -------------------------------------------------------------------------------------------------------

def create_user(db: Session, username: str, password: str, role: str, display_name: str | None) -> User:
    check_username(username)
    check_role(role)
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise AuthError("auth_username_taken", 409)
    user = User(username=username, role=role, display_name=display_name, password_hash=hash_password(password),
                is_active=True, failed_logins=0)
    db.add(user)
    db.flush()
    return user


def active_admins(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0


def update_user(db: Session, user: User, role: str | None, is_active: bool | None, display_name: str | None,
                password: str | None) -> None:
    demoted = (role is not None and role != "admin") or is_active is False
    if user.role == "admin" and user.is_active and demoted and active_admins(db) <= 1:
        raise AuthError("auth_last_admin", 409)
    if role is not None:
        user.role = check_role(role)
    if display_name is not None:
        user.display_name = display_name or None
    if password is not None:
        user.password_hash = hash_password(password)
        user.failed_logins, user.locked_until = 0, None
    if is_active is not None:
        user.is_active = is_active
    if is_active is False or password is not None or role is not None:
        revoke_sessions(db, user.id)


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not _verify(user.password_hash, current):
        raise AuthError("auth_password_wrong", 403)
    user.password_hash = hash_password(new)
    revoke_sessions(db, user.id)


def _verify(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# --- Sessions -------------------------------------------------------------------------------------------------------

def login(db: Session, username: str, password: str) -> tuple[User, str, str]:
    """(user, session token, CSRF token). Wrong name or password both answer auth_invalid_credentials; an account
    with too many recent failures is refused until its lockout ends, even with the right password."""
    s = get_settings()
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    now = utcnow()
    if user is None:
        _verify(_DUMMY_HASH, password)
        raise AuthError("auth_invalid_credentials", 401)
    if user.locked_until is not None and user.locked_until > now:
        raise AuthError("auth_locked", 429, seconds=int((user.locked_until - now).total_seconds()) + 1)
    if not _verify(user.password_hash, password) or not user.is_active:
        user.failed_logins += 1
        if user.failed_logins >= s.login_max_failures:
            user.locked_until = now + dt.timedelta(seconds=s.login_lockout_seconds)
            user.failed_logins = 0
        raise AuthError("auth_invalid_credentials", 401)
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_sha256=sha256(token), csrf_sha256=sha256(csrf), created_at=now,
                       expires_at=now + dt.timedelta(hours=s.session_hours)))
    return user, token, csrf


def session_user(db: Session, token: str | None) -> tuple[User, UserSession] | None:
    if not token or len(token) > 200:
        return None
    sess = db.scalar(select(UserSession).where(UserSession.token_sha256 == sha256(token)))
    if sess is None or sess.revoked_at is not None or sess.expires_at <= utcnow():
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    return user, sess


def csrf_ok(sess: UserSession, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sha256(header), sess.csrf_sha256)


def revoke_sessions(db: Session, user_id: str) -> None:
    now = utcnow()
    for sess in db.scalars(select(UserSession).where(UserSession.user_id == user_id,
                                                     UserSession.revoked_at.is_(None))):
        sess.revoked_at = now


# --- Project access -------------------------------------------------------------------------------------------------

def access(db: Session, user: User, project: Project) -> str | None:
    """'write', 'read' or None. Admins write everywhere; an owner writes; a share grants its access; a viewer never
    writes, whatever the share says."""
    if user.role == "admin":
        return "write"
    level = None
    if project.owner_id == user.id:
        level = "write"
    else:
        share = db.scalar(select(ProjectShare).where(ProjectShare.project_id == project.id,
                                                     ProjectShare.user_id == user.id))
        level = share.access if share else None
    if level == "write" and user.role == "viewer":
        return "read"
    return level


def visible_project_ids(db: Session, user: User) -> set[str] | None:
    """None: every project (an administrator)."""
    if user.role == "admin":
        return None
    owned = set(db.scalars(select(Project.id).where(Project.owner_id == user.id)))
    shared = set(db.scalars(select(ProjectShare.project_id).where(ProjectShare.user_id == user.id)))
    return owned | shared


def set_share(db: Session, project: Project, user: User, level: str | None) -> None:
    if level is not None and level not in SHARE_ACCESS:
        raise AuthError("auth_share_access_invalid")
    share = db.scalar(select(ProjectShare).where(ProjectShare.project_id == project.id,
                                                 ProjectShare.user_id == user.id))
    if level is None:
        if share is not None:
            db.delete(share)
        return
    if share is None:
        db.add(ProjectShare(project_id=project.id, user_id=user.id, access=level))
    else:
        share.access = level


# --- Audit ----------------------------------------------------------------------------------------------------------

def audit(db: Session, action: str, outcome: str, user: User | None = None, *, username: str | None = None,
          method: str | None = None, route: str | None = None, project_id: str | None = None,
          **detail: Any) -> None:
    db.add(AuditEvent(user_id=user.id if user else None, username=user.username if user else username,
                      action=action, outcome=outcome, method=method, route=route, project_id=project_id,
                      detail=detail, at=utcnow()))
