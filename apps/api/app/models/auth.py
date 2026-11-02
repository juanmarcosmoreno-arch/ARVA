import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid, utcnow

ROLES = ("admin", "analyst", "viewer")
SHARE_ACCESS = ("read", "write")


class User(TimestampMixin, Base):
    """An account, used only when authentication is on (ARVA_AUTH_ENABLED). `password_hash` is an Argon2id hash
    (argon2-cffi); the password itself is never stored."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 is stored, with the CSRF token's."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE", name="fk_user_sessions_user_id"), nullable=False,
        index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectShare(Base):
    __tablename__ = "project_shares"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_shares_project_id_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_shares_project_id"),
        nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE", name="fk_project_shares_user_id"), nullable=False,
        index=True)
    access: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    """Who did what: sign-ins, account and sharing changes, refused requests, every change request and report
    download while authentication is on. No request bodies or values are kept, only the route's template."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    route: Mapped[str | None] = mapped_column(String(300), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AssistRequest(Base):
    """One question sent to the configured ARVA Assist provider: exactly what was sent (the context and the
    question), whether sequences were included (only with the user's consent for that request), the provider and
    endpoint host, and the answer or the failure."""

    __tablename__ = "assist_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sent: Mapped[dict] = mapped_column(JSON, nullable=False)
    sent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    included_sequences: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
