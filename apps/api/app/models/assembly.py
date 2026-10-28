import datetime as dt
import enum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class AssemblyMode(str, enum.Enum):
    long = "long"
    short = "short"
    hybrid = "hybrid"


class Assembly(Base):
    """A genome assembly written by one analysis job.

    Its files stay under the job's results/ folder and are never registered as RawFile reads.
    `input_file_ids` is the lineage: the exact imported or derived read files the assembler used.
    `stats` holds arva_core.assembly_stats output without the per-contig rows, which are in
    `contigs` (bounded; `stats.contig_rows` says whether rows were left out). `warnings` are
    labelled heuristics (arva_core.assembly_stats.assembly_warnings).
    """

    __tablename__ = "assemblies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_assemblies_sample_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_assemblies_job_id"),
        nullable=False, unique=True,
    )
    assembler: Mapped[str] = mapped_column(String(100), nullable=False)
    assembler_version: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[AssemblyMode] = mapped_column(Enum(AssemblyMode, native_enum=False), nullable=False)
    # The assembler's read-type setting, e.g. Flye's "nano-hq".
    read_type: Mapped[str] = mapped_column(String(50), nullable=False)
    input_file_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    contigs_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    graph_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    info_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False)
    contigs: Mapped[list] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
