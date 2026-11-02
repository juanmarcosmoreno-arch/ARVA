"""comparison_sets, comparison_members, comparison_results: comparative genomics (named sets of assemblies from any
project, ANI matrices and whole-genome alignments)

Revision ID: c4e7a2d9f1b3
Revises: b8d3f1a6c2e4
Create Date: 2026-11-02 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e7a2d9f1b3"
down_revision: str | Sequence[str] | None = "b8d3f1a6c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comparison_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_comparison_sets_project_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_comparison_sets"),
    )
    op.create_index("ix_comparison_sets_project_id", "comparison_sets", ["project_id"])
    op.create_table(
        "comparison_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("set_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["comparison_sets.id"], name="fk_comparison_members_set_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name="fk_comparison_members_assembly_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_comparison_members"),
        sa.UniqueConstraint("set_id", "assembly_id", name="uq_comparison_members_set_id_assembly_id"),
    )
    op.create_index("ix_comparison_members_set_id", "comparison_members", ["set_id"])
    op.create_index("ix_comparison_members_assembly_id", "comparison_members", ["assembly_id"])
    op.create_table(
        "comparison_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("set_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("analysis", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.String(length=100), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("genomes", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["comparison_sets.id"], name="fk_comparison_results_set_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_comparison_results_job_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_comparison_results"),
        sa.UniqueConstraint("job_id", name="uq_comparison_results_job_id"),
    )
    op.create_index("ix_comparison_results_set_id", "comparison_results", ["set_id"])


def downgrade() -> None:
    # Dropping the tables would forget comparison sets and results whose files stay in results/; refuse instead.
    bind = op.get_bind()
    for table in ("comparison_results", "comparison_sets"):
        count = bind.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        if count:
            raise RuntimeError(f"{count} row(s) exist in {table}. Remove them first ('DELETE FROM {table}') if you "
                               "accept losing their records.")
    op.drop_index("ix_comparison_results_set_id", table_name="comparison_results")
    op.drop_table("comparison_results")
    op.drop_index("ix_comparison_members_assembly_id", table_name="comparison_members")
    op.drop_index("ix_comparison_members_set_id", table_name="comparison_members")
    op.drop_table("comparison_members")
    op.drop_index("ix_comparison_sets_project_id", table_name="comparison_sets")
    op.drop_table("comparison_sets")
