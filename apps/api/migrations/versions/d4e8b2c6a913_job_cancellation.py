"""job cancellation: status 'cancelled', analysis_jobs.cancel_requested_at and analysis_jobs.checkpoint (a stopped
Flye run's work folder kept for --resume)

Revision ID: d4e8b2c6a913
Revises: c3d9a1f7e5b2
Create Date: 2026-10-28 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8b2c6a913"
down_revision: str | Sequence[str] | None = "c3d9a1f7e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The status column is VARCHAR(9) without a CHECK constraint (native_enum=False), so 'cancelled' fits as is.
    op.add_column("analysis_jobs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("analysis_jobs", sa.Column("checkpoint", sa.JSON(), nullable=True))


def downgrade() -> None:
    # The previous schema knows neither status: refuse rather than relabel cancelled jobs or forget kept folders.
    bind = op.get_bind()
    cancelled = bind.scalar(sa.text("SELECT count(*) FROM analysis_jobs WHERE status = 'cancelled'"))
    kept = bind.scalar(sa.text("SELECT count(*) FROM analysis_jobs WHERE checkpoint IS NOT NULL"))
    if cancelled or kept:
        raise RuntimeError(
            f"{cancelled} cancelled job(s) and {kept} kept Flye work folder(s) exist. Discard the work folders in ARVA "
            "(or delete storage/checkpoints/), then run \"UPDATE analysis_jobs SET status = 'failed', checkpoint = "
            "NULL WHERE status = 'cancelled' OR checkpoint IS NOT NULL\" if you accept recording cancelled jobs as "
            "failed."
        )
    op.drop_column("analysis_jobs", "checkpoint")
    op.drop_column("analysis_jobs", "cancel_requested_at")
