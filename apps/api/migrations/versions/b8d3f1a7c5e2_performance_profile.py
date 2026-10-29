"""app_settings: settings stored server-side (the performance profile), and the resources each analysis job was given
(analysis_jobs.resources)

Revision ID: b8d3f1a7c5e2
Revises: f2b6d8a4c1e3
Create Date: 2026-10-28 23:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d3f1a7c5e2"
down_revision: str | Sequence[str] | None = "f2b6d8a4c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
    )
    op.add_column("analysis_jobs", sa.Column("resources", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Dropping would forget the saved profile and the resources recorded with each job.
    bind = op.get_bind()
    saved = bind.scalar(sa.text("SELECT count(*) FROM app_settings"))
    recorded = bind.scalar(sa.text("SELECT count(*) FROM analysis_jobs WHERE resources IS NOT NULL"))
    if saved or recorded:
        raise RuntimeError(
            f"{saved} saved setting(s) and {recorded} job(s) with recorded resources exist; the previous schema "
            "cannot keep them. Downgrade a database without them, or keep this revision."
        )
    op.drop_column("analysis_jobs", "resources")
    op.drop_table("app_settings")
