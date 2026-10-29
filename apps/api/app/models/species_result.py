import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class SpeciesResult(Base):
    """The species identification of one assembly by one job: the method's ranked hits against one database, ARVA's
    interpretation of them, and its consistency checks with MLST and the annotation's organism.

    `method` is fastani, skani, mash, sylph or gtdbtk. `hits` keeps the best hits (each with the reference's accession,
    organism, strain and type-material flag from the collection, and the method's values: ANI, aligned fraction,
    fragments, Mash distance, containment). `status` is ARVA's reading (same_species, ambiguous, below_boundary,
    no_hits, screening_only) and `species` is set only for same_species; `interpretation` holds the thresholds and
    their sources, the reasons and the caveats. `consistency` compares the species with the MLST scheme and the
    organism given for an annotation, as found when the job ran.
    """

    __tablename__ = "species_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_species_results_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_species_results_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_species_results_job_id"),
        nullable=False, unique=True,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    database_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    database_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    database_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    species: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    hits: Mapped[list] = mapped_column(JSON, nullable=False)
    interpretation: Mapped[dict] = mapped_column(JSON, nullable=False)
    consistency: Mapped[list] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    files: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
