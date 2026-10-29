"""Database kinds: reference_databases.kind, version_source, is_default (one default per kind), verification_level,
and the manifest and a collection's genome inventory in their own columns; each job records the database's kind,
how its version was known and its path

Revision ID: d9f2b4a6c8e1
Revises: c3e9a5d7f1b4
Create Date: 2026-10-29 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f2b4a6c8e1"
down_revision: str | Sequence[str] | None = "c3e9a5d7f1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND = "CASE WHEN {col} IN ('bakta-light', 'bakta-full') THEN 'bakta' ELSE {col} END"


def upgrade() -> None:
    op.add_column("reference_databases", sa.Column("kind", sa.String(length=50), nullable=True))
    op.execute(f"UPDATE reference_databases SET kind = {_KIND.format(col='key')}")
    op.alter_column("reference_databases", "kind", nullable=False)
    op.create_index("ix_reference_databases_kind", "reference_databases", ["kind"])
    op.add_column("reference_databases", sa.Column("version_source", sa.String(length=20), nullable=True))
    # Until now only Bakta databases existed, their version read from version.json.
    op.execute("UPDATE reference_databases SET version_source = 'file' WHERE version IS NOT NULL")
    op.add_column("reference_databases", sa.Column("is_default", sa.Boolean(), nullable=False,
                                                   server_default=sa.false()))
    op.execute("UPDATE reference_databases SET is_default = true WHERE id IN (SELECT DISTINCT ON (kind) id FROM "
               "reference_databases WHERE status IN ('installed', 'registered') ORDER BY kind, verified_at DESC NULLS "
               "LAST, created_at DESC)")
    op.create_index("uq_reference_databases_default_kind", "reference_databases", ["kind"], unique=True,
                    postgresql_where=sa.text("is_default"))
    op.add_column("reference_databases", sa.Column("verification_level", sa.String(length=10), nullable=True))
    op.execute("UPDATE reference_databases SET verification_level = 'full' WHERE checksum IS NOT NULL")
    op.add_column("reference_databases", sa.Column("manifest", sa.JSON(), nullable=True))
    op.add_column("reference_databases", sa.Column("inventory", sa.JSON(), nullable=True))
    op.execute("UPDATE reference_databases SET manifest = (details::jsonb -> 'manifest')::json, details = "
               "((details::jsonb - 'manifest') || jsonb_build_object('file_count', "
               "jsonb_array_length(details::jsonb -> 'manifest')))::json "
               "WHERE details IS NOT NULL AND jsonb_typeof(details::jsonb -> 'manifest') = 'array'")

    op.add_column("analysis_jobs", sa.Column("database_kind", sa.String(length=50), nullable=True))
    op.add_column("analysis_jobs", sa.Column("database_version_source", sa.String(length=20), nullable=True))
    op.add_column("analysis_jobs", sa.Column("database_path", sa.String(length=1024), nullable=True))
    op.execute(f"UPDATE analysis_jobs SET database_kind = {_KIND.format(col='database_key')}, "
               "database_version_source = 'file' WHERE database_key IS NOT NULL")
    op.execute("UPDATE analysis_jobs j SET database_path = r.path FROM reference_databases r "
               "WHERE j.reference_database_id = r.id")


def downgrade() -> None:
    bind = op.get_bind()
    new = bind.scalar(sa.text("SELECT count(*) FROM reference_databases WHERE origin = 'extract' OR status = "
                              "'extracting'"))
    if new:
        raise RuntimeError(f"{new} reference database record(s) are copies ARVA extracted from an archive, which the "
                           "previous schema cannot describe. Delete them in ARVA first.")
    op.drop_column("analysis_jobs", "database_path")
    op.drop_column("analysis_jobs", "database_version_source")
    op.drop_column("analysis_jobs", "database_kind")
    op.execute("UPDATE reference_databases SET details = ((COALESCE(details::jsonb, '{}'::jsonb) - 'file_count') || "
               "jsonb_build_object('manifest', manifest::jsonb))::json WHERE manifest IS NOT NULL")
    op.drop_column("reference_databases", "inventory")
    op.drop_column("reference_databases", "manifest")
    op.drop_column("reference_databases", "verification_level")
    op.drop_index("uq_reference_databases_default_kind", table_name="reference_databases")
    op.drop_column("reference_databases", "is_default")
    op.drop_column("reference_databases", "version_source")
    op.drop_index("ix_reference_databases_kind", table_name="reference_databases")
    op.drop_column("reference_databases", "kind")
