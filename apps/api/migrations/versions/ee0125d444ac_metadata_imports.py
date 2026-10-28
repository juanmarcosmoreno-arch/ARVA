"""metadata_imports: provenance of sample metadata tables imported into a project

Revision ID: ee0125d444ac
Revises: 720d1519b821
Create Date: 2026-10-28 01:24:40.475484

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ee0125d444ac"
down_revision: str | Sequence[str] | None = "720d1519b821"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metadata_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.Enum("csv", "xlsx", name="metadatafilekind", native_enum=False), nullable=False),
        sa.Column("sheet", sa.String(length=255), nullable=True),
        sa.Column("encoding", sa.String(length=32), nullable=True),
        sa.Column("delimiter", sa.String(length=4), nullable=True),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("date_order", sa.String(length=3), nullable=True),
        sa.Column(
            "mode",
            sa.Enum("create_and_update", "create_only", name="metadataimportmode", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_metadata_imports_project_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metadata_imports"),
    )
    op.create_index("ix_metadata_imports_project_id", "metadata_imports", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_metadata_imports_project_id", table_name="metadata_imports")
    op.drop_table("metadata_imports")
