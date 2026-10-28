import datetime as dt
import enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from app.models.qc_result import QCResult
    from app.models.sample import Sample


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class AnalysisJob(TimestampMixin, Base):
    """Scientific-integrity ledger entry for one execution of an analysis step.

    Every analysis performed by ARVA — however small — is recorded here with
    the exact tool, version, parameters and inputs used, so results are
    always traceable and reproducible (see spec section 2.1).
    """

    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_analysis_jobs_project_id"),
        nullable=False,
        index=True,
    )
    # None for project-level jobs (e.g. the MultiQC project report).
    sample_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE"), nullable=True
    )

    job_type: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "fastq_stats"
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    database_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_raw_file_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    output_paths: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.pending, nullable=False
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Exact argument vectors executed (one list per external command), so a run
    # can be reproduced outside ARVA.
    commands: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Small structured results (e.g. SeqKit rows, fastp before/after summary).
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # A job launched automatically by another job (e.g. statistics of filtered reads).
    parent_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True
    )

    sample: Mapped["Sample | None"] = relationship("Sample", back_populates="analysis_jobs")
    qc_results: Mapped[list["QCResult"]] = relationship(
        "QCResult", back_populates="analysis_job", cascade="all, delete-orphan"
    )
