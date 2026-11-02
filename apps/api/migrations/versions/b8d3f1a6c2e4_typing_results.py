"""typing_results: the calls of species-specific typing steps (S. aureus SCCmec with sccmec, spa with spaTyper, agr
with AgrVATE), one row per job

Revision ID: b8d3f1a6c2e4
Revises: f5a8c3d1b7e9
Create Date: 2026-11-02 02:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d3f1a6c2e4"
down_revision: str | Sequence[str] | None = "f5a8c3d1b7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXED = ("sample_id", "assembly_id", "module")


def upgrade() -> None:
    op.create_table(
        "typing_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.String(length=100), nullable=False),
        sa.Column("database_kind", sa.String(length=50), nullable=True),
        sa.Column("database_name", sa.String(length=255), nullable=True),
        sa.Column("database_version", sa.String(length=100), nullable=True),
        sa.Column("database_checksum", sa.String(length=255), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("call", sa.String(length=100), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("applicability", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_typing_results_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name="fk_typing_results_assembly_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_typing_results_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_typing_results"),
        sa.UniqueConstraint("job_id", name="uq_typing_results_job_id"),
    )
    for col in INDEXED:
        op.create_index(f"ix_typing_results_{col}", "typing_results", [col])


def downgrade() -> None:
    # Dropping the table would forget typing calls whose files stay in results/; refuse instead.
    bind = op.get_bind()
    count = bind.scalar(sa.text("SELECT count(*) FROM typing_results"))
    if count:
        raise RuntimeError(f"{count} row(s) exist in typing_results. Remove them first ('DELETE FROM typing_results') "
                           "if you accept losing their records.")
    for col in reversed(INDEXED):
        op.drop_index(f"ix_typing_results_{col}", table_name="typing_results")
    op.drop_table("typing_results")
