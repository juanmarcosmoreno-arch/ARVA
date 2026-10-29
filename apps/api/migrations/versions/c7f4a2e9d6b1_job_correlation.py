"""analysis_jobs.correlation_id: the API request (or parent job) a job came from, linking error log entries

Revision ID: c7f4a2e9d6b1
Revises: b8e1d5c3f7a2
Create Date: 2026-10-29 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7f4a2e9d6b1"
down_revision: str | Sequence[str] | None = "b8e1d5c3f7a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("correlation_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_jobs", "correlation_id")
