"""mobile_element_results and virulence_results: what the plasmid and mobile-element searches (MOB-suite,
PlasmidFinder through ABRicate, ISEScan, IntegronFinder, geNomad) and ABRicate's VFDB screen reported for an assembly,
one row per contig call, plasmid, replicon, element or virulence-gene hit

Revision ID: f5a8c3d1b7e9
Revises: e4b7c9a2d6f8
Create Date: 2026-10-29 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a8c3d1b7e9"
down_revision: str | Sequence[str] | None = "e4b7c9a2d6f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _keys(table: str) -> list[sa.Column | sa.Constraint]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name=f"fk_{table}_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name=f"fk_{table}_assembly_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name=f"fk_{table}_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
    ]


def upgrade() -> None:
    op.create_table(
        "mobile_element_results",
        *_keys("mobile_element_results"),
        sa.Column("tool", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("element", sa.String(length=255), nullable=True),
        sa.Column("element_type", sa.String(length=255), nullable=True),
        sa.Column("contig", sa.String(length=255), nullable=True),
        sa.Column("start", sa.Integer(), nullable=True),
        sa.Column("end", sa.Integer(), nullable=True),
        sa.Column("strand", sa.String(length=1), nullable=True),
        sa.Column("identity", sa.Float(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("completeness", sa.String(length=40), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("feature", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("sample_id", "assembly_id", "job_id", "category"):
        op.create_index(f"ix_mobile_element_results_{col}", "mobile_element_results", [col])
    op.create_table(
        "virulence_results",
        *_keys("virulence_results"),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("gene", sa.String(length=255), nullable=False),
        sa.Column("contig", sa.String(length=255), nullable=True),
        sa.Column("start", sa.Integer(), nullable=True),
        sa.Column("end", sa.Integer(), nullable=True),
        sa.Column("strand", sa.String(length=1), nullable=True),
        sa.Column("identity", sa.Float(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("ref_start", sa.Integer(), nullable=True),
        sa.Column("ref_end", sa.Integer(), nullable=True),
        sa.Column("ref_length", sa.Integer(), nullable=True),
        sa.Column("gap_openings", sa.Integer(), nullable=True),
        sa.Column("gap_positions", sa.Integer(), nullable=True),
        sa.Column("coverage_map", sa.String(length=40), nullable=True),
        sa.Column("accession", sa.String(length=255), nullable=True),
        sa.Column("product", sa.String(length=2000), nullable=True),
        sa.Column("vf_name", sa.String(length=500), nullable=True),
        sa.Column("vf_id", sa.String(length=20), nullable=True),
        sa.Column("vf_category", sa.String(length=255), nullable=True),
        sa.Column("vfc_id", sa.String(length=20), nullable=True),
        sa.Column("organism", sa.String(length=500), nullable=True),
        sa.Column("hit_kind", sa.String(length=20), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=True),
        sa.Column("feature", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("sample_id", "assembly_id", "job_id", "gene"):
        op.create_index(f"ix_virulence_results_{col}", "virulence_results", [col])


def downgrade() -> None:
    # Dropping the tables would forget results whose files stay in results/; refuse instead.
    bind = op.get_bind()
    for table in ("mobile_element_results", "virulence_results"):
        count = bind.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        if count:
            raise RuntimeError(f"{count} row(s) exist in {table}. Remove them first ('DELETE FROM {table}') if you "
                               "accept losing their records.")
    for col in ("gene", "job_id", "assembly_id", "sample_id"):
        op.drop_index(f"ix_virulence_results_{col}", table_name="virulence_results")
    op.drop_table("virulence_results")
    for col in ("category", "job_id", "assembly_id", "sample_id"):
        op.drop_index(f"ix_mobile_element_results_{col}", table_name="mobile_element_results")
    op.drop_table("mobile_element_results")
