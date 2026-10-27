from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob


class QCResult(TimestampMixin, Base):
    """Structured statistics computed from a single raw file.

    `metrics` carries the full computed payload (see
    arva_core.seqstats.compute_sequence_stats); the indexed columns below
    duplicate the headline numbers for fast querying/sorting across samples.
    """

    __tablename__ = "qc_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False
    )
    raw_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_files.id", ondelete="CASCADE"), nullable=False
    )

    read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_bases: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mean_length: Mapped[float] = mapped_column(Float, nullable=False)
    n50: Mapped[int] = mapped_column(Integer, nullable=False)
    gc_percent: Mapped[float] = mapped_column(Float, nullable=False)
    mean_quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)

    analysis_job: Mapped["AnalysisJob"] = relationship("AnalysisJob", back_populates="qc_results")
