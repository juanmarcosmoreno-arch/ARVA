"""job progress: analysis_jobs.progress, live monitoring of long tool runs (e.g. Flye stages)

Revision ID: b5c2e81f4a97
Revises: 2084b616df6a
Create Date: 2026-10-28 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5c2e81f4a97"
down_revision: str | Sequence[str] | None = "2084b616df6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("progress", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Progress only describes a run while it happens; the job's log, parameters and outputs keep the record.
    op.drop_column("analysis_jobs", "progress")
