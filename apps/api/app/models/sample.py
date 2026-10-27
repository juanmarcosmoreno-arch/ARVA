import datetime as dt
import enum

from sqlalchemy import JSON, Date, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class SequencingTechnology(str, enum.Enum):
    illumina = "illumina"
    nanopore = "nanopore"
    pacbio = "pacbio"
    hybrid = "hybrid"
    unknown = "unknown"


class Sample(TimestampMixin, Base):
    __tablename__ = "samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    sample_code: Mapped[str] = mapped_column(String(255), nullable=False)
    organism: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_species: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sample_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geographic_origin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collection_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    sequencing_technology: Mapped[SequencingTechnology] = mapped_column(
        Enum(SequencingTechnology, native_enum=False), default=SequencingTechnology.unknown
    )
    sequencing_run: Mapped[str | None] = mapped_column(String(255), nullable=True)
    researcher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="samples")
    raw_files: Mapped[list["RawFile"]] = relationship(
        "RawFile", back_populates="sample", cascade="all, delete-orphan"
    )
    analysis_jobs: Mapped[list["AnalysisJob"]] = relationship(
        "AnalysisJob", back_populates="sample", cascade="all, delete-orphan"
    )
