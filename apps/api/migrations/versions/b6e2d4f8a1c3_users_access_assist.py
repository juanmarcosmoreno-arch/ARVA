"""users, user_sessions, project_shares, audit_events, assist_requests and projects.owner_id: optional
authentication with roles and project sharing, the access audit log and the ARVA Assist request log

Revision ID: b6e2d4f8a1c3
Revises: a7d2c5e9b1f4
Create Date: 2026-11-02 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e2d4f8a1c3"
down_revision: str | Sequence[str] | None = "a7d2c5e9b1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("assist_requests", "audit_events", "project_shares", "user_sessions", "users")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("csrf_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_sessions_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.UniqueConstraint("token_sha256", name="uq_user_sessions_token_sha256"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "project_shares",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("access", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_project_shares_project_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_project_shares_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_project_shares"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_shares_project_id_user_id"),
    )
    op.create_index("ix_project_shares_project_id", "project_shares", ["project_id"])
    op.create_index("ix_project_shares_user_id", "project_shares", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("route", sa.String(length=300), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_at", "audit_events", ["at"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])
    op.create_table(
        "assist_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("endpoint_host", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sent", sa.JSON(), nullable=False),
        sa.Column("sent_sha256", sa.String(length=64), nullable=False),
        sa.Column("included_sequences", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_assist_requests"),
    )
    op.create_index("ix_assist_requests_at", "assist_requests", ["at"])
    op.add_column("projects", sa.Column("owner_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_projects_owner_id", "projects", "users", ["owner_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    counts = {t: bind.scalar(sa.text(f"SELECT count(*) FROM {t}")) for t in TABLES}
    if any(counts.values()):
        found = ", ".join(f"{n} in {t}" for t, n in counts.items() if n)
        raise RuntimeError(f"Rows exist ({found}). Remove them first if you accept losing the accounts, their "
                           "project sharing, the access audit log and the ARVA Assist request log.")
    op.drop_constraint("fk_projects_owner_id", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
    op.drop_index("ix_assist_requests_at", table_name="assist_requests")
    op.drop_table("assist_requests")
    op.drop_index("ix_audit_events_project_id", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_project_shares_user_id", table_name="project_shares")
    op.drop_index("ix_project_shares_project_id", table_name="project_shares")
    op.drop_table("project_shares")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("users")
