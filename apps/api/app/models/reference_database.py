import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class DatabaseStatus(str, enum.Enum):
    installed = "installed"
    registered = "registered"
    downloading = "downloading"
    # A copy being extracted from an archive the user has (e.g. an NCBI Datasets package zip).
    extracting = "extracting"
    verifying = "verifying"
    failed = "failed"
    cancelled = "cancelled"


class DatabaseOrigin(str, enum.Enum):
    # Downloaded and extracted by ARVA into ARVA_DB_DIR: ARVA owns (and may delete) the folder.
    download = "download"
    # An existing folder registered by the user: ARVA only reads it and never deletes it.
    register = "register"
    # A copy ARVA extracted from an archive the user has, into a database folder: ARVA owns (and may delete) the copy,
    # never the archive.
    extract = "extract"
    # Shipped inside a tool's own package (mlst's PubMLST schemes): ARVA reads it in place and never changes,
    # updates or deletes it.
    bundled = "bundled"


class VersionSource(str, enum.Enum):
    # Read from the database's own files (e.g. Bakta's version.json).
    file = "file"
    # Declared by the user because the files do not state it.
    declared = "declared"
    # Identified by the full checksum matching a checksum the tool publishes per version (CheckM2).
    checksum = "checksum"
    # Recorded by ARVA when it downloaded the data from a source that publishes no version (the download date, e.g.
    # a reference collection built from NCBI Datasets).
    download = "download"


def _kind_of_key(context) -> str:
    key = context.get_current_parameters()["key"]
    return "bakta" if key in ("bakta-light", "bakta-full") else key


class ReferenceDatabase(TimestampMixin, Base):
    """One reference database ARVA knows on this computer, installed by the Database Manager or registered."""

    __tablename__ = "reference_databases"
    __table_args__ = (
        UniqueConstraint("path", name="uq_reference_databases_path"),
        Index("uq_reference_databases_default_kind", "kind", unique=True, postgresql_where=text("is_default")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # The catalogue entry (e.g. "bakta-light") or, for a kind ARVA cannot download, the kind; the version below may
    # differ from the catalogue's for a registered folder.
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # The database kind (database_kinds.py), e.g. "bakta" for bakta-light and bakta-full.
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default=_kind_of_key)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version_source: Mapped[VersionSource | None] = mapped_column(
        Enum(VersionSource, native_enum=False, length=20), nullable=True)
    # The folder, or the file for single-file kinds (a sylph database, a FastANI reference list).
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # The one database of its kind analyses use when none is chosen.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # quick: the kind's files, sizes and version file were checked; full: plus the SHA-256 of every file.
    verification_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    # The detection (kind, version file, files checked), the catalogue facts used and the archive.
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Path, size and SHA-256 of every file, from the full verification (loaded only when asked for).
    manifest: Mapped[list | None] = deferred(mapped_column(JSON, nullable=True))
    # A reference collection's genomes: accession, organism, species, strain, type material, path, size.
    inventory: Mapped[list | None] = deferred(mapped_column(JSON, nullable=True))
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {code, params} of error_message for the expected failures, so the interface can show it translated.
    error_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cancel_requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The task-queue id of the current download or verification.
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
