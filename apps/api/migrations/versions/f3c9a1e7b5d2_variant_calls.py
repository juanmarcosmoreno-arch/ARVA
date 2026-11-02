"""variant_calls: variant-calling runs of a sample's reads against a reference (bcftools), with the reference's
snapshot; the variant records stay in each run's results file

Revision ID: f3c9a1e7b5d2
Revises: e8b4f2a6c3d1
Create Date: 2026-11-02 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c9a1e7b5d2"
down_revision: str | Sequence[str] | None = "e8b4f2a6c3d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "variant_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("reference_assembly_id", sa.String(length=36), nullable=True),
        sa.Column("reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.JSON(), nullable=False),
        sa.Column("technology", sa.String(length=20), nullable=False),
        sa.Column("aligner", sa.String(length=100), nullable=False),
        sa.Column("aligner_version", sa.String(length=100), nullable=False),
        sa.Column("caller_version", sa.String(length=100), nullable=False),
        sa.Column("reads", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_variant_calls_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_variant_calls_job_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_assembly_id"], ["assemblies.id"],
                                name="fk_variant_calls_reference_assembly_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_variant_calls"),
        sa.UniqueConstraint("job_id", name="uq_variant_calls_job_id"),
    )
    op.create_index("ix_variant_calls_sample_id", "variant_calls", ["sample_id"])
    op.create_index("ix_variant_calls_reference_assembly_id", "variant_calls", ["reference_assembly_id"])
    op.create_index("ix_variant_calls_reference_sha256", "variant_calls", ["reference_sha256"])


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM variant_calls"))
    if count:
        raise RuntimeError(f"{count} row(s) exist in variant_calls. Remove them first ('DELETE FROM variant_calls') "
                           "if you accept losing the records of these variant-calling runs (their files stay).")
    op.drop_index("ix_variant_calls_reference_sha256", table_name="variant_calls")
    op.drop_index("ix_variant_calls_reference_assembly_id", table_name="variant_calls")
    op.drop_index("ix_variant_calls_sample_id", table_name="variant_calls")
    op.drop_table("variant_calls")
