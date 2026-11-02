"""workflows, workflow_versions, batch_runs, batch_items: the Workflow Builder's versioned definitions and the batch
queue that runs them as ordinary analysis jobs

Revision ID: a7d2c5e9b1f4
Revises: f3c9a1e7b5d2
Create Date: 2026-11-02 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2c5e9b1f4"
down_revision: str | Sequence[str] | None = "f3c9a1e7b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("batch_items", "batch_runs", "workflow_versions", "workflows")


def _times() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("template_key", sa.String(length=64), nullable=True),
        sa.Column("duplicated_from_id", sa.String(length=36), nullable=True),
        *_times(),
        sa.ForeignKeyConstraint(["duplicated_from_id"], ["workflows.id"], name="fk_workflows_duplicated_from_id",
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_workflows"),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], name="fk_workflow_versions_workflow_id",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_versions"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_id_version"),
    )
    op.create_index("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"])
    op.create_table(
        "batch_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=True),
        sa.Column("parent_run_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("sample_ids", sa.JSON(), nullable=False),
        sa.Column("branch_changes", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_times(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_batch_runs_project_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"],
                                name="fk_batch_runs_workflow_version_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_run_id"], ["batch_runs.id"], name="fk_batch_runs_parent_run_id",
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_batch_runs"),
    )
    op.create_index("ix_batch_runs_project_id", "batch_runs", ["project_id"])
    op.create_index("ix_batch_runs_workflow_version_id", "batch_runs", ["workflow_version_id"])
    op.create_table(
        "batch_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_kind", sa.String(length=64), nullable=False),
        sa.Column("sample_id", sa.String(length=36), nullable=True),
        sa.Column("sample_key", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("job_ids", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("reserved", sa.JSON(), nullable=True),
        sa.Column("reused_from_item_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["batch_runs.id"], name="fk_batch_items_run_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_batch_items_sample_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], name="fk_batch_items_job_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reused_from_item_id"], ["batch_items.id"],
                                name="fk_batch_items_reused_from_item_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_batch_items"),
        sa.UniqueConstraint("run_id", "node_id", "sample_key", name="uq_batch_items_run_id_node_sample"),
    )
    op.create_index("ix_batch_items_run_id", "batch_items", ["run_id"])
    op.create_index("ix_batch_items_sample_id", "batch_items", ["sample_id"])
    op.create_index("ix_batch_items_job_id", "batch_items", ["job_id"])


def downgrade() -> None:
    bind = op.get_bind()
    counts = {t: bind.scalar(sa.text(f"SELECT count(*) FROM {t}")) for t in TABLES}
    if any(counts.values()):
        found = ", ".join(f"{n} in {t}" for t, n in counts.items() if n)
        raise RuntimeError(f"Rows exist ({found}). Remove them first ('DELETE FROM batch_runs; DELETE FROM "
                           "workflows') if you accept losing the workflow definitions and the records of their runs "
                           "(the analysis jobs and their results stay).")
    op.drop_index("ix_batch_items_job_id", table_name="batch_items")
    op.drop_index("ix_batch_items_sample_id", table_name="batch_items")
    op.drop_index("ix_batch_items_run_id", table_name="batch_items")
    op.drop_table("batch_items")
    op.drop_index("ix_batch_runs_workflow_version_id", table_name="batch_runs")
    op.drop_index("ix_batch_runs_project_id", table_name="batch_runs")
    op.drop_table("batch_runs")
    op.drop_index("ix_workflow_versions_workflow_id", table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
