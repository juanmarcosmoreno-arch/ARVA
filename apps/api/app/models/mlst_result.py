import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class MlstResult(Base):
    """The MLST call of one assembly by one mlst job, as mlst reported it.

    `scheme` and `st` are None when mlst reported "-" (no scheme reached the minimum score; or no ST for the
    allele combination). `alleles` keeps every locus in the scheme's order with mlst's call and its type (exact,
    novel, partial, missing, multiple, null). `clonal_complex` is read from the scheme's profile file, which not
    every scheme has. `warnings` are ARVA's coded warnings; `details` the facts from mlst's log (tied schemes, other
    schemes with exact allele matches, the BLAST command), the novel alleles and the scheme's own dates.
    """

    __tablename__ = "mlst_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_mlst_results_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_mlst_results_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_mlst_results_job_id"),
        nullable=False, unique=True,
    )
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    database_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    database_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    database_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    scheme: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    st: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    alleles: Mapped[list] = mapped_column(JSON, nullable=False)
    clonal_complex: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    files: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
