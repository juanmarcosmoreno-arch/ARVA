import datetime as dt
import enum

from sqlalchemy import JSON, BigInteger, DateTime, Enum, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class DatabaseStatus(str, enum.Enum):
    installed = "installed"
    registered = "registered"
    downloading = "downloading"
    verifying = "verifying"
    failed = "failed"
    cancelled = "cancelled"


class DatabaseOrigin(str, enum.Enum):
    # Downloaded and extracted by ARVA into ARVA_DB_DIR: ARVA owns (and may delete) the folder.
    download = "download"
    # An existing folder registered by the user: ARVA only reads it and never deletes it.
    register = "register"


class ReferenceDatabase(TimestampMixin, Base):
    """One reference database ARVA knows on this computer, installed by the Database Manager or registered."""

    __tablename__ = "reference_databases"
    __table_args__ = (UniqueConstraint("path", name="uq_reference_databases_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # The catalogue entry (e.g. "bakta-light"); the version below may differ from the catalogue's for a registered folder.
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    licence: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # SHA-256 over ARVA's manifest of the folder (every file's path, size and SHA-256), "sha256:<hex>".
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The publisher's checksum of the downloaded archive, verified before extraction ("md5:<hex>"); None if registered.
    archive_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[DatabaseStatus] = mapped_column(Enum(DatabaseStatus, native_enum=False, length=20), nullable=False)
    origin: Mapped[DatabaseOrigin] = mapped_column(Enum(DatabaseOrigin, native_enum=False, length=20), nullable=False)
    installed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The tool's own version file, the catalogue facts used, the archive, and the file manifest.
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {code, params} of error_message for the expected failures, so the interface can show it translated.
    error_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cancel_requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The task-queue id of the current download or verification.
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
