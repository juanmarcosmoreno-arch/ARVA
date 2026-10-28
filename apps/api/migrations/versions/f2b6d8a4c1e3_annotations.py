"""annotations: genome annotations of assemblies (Bakta, Prokka), their steps, summary and files

Revision ID: f2b6d8a4c1e3
Revises: e7a3c5b9d214
Create Date: 2026-10-28 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b6d8a4c1e3"
down_revision: str | Sequence[str] | None = "e7a3c5b9d214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotations",
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
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("sequences", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("features_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_annotations_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name="fk_annotations_assembly_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_annotations_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_annotations"),
        sa.UniqueConstraint("job_id", name="uq_annotations_job_id"),
    )
    op.create_index("ix_annotations_sample_id", "annotations", ["sample_id"])
    op.create_index("ix_annotations_assembly_id", "annotations", ["assembly_id"])


def downgrade() -> None:
    # Dropping the table would forget annotations whose files stay in results/; refuse instead.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM annotations"))
    if count:
        raise RuntimeError(f"{count} annotation record(s) exist. Remove them first with 'DELETE FROM annotations' if "
                           "you accept losing their records.")
    op.drop_index("ix_annotations_assembly_id", table_name="annotations")
    op.drop_index("ix_annotations_sample_id", table_name="annotations")
    op.drop_table("annotations")
