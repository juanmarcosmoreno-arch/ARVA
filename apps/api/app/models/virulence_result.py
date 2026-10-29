import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class VirulenceResult(Base):
    """One hit ABRicate reported against its bundled VFDB for an assembly in one virulence_screen job: a nucleotide
    match to a virulence-factor gene, with identity, coverage of the reference and the reference range, never a
    virulence phenotype. `hit_kind` is ARVA's reading of the coordinates (complete, complete_gaps, partial,
    contig_end) and `pieces` the number of partial hits of the same reference (a split or interrupted gene).
    `vf_name`, `vf_id`, `vf_category` and `vfc_id` come from VFDB's sequence description. AMRFinderPlus's own
    virulence genes stay in amr_results; the two sources are shown side by side, never merged into one call.
    """

    __tablename__ = "virulence_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_virulence_results_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_virulence_results_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_virulence_results_job_id"),
        nullable=False, index=True,
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    gene: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contig: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strand: Mapped[str | None] = mapped_column(String(1), nullable=True)
    identity: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    ref_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ref_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ref_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gap_openings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gap_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_map: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accession: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    vf_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vf_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vf_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vfc_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    organism: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hit_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    pieces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
