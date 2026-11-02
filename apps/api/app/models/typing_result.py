import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class TypingResult(Base):
    """One call of a species-specific typing step (app.services.typing_modules) on one assembly, by one job.

    `module` is the typing module (staphylococcus_aureus) and `method` its step (sccmec, spa, agr). `status` is ARVA's
    reading of the tool's call (typed, type_only, new_repeat_succession, low_confidence, multiple, not_typeable, ...)
    and `call` the determined value (an SCCmec type or subtype, a spa type, an agr group), None whenever the tool did
    not determine one. `details` keeps the tool's own values (targets, regions, repeats, k-mer score, frameshifts, the
    operon's alignment); `applicability` the species evidence when the job was started and any override the user
    confirmed. The database (or the files bundled with the tool) is recorded by kind, name, version and checksum.
    """

    __tablename__ = "typing_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_typing_results_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_typing_results_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_typing_results_job_id"),
        nullable=False, unique=True,
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    database_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    database_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    database_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    call: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    applicability: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    files: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
