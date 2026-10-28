"""assemblies: genome assemblies written by analysis jobs, with contig statistics and heuristic warnings

Revision ID: 2084b616df6a
Revises: f790c1a68c7b
Create Date: 2026-10-28 13:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2084b616df6a"
down_revision: str | Sequence[str] | None = "f790c1a68c7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assemblies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("assembler", sa.String(length=100), nullable=False),
        sa.Column("assembler_version", sa.String(length=100), nullable=False),
        sa.Column("mode", sa.Enum("long", "short", "hybrid", name="assemblymode", native_enum=False), nullable=False),
        sa.Column("read_type", sa.String(length=50), nullable=False),
        sa.Column("input_file_ids", sa.JSON(), nullable=False),
        sa.Column("contigs_path", sa.String(length=1024), nullable=False),
        sa.Column("graph_path", sa.String(length=1024), nullable=True),
        sa.Column("info_path", sa.String(length=1024), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("contigs", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_assemblies_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_assemblies_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_assemblies"),
        sa.UniqueConstraint("job_id", name="uq_assemblies_job_id"),
    )
    op.create_index("ix_assemblies_sample_id", "assemblies", ["sample_id"])


def downgrade() -> None:
    # Dropping the table would delete the records of assemblies whose files stay in results/; refuse instead.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM assemblies"))
    if count:
        raise RuntimeError(
            f"{count} assembly record(s) exist. Remove them first with 'DELETE FROM assemblies' "
            "if you accept losing their records."
        )
    op.drop_index("ix_assemblies_sample_id", table_name="assemblies")
    op.drop_table("assemblies")
