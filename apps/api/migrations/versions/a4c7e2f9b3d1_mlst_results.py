"""mlst_results: MLST calls of assemblies (mlst), with each locus's call, the clonal complex from the scheme and
ARVA's warnings; reference_databases.origin gains "bundled" (a non-native enum, so no schema change)

Revision ID: a4c7e2f9b3d1
Revises: d9f2b4a6c8e1
Create Date: 2026-10-29 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c7e2f9b3d1"
down_revision: str | Sequence[str] | None = "d9f2b4a6c8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mlst_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.String(length=100), nullable=False),
        sa.Column("database_key", sa.String(length=100), nullable=True),
        sa.Column("database_name", sa.String(length=255), nullable=True),
        sa.Column("database_version", sa.String(length=100), nullable=True),
        sa.Column("database_checksum", sa.String(length=255), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("scheme", sa.String(length=100), nullable=True),
        sa.Column("st", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("alleles", sa.JSON(), nullable=False),
        sa.Column("clonal_complex", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_mlst_results_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name="fk_mlst_results_assembly_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_mlst_results_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_mlst_results"),
        sa.UniqueConstraint("job_id", name="uq_mlst_results_job_id"),
    )
    op.create_index("ix_mlst_results_sample_id", "mlst_results", ["sample_id"])
    op.create_index("ix_mlst_results_assembly_id", "mlst_results", ["assembly_id"])
    op.create_index("ix_mlst_results_scheme", "mlst_results", ["scheme"])


def downgrade() -> None:
    # Dropping the table would forget MLST calls whose files stay in results/, and older code does not know a
    # bundled database; refuse instead.
    bind = op.get_bind()
    count = bind.scalar(sa.text("SELECT count(*) FROM mlst_results"))
    bundled = bind.scalar(sa.text("SELECT count(*) FROM reference_databases WHERE origin = 'bundled'"))
    if count or bundled:
        raise RuntimeError(f"{count} MLST result(s) and {bundled} bundled database record(s) exist. Remove them first "
                           "('DELETE FROM mlst_results', 'DELETE FROM reference_databases WHERE origin = ''bundled''') "
                           "if you accept losing their records.")
    op.drop_index("ix_mlst_results_scheme", table_name="mlst_results")
    op.drop_index("ix_mlst_results_assembly_id", table_name="mlst_results")
    op.drop_index("ix_mlst_results_sample_id", table_name="mlst_results")
    op.drop_table("mlst_results")
