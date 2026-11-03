"""assemblies.mode accepts "imported": a finished genome FASTA registered by the user (e.g. an NCBI RefSeq genome)

Revision ID: c4e8a2f6d0b1
Revises: b6e2d4f8a1c3
Create Date: 2026-11-02 23:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f6d0b1"
down_revision: str | Sequence[str] | None = "b6e2d4f8a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("assemblies", "mode", type_=sa.String(length=8), existing_type=sa.String(length=6),
                    existing_nullable=False)


def downgrade() -> None:
    op.execute("DELETE FROM assemblies WHERE mode = 'imported'")
    op.alter_column("assemblies", "mode", type_=sa.String(length=6), existing_type=sa.String(length=8),
                    existing_nullable=False)
