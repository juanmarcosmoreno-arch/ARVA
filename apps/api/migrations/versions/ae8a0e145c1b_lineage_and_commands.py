"""lineage of derived files, exact commands and result summaries

Revision ID: ae8a0e145c1b
Revises: a892cbfd8749
Create Date: 2026-10-27 19:17:33.113146

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ae8a0e145c1b"
down_revision: str | Sequence[str] | None = "a892cbfd8749"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("commands", sa.JSON(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("tool_path", sa.String(length=1024), nullable=True))
    op.add_column("analysis_jobs", sa.Column("result_summary", sa.JSON(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("parent_job_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_analysis_jobs_parent_job_id", "analysis_jobs", "analysis_jobs",
        ["parent_job_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(
        "raw_files",
        sa.Column(
            "origin",
            sa.Enum("imported", "derived", name="fileorigin", native_enum=False),
            server_default="imported",
            nullable=False,
        ),
    )
    op.add_column("raw_files", sa.Column("parent_file_id", sa.String(length=36), nullable=True))
    op.add_column("raw_files", sa.Column("produced_by_job_id", sa.String(length=36), nullable=True))
    op.add_column("raw_files", sa.Column("description", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_raw_files_parent_file_id", "raw_files", "raw_files",
        ["parent_file_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_raw_files_produced_by_job_id", "raw_files", "analysis_jobs",
        ["produced_by_job_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_raw_files_produced_by_job_id", "raw_files", type_="foreignkey")
    op.drop_constraint("fk_raw_files_parent_file_id", "raw_files", type_="foreignkey")
    op.drop_column("raw_files", "description")
    op.drop_column("raw_files", "produced_by_job_id")
    op.drop_column("raw_files", "parent_file_id")
    op.drop_column("raw_files", "origin")
    op.drop_constraint("fk_analysis_jobs_parent_job_id", "analysis_jobs", type_="foreignkey")
    op.drop_column("analysis_jobs", "parent_job_id")
    op.drop_column("analysis_jobs", "result_summary")
    op.drop_column("analysis_jobs", "tool_path")
    op.drop_column("analysis_jobs", "commands")
