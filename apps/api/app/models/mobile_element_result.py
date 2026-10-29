import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class MobileElementResult(Base):
    """One row a mobile-element search reported for an assembly in one mobile_elements job, as the tool wrote it.

    `tool` is mobsuite, plasmidfinder (ABRicate's PlasmidFinder database), isescan, integronfinder or genomad;
    `category` what the row describes: a contig's MOB-suite call (contig), a plasmid MOB-suite reconstructed and
    typed (plasmid), a repetitive element MOB-suite found (mge), a replicon (replicon), an insertion sequence
    (insertion_sequence), an integron (integron), or geNomad's plasmid, virus or provirus calls. `element` is the
    tool's name for it and `element_type` its type (molecule type, replicon family, IS family, integron type, ...);
    `completeness` the tool's own completeness where it states one (or ARVA's reading of a partial hit). `contig` is
    the assembly's contig name. `details` keeps every column of the tool's row. `feature` links the row to an
    annotated feature where one overlaps it. A contig MOB-suite calls 'chromosome' was not assigned to a plasmid; it is
    not proven to be a chromosome.
    """

    __tablename__ = "mobile_element_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_mobile_element_results_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_mobile_element_results_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_mobile_element_results_job_id"),
        nullable=False, index=True,
    )
    tool: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    element: Mapped[str | None] = mapped_column(String(255), nullable=True)
    element_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contig: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strand: Mapped[str | None] = mapped_column(String(1), nullable=True)
    identity: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness: Mapped[str | None] = mapped_column(String(40), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feature: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
