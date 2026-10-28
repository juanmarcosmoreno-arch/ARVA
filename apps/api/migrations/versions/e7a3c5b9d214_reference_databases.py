"""reference_databases: databases installed or registered by the Database Manager, and the database each analysis
job used (analysis_jobs.database_key, database_checksum, reference_database_id)

Revision ID: e7a3c5b9d214
Revises: d4e8b2c6a913
Create Date: 2026-10-28 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a3c5b9d214"
down_revision: str | Sequence[str] | None = "d4e8b2c6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("installed", "registered", "downloading", "verifying", "failed", "cancelled")


def upgrade() -> None:
    op.create_table(
        "reference_databases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("licence", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("archive_checksum", sa.String(length=255), nullable=True),
        sa.Column("status", sa.Enum(*_STATUSES, name="databasestatus", native_enum=False, length=20), nullable=False),
        sa.Column("origin", sa.Enum("download", "register", name="databaseorigin", native_enum=False, length=20),
                  nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_reference_databases"),
        sa.UniqueConstraint("path", name="uq_reference_databases_path"),
    )
    op.create_index("ix_reference_databases_key", "reference_databases", ["key"])
    op.add_column("analysis_jobs", sa.Column("database_key", sa.String(length=100), nullable=True))
    op.add_column("analysis_jobs", sa.Column("database_checksum", sa.String(length=255), nullable=True))
    op.add_column("analysis_jobs", sa.Column("reference_database_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_analysis_jobs_reference_database_id", "analysis_jobs", "reference_databases",
                          ["reference_database_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    # Dropping would forget installed databases (their folders stay on disk) and which database each job used.
    bind = op.get_bind()
    databases = bind.scalar(sa.text("SELECT count(*) FROM reference_databases"))
    used = bind.scalar(sa.text("SELECT count(*) FROM analysis_jobs WHERE database_key IS NOT NULL"))
    if databases or used:
        raise RuntimeError(
            f"{databases} reference database record(s) and {used} job(s) that used a database exist. Delete the "
            "databases in ARVA first; the jobs' database records cannot be kept by the previous schema."
        )
    op.drop_constraint("fk_analysis_jobs_reference_database_id", "analysis_jobs", type_="foreignkey")
    op.drop_column("analysis_jobs", "reference_database_id")
    op.drop_column("analysis_jobs", "database_checksum")
    op.drop_column("analysis_jobs", "database_key")
    op.drop_index("ix_reference_databases_key", table_name="reference_databases")
    op.drop_table("reference_databases")
