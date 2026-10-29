"""amr_results: the genes, point mutations, stress and virulence genes AMRFinderPlus reported for an assembly, one
row per element, with the method, identity, coverage, coordinates and the linked annotation feature

Revision ID: e4b7c9a2d6f8
Revises: c7f4a2e9d6b1
Create Date: 2026-10-29 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c9a2d6f8"
down_revision: str | Sequence[str] | None = "c7f4a2e9d6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "amr_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=True),
        sa.Column("element_symbol", sa.String(length=255), nullable=False),
        sa.Column("element_name", sa.String(length=1000), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("subtype", sa.String(length=40), nullable=True),
        sa.Column("amr_class", sa.String(length=255), nullable=True),
        sa.Column("amr_subclass", sa.String(length=1000), nullable=True),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("method_kind", sa.String(length=20), nullable=False),
        sa.Column("identity", sa.Float(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("target_length", sa.Integer(), nullable=True),
        sa.Column("reference_length", sa.Integer(), nullable=True),
        sa.Column("alignment_length", sa.Integer(), nullable=True),
        sa.Column("contig", sa.String(length=255), nullable=True),
        sa.Column("assembly_contig", sa.String(length=255), nullable=True),
        sa.Column("start", sa.Integer(), nullable=True),
        sa.Column("stop", sa.Integer(), nullable=True),
        sa.Column("strand", sa.String(length=1), nullable=True),
        sa.Column("protein_id", sa.String(length=255), nullable=True),
        sa.Column("closest_accession", sa.String(length=255), nullable=True),
        sa.Column("closest_name", sa.String(length=1000), nullable=True),
        sa.Column("hmm_accession", sa.String(length=100), nullable=True),
        sa.Column("hmm_description", sa.String(length=1000), nullable=True),
        sa.Column("hierarchy_node", sa.String(length=255), nullable=True),
        sa.Column("feature", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_amr_results_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name="fk_amr_results_assembly_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_amr_results_job_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"], name="fk_amr_results_annotation_id",
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_amr_results"),
    )
    op.create_index("ix_amr_results_sample_id", "amr_results", ["sample_id"])
    op.create_index("ix_amr_results_assembly_id", "amr_results", ["assembly_id"])
    op.create_index("ix_amr_results_job_id", "amr_results", ["job_id"])
    op.create_index("ix_amr_results_element_symbol", "amr_results", ["element_symbol"])


def downgrade() -> None:
    # Dropping the table would forget AMR results whose files stay in results/; refuse instead.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM amr_results"))
    if count:
        raise RuntimeError(f"{count} AMR result row(s) exist. Remove them first ('DELETE FROM amr_results') if you "
                           "accept losing their records.")
    op.drop_index("ix_amr_results_element_symbol", table_name="amr_results")
    op.drop_index("ix_amr_results_job_id", table_name="amr_results")
    op.drop_index("ix_amr_results_assembly_id", table_name="amr_results")
    op.drop_index("ix_amr_results_sample_id", table_name="amr_results")
    op.drop_table("amr_results")
