"""project-level analysis jobs: analysis_jobs.project_id, sample_id optional

Revision ID: f790c1a68c7b
Revises: ee0125d444ac
Create Date: 2026-10-28 09:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f790c1a68c7b"
down_revision: str | Sequence[str] | None = "ee0125d444ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("project_id", sa.String(length=36), nullable=True))
    op.execute(
        "UPDATE analysis_jobs SET project_id = samples.project_id "
        "FROM samples WHERE samples.id = analysis_jobs.sample_id"
    )
    op.alter_column("analysis_jobs", "project_id", existing_type=sa.String(length=36), nullable=False)
    op.create_foreign_key(
        "fk_analysis_jobs_project_id", "analysis_jobs", "projects", ["project_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_analysis_jobs_project_id", "analysis_jobs", ["project_id"])
    op.alter_column("analysis_jobs", "sample_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    # The old schema cannot represent project-level jobs; refuse rather than delete provenance records.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM analysis_jobs WHERE sample_id IS NULL"))
    if count:
        raise RuntimeError(
            f"{count} project-level analysis job(s) exist (e.g. MultiQC reports). Remove them first with "
            "'DELETE FROM analysis_jobs WHERE sample_id IS NULL' if you accept losing their records."
        )
    op.alter_column("analysis_jobs", "sample_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_index("ix_analysis_jobs_project_id", table_name="analysis_jobs")
    op.drop_constraint("fk_analysis_jobs_project_id", "analysis_jobs", type_="foreignkey")
    op.drop_column("analysis_jobs", "project_id")
