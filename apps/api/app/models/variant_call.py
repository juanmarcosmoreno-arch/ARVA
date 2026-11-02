import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class VariantCall(Base):
    """One variant-calling run of a sample's reads against a reference (read alignment with minimap2 or BWA-MEM,
    haploid calling with bcftools, soft filters, and bcftools csq effects when the reference is an annotated ARVA
    assembly).

    `reference` is the snapshot of the reference taken when the job was queued: kind (assembly or a genome of a
    reference collection), its label, the SHA-256 of the FASTA ARVA aligned to, its contigs and lengths, and the
    annotation used for effects. `reference_assembly_id` links runs against an ARVA assembly so that the Genome
    Explorer can show them (SET NULL when that assembly is deleted; the snapshot stays). `reads` lists the read files
    (role, name, SHA-256). The variant records are not rows here: they are in the results file `files["variants"]`
    (JSON) next to the VCF, like an annotation's features. `summary` holds the counts, the plots' data, the alignment
    statistics and the callable (depth >= the minimum depth) positions; `files` kind → path, SHA-256 and size.
    """

    __tablename__ = "variant_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_variant_calls_sample_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_variant_calls_job_id"),
        nullable=False, unique=True,
    )
    reference_assembly_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="SET NULL", name="fk_variant_calls_reference_assembly_id"),
        nullable=True, index=True,
    )
    reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reference: Mapped[dict] = mapped_column(JSON, nullable=False)
    technology: Mapped[str] = mapped_column(String(20), nullable=False)
    aligner: Mapped[str] = mapped_column(String(100), nullable=False)
    aligner_version: Mapped[str] = mapped_column(String(100), nullable=False)
    caller_version: Mapped[str] = mapped_column(String(100), nullable=False)
    reads: Mapped[list] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    files: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
