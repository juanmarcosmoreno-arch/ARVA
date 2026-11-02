"""gene_queries: saved query sequences of Custom Gene Investigation (Region Explorer and gene investigation results
are comparison_results rows with analysis "region" / "gene")

Revision ID: d7a3e5c1f9b2
Revises: c4e7a2d9f1b3
Create Date: 2026-11-02 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3e5c1f9b2"
down_revision: str | Sequence[str] | None = "c4e7a2d9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gene_queries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("molecule", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Text(), nullable=False),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_gene_queries"),
        sa.UniqueConstraint("molecule", "sha256", name="uq_gene_queries_molecule_sha256"),
    )


def downgrade() -> None:
    # Investigations keep a copy of their query, but the saved library would be lost; refuse while it has rows.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM gene_queries"))
    if count:
        raise RuntimeError(f"{count} row(s) exist in gene_queries. Remove them first ('DELETE FROM gene_queries') if "
                           "you accept losing the saved queries.")
    op.drop_table("gene_queries")
