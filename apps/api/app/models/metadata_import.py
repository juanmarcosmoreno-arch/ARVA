import datetime as dt
import enum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class MetadataFileKind(str, enum.Enum):
    csv = "csv"
    xlsx = "xlsx"


class MetadataImportMode(str, enum.Enum):
    create_and_update = "create_and_update"
    create_only = "create_only"


class MetadataImport(Base):
    """Provenance of one applied sample-metadata table: which file, read how, mapped how, and what changed."""

    __tablename__ = "metadata_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_metadata_imports_project_id"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[MetadataFileKind] = mapped_column(Enum(MetadataFileKind, native_enum=False), nullable=False)
    sheet: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encoding: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delimiter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    header_row: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping: Mapped[dict] = mapped_column(JSON, nullable=False)
    date_order: Mapped[str | None] = mapped_column(String(3), nullable=True)
    mode: Mapped[MetadataImportMode] = mapped_column(Enum(MetadataImportMode, native_enum=False), nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
