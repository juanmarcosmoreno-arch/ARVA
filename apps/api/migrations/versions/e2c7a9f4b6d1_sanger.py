"""sanger_reads, sanger_identifications, sanger_search_results: Sanger reads of one gene under a sample, the
identification asked of one or two of them (trimming, consensus with its evidence, suspicion) and the hits of each
search

Revision ID: e2c7a9f4b6d1
Revises: c4e8a2f6d0b1
Create Date: 2026-11-03 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2c7a9f4b6d1"
down_revision: str | Sequence[str] | None = "c4e8a2f6d0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "sanger_reads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("direction_source", sa.String(length=10), nullable=False),
        sa.Column("pair_key", sa.String(length=255), nullable=True),
        sa.Column("primer", sa.String(length=50), nullable=True),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("has_qualities", sa.Boolean(), nullable=False),
        sa.Column("has_trace", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_sanger_reads_sample_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_sanger_reads"),
        sa.UniqueConstraint("sample_id", "sha256", "record_index", name="uq_sanger_reads_sample_id_sha256_record_index"),
    )
    op.create_index("ix_sanger_reads_sample_id", "sanger_reads", ["sample_id"])
    op.create_table(
        "sanger_identifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("forward_read_id", sa.String(length=36), nullable=True),
        sa.Column("reverse_read_id", sa.String(length=36), nullable=True),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("sequence", sa.Text(), nullable=False),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("consensus", sa.JSON(), nullable=False),
        sa.Column("suspected", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_sanger_identifications_sample_id",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["forward_read_id"], ["sanger_reads.id"],
                                name="fk_sanger_identifications_forward_read_id"),
        sa.ForeignKeyConstraint(["reverse_read_id"], ["sanger_reads.id"],
                                name="fk_sanger_identifications_reverse_read_id"),
        sa.PrimaryKeyConstraint("id", name="pk_sanger_identifications"),
    )
    for col in ("sample_id", "forward_read_id", "reverse_read_id"):
        op.create_index(f"ix_sanger_identifications_{col}", "sanger_identifications", [col])
    op.create_table(
        "sanger_search_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identification_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["identification_id"], ["sanger_identifications.id"],
                                name="fk_sanger_search_results_identification_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_sanger_search_results_job_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_sanger_search_results"),
        sa.UniqueConstraint("job_id", name="uq_sanger_search_results_job_id"),
    )
    op.create_index("ix_sanger_search_results_identification_id", "sanger_search_results", ["identification_id"])


def downgrade() -> None:
    # The original files stay in raw/, but the reads' directions and pairs, the consensus evidence and the search
    # results would be lost: refuse while there are any.
    bind = op.get_bind()
    counts = {t: bind.scalar(sa.text(f"SELECT count(*) FROM {t}"))
              for t in ("sanger_reads", "sanger_identifications", "sanger_search_results")}
    if any(counts.values()):
        listed = ", ".join(f"{n} in {t}" for t, n in counts.items() if n)
        raise RuntimeError(f"Sanger data exist ({listed}). Remove them first (DELETE FROM sanger_search_results; "
                           "DELETE FROM sanger_identifications; DELETE FROM sanger_reads) if you accept losing them; "
                           "the uploaded files stay in raw/.")
    op.drop_index("ix_sanger_search_results_identification_id", table_name="sanger_search_results")
    op.drop_table("sanger_search_results")
    for col in ("sample_id", "forward_read_id", "reverse_read_id"):
        op.drop_index(f"ix_sanger_identifications_{col}", table_name="sanger_identifications")
    op.drop_table("sanger_identifications")
    op.drop_index("ix_sanger_reads_sample_id", table_name="sanger_reads")
    op.drop_table("sanger_reads")
