"""read-header metadata summarised from the first records of each raw file

Revision ID: 720d1519b821
Revises: ae8a0e145c1b
Create Date: 2026-10-28 00:30:02.203206

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "720d1519b821"
down_revision: str | Sequence[str] | None = "ae8a0e145c1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_files", sa.Column("header_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_files", "header_metadata")
