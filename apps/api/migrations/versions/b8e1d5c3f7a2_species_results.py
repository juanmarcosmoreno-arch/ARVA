"""species_results: species identification of assemblies (FastANI, skani, Mash, sylph, GTDB-Tk) with the ranked hits,
ARVA's interpretation and its consistency checks

Revision ID: b8e1d5c3f7a2
Revises: a4c7e2f9b3d1
Create Date: 2026-10-29 23:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e1d5c3f7a2"
down_revision: str | Sequence[str] | None = "a4c7e2f9b3d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "species_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.String(length=100), nullable=False),
        sa.Column("database_kind", sa.String(length=50), nullable=True),
        sa.Column("database_name", sa.String(length=255), nullable=True),
        sa.Column("database_version", sa.String(length=100), nullable=True),
        sa.Column("database_checksum", sa.String(length=255), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("species", sa.String(length=255), nullable=True),
        sa.Column("hits", sa.JSON(), nullable=False),
        sa.Column("interpretation", sa.JSON(), nullable=False),
        sa.Column("consistency", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_species_results_sample_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name="fk_species_results_assembly_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_species_results_job_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_species_results"),
        sa.UniqueConstraint("job_id", name="uq_species_results_job_id"),
    )
    op.create_index("ix_species_results_sample_id", "species_results", ["sample_id"])
    op.create_index("ix_species_results_assembly_id", "species_results", ["assembly_id"])
    op.create_index("ix_species_results_species", "species_results", ["species"])


def downgrade() -> None:
    # Dropping the table would forget identifications whose files stay in results/; refuse instead.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM species_results"))
    if count:
        raise RuntimeError(f"{count} species identification result(s) exist. Remove them first "
                           "('DELETE FROM species_results') if you accept losing their records.")
    op.drop_index("ix_species_results_species", table_name="species_results")
    op.drop_index("ix_species_results_assembly_id", table_name="species_results")
    op.drop_index("ix_species_results_sample_id", table_name="species_results")
    op.drop_table("species_results")
