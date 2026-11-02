"""phylo_tree_views: the rooting and Tree Explorer display chosen for each phylogeny result (phylogeny results are
comparison_results rows with analysis "phylogeny")

Revision ID: e8b4f2a6c3d1
Revises: d7a3e5c1f9b2
Create Date: 2026-11-02 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4f2a6c3d1"
down_revision: str | Sequence[str] | None = "d7a3e5c1f9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phylo_tree_views",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("rooting", sa.JSON(), nullable=False),
        sa.Column("style", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["comparison_results.id"], name="fk_phylo_tree_views_result_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_phylo_tree_views"),
        sa.UniqueConstraint("result_id", name="uq_phylo_tree_views_result_id"),
    )


def downgrade() -> None:
    # The trees stay (comparison_results); only the chosen rooting and display would be lost. Refuse while rows exist.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM phylo_tree_views"))
    if count:
        raise RuntimeError(f"{count} row(s) exist in phylo_tree_views. Remove them first ('DELETE FROM "
                           "phylo_tree_views') if you accept losing the saved rootings and tree displays.")
    op.drop_table("phylo_tree_views")
