"""assemblies.declared_assembler, assemblies.declared_assembler_version: the assembler and version the user states for a
genome FASTA registered as a draft assembled outside ARVA from the sample's reads (only such drafts may be polished)

Revision ID: b8e4d2a6f1c3
Revises: e2c7a9f4b6d1
Create Date: 2026-11-04 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4d2a6f1c3"
down_revision: str | Sequence[str] | None = "e2c7a9f4b6d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assemblies", sa.Column("declared_assembler", sa.String(length=100), nullable=True))
    op.add_column("assemblies", sa.Column("declared_assembler_version", sa.String(length=100), nullable=True))


def downgrade() -> None:
    # Dropping the columns would silently turn a declared draft (and its polished versions' lineage) into a plain
    # imported genome; the user's statement would be lost.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM assemblies WHERE declared_assembler IS NOT NULL")).scalar()
    if count:
        raise RuntimeError(f"{count} registered draft assembly record(s) hold the assembler the user declared; delete "
                           "them before downgrading")
    op.drop_column("assemblies", "declared_assembler_version")
    op.drop_column("assemblies", "declared_assembler")
