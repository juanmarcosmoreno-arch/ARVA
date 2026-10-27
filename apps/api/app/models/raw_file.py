import datetime as dt
import enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_uuid, utcnow


class FileFormat(str, enum.Enum):
    fastq = "fastq"
    fastq_gz = "fastq_gz"
    fasta = "fasta"
    fasta_gz = "fasta_gz"
    unknown = "unknown"


class RawFile(Base):
    """An immutable raw sequencing/reference file registered against a sample.

    The original file content is never modified once stored; downstream
    processing always reads from this file and writes derived artifacts
    elsewhere (see AnalysisJob / QCResult).
    """

    __tablename__ = "raw_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE"), nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_format: Mapped[FileFormat] = mapped_column(
        Enum(FileFormat, native_enum=False), default=FileFormat.unknown, nullable=False
    )
    read_mate: Mapped[str | None] = mapped_column(String(10), nullable=True)  # R1 / R2 / None

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    sample: Mapped["Sample"] = relationship("Sample", back_populates="raw_files")
