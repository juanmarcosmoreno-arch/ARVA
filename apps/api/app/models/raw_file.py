import datetime as dt
import enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_uuid, utcnow

if TYPE_CHECKING:
    from app.models.sample import Sample


class FileFormat(str, enum.Enum):
    fastq = "fastq"
    fastq_gz = "fastq_gz"
    fasta = "fasta"
    fasta_gz = "fasta_gz"
    # Raw nanopore signal, recognised by content; it holds no reads, so read-level analyses never use it.
    pod5 = "pod5"
    unknown = "unknown"


class FileOrigin(str, enum.Enum):
    imported = "imported"
    derived = "derived"


class RawFile(Base):
    """An immutable sequence file registered against a sample.

    `imported` files are the user's originals. `derived` files (e.g. filtered
    reads) are written by an analysis job and link back to their parent file
    and producing job, forming the lineage raw → processing → derived file.
    No file content is ever modified after it is stored.
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
    # {code, params} of validation_message, so the interface can show it translated.
    validation_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    origin: Mapped[FileOrigin] = mapped_column(
        Enum(FileOrigin, native_enum=False), default=FileOrigin.imported,
        server_default=FileOrigin.imported.value, nullable=False,
    )
    parent_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("raw_files.id", ondelete="SET NULL"), nullable=True
    )
    produced_by_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # arva_core.header_meta.summarise() of the first read headers; a suggestion, never user metadata.
    header_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sample: Mapped["Sample"] = relationship("Sample", back_populates="raw_files")
