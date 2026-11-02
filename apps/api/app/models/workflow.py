import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid, utcnow


class Workflow(TimestampMixin, Base):
    """A named workflow (a graph of analyses, arva_core.workflow). Its definition lives in numbered versions; saving
    a change adds a version and never rewrites one, so every run keeps pointing at the graph it ran."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The predefined workflow it started from, if any.
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duplicated_from_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="SET NULL", name="fk_workflows_duplicated_from_id"),
        nullable=True)
    versions: Mapped[list["WorkflowVersion"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowVersion.version")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_id_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE", name="fk_workflow_versions_workflow_id"),
        nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    # SHA-256 of arva_core.workflow.canonical(definition): equal for graphs that compute the same thing.
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    workflow: Mapped[Workflow] = relationship(back_populates="versions")


class BatchRun(TimestampMixin, Base):
    """One run of a workflow version over samples of a project (a batch). Its items are the node-by-sample units;
    every item that runs a tool becomes one ordinary analysis job. `definition` and `tools` are snapshots taken when
    the run was created; `settings` holds the queue settings (priority, concurrency, threads and memory per job,
    retries). A branch (`parent_run_id`) reuses the outputs of its parent's unchanged nodes and runs the rest again
    as new jobs, so earlier results are never overwritten."""

    __tablename__ = "batch_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE", name="fk_batch_runs_project_id"),
        nullable=False, index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_versions.id", ondelete="SET NULL", name="fk_batch_runs_workflow_version_id"),
        nullable=True, index=True)
    parent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("batch_runs.id", ondelete="SET NULL", name="fk_batch_runs_parent_run_id"),
        nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # queued (waiting for its turn), running, paused, completed, completed_with_errors, cancelled
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tools: Mapped[dict] = mapped_column(JSON, nullable=False)
    sample_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    # The changed parameters of a branch, by node: [{node, path, before, after}].
    branch_changes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list["BatchItem"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="BatchItem.seq")


class BatchItem(Base):
    """One node of a run for one sample (sample-scope nodes) or for the whole run (set-scope nodes, sample_id
    None). `job_id` is the current job; `job_ids` every attempt. `reused_from_item_id` marks an item of a branch
    that took its parent's output instead of running."""

    __tablename__ = "batch_items"
    __table_args__ = (UniqueConstraint("run_id", "node_id", "sample_key", name="uq_batch_items_run_id_node_sample"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("batch_runs.id", ondelete="CASCADE", name="fk_batch_items_run_id"),
        nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_batch_items_sample_id"), nullable=True,
        index=True)
    # sample_id, or "_set" for a set-scope item (so the unique constraint covers both).
    sample_key: Mapped[str] = mapped_column(String(36), nullable=False)
    # waiting, queued, running, completed, failed, cancelled, skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    depends_on: Mapped[list] = mapped_column(JSON, nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="SET NULL", name="fk_batch_items_job_id"), nullable=True,
        index=True)
    job_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {code, params, message} of the reason the item failed or was skipped.
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The threads and memory ARVA reserved for it in the queue (an estimate, not a measurement).
    reserved: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reused_from_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("batch_items.id", ondelete="SET NULL", name="fk_batch_items_reused_from_item_id"),
        nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run: Mapped[BatchRun] = relationship(back_populates="items")
