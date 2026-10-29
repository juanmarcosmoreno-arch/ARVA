"""Stable codes next to English messages shown in the interface, so it can show them in the user's language:
analysis_jobs.error_detail, raw_files.validation_detail and reference_databases.error_detail ({code, params})

Revision ID: c3e9a5d7f1b4
Revises: b8d3f1a7c5e2
Create Date: 2026-10-29 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e9a5d7f1b4"
down_revision: str | Sequence[str] | None = "b8d3f1a7c5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (("analysis_jobs", "error_detail"), ("raw_files", "validation_detail"), ("reference_databases", "error_detail"))


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.JSON(), nullable=True))


def downgrade() -> None:
    # Only the codes go: the English messages they translate stay in error_message and validation_message.
    for table, column in _COLUMNS:
        op.drop_column(table, column)
