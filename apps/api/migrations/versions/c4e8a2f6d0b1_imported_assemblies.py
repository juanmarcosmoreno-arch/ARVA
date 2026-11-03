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
    # Deleting imported genomes would cascade to their annotations, typing, AMR and comparison memberships: refuse.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM assemblies WHERE mode = 'imported'"))
    if count:
        raise RuntimeError(f"{count} imported assemblies exist. Remove them first (DELETE FROM assemblies WHERE "
                           "mode = 'imported') if you accept losing them and every result computed on them "
                           "(annotations, typing, AMR, mobile elements, comparison memberships); their files stay.")
    op.alter_column("assemblies", "mode", type_=sa.String(length=6), existing_type=sa.String(length=8),
                    existing_nullable=False)
