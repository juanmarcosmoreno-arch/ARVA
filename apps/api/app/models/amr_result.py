import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class AmrResult(Base):
    """One element AMRFinderPlus reported for an assembly in one amr_detection job (a gene, a point mutation, a stress
    or virulence gene), as the tool wrote it: a gene or mutation found, never a resistance phenotype.

    `type` is AMR, STRESS or VIRULENCE and `subtype` the tool's (AMR, POINT, POINT_DISRUPT, BIOCIDE, METAL, ...);
    `method` is AMRFinderPlus's own (EXACTX, BLASTX, PARTIALX, PARTIAL_CONTIG_ENDX, INTERNAL_STOP, POINTX, HMM, ...)
    and `method_kind` ARVA's reading of it (complete, partial, contig_end, internal_stop, point, hmm, ...). `contig`
    is the name in the file AMRFinderPlus read; `assembly_contig` the assembly's own name for it (they differ when the
    annotation renamed contigs). `feature` links the row to an annotated feature: by protein id in a combined search,
    or by overlap with a CDS of the annotation the job linked. The run itself (tool, database, parameters, files,
    warnings, the point-mutation screen) is the job's record.
    """

    __tablename__ = "amr_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_amr_results_sample_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_amr_results_assembly_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_amr_results_job_id"),
        nullable=False, index=True,
    )
    annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("annotations.id", ondelete="SET NULL", name="fk_amr_results_annotation_id"),
        nullable=True,
    )
    element_symbol: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    element_name: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amr_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amr_subclass: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    method_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    identity: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alignment_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contig: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assembly_contig: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strand: Mapped[str | None] = mapped_column(String(1), nullable=True)
    protein_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closest_accession: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closest_name: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    hmm_accession: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hmm_description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    hierarchy_node: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feature: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
