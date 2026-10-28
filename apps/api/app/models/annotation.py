import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class Annotation(Base):
    """A genome annotation of one assembly written by one analysis job (Bakta or Prokka).

    The features are not rows here: they are in `features_path`, one JSON object per line (arva_core.annotation),
    under the job's results/ folder next to the annotator's own files (`files`: kind → path, SHA-256, size). A
    bacterial genome has a few thousand features that never change after the run; the API filters them in memory,
    which is fast at that size and keeps tens of thousands of rows per annotation out of the database.
    `steps` says for every workflow step whether it ran, was skipped (and why) or failed; `summary` holds ARVA's
    counts and coding density and the annotator's own statistics. The database is copied by key, name, version and
    content checksum so the record survives the database's deletion.
    """

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_annotations_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_annotations_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_annotations_job_id"),
        nullable=False, unique=True,
    )
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    database_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    database_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    database_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    steps: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    # The annotated sequences: the annotator's name, the assembly's contig name, length (and Bakta's topology/type).
    sequences: Mapped[list] = mapped_column(JSON, nullable=False)
    files: Mapped[dict] = mapped_column(JSON, nullable=False)
    features_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
