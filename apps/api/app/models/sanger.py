"""Sanger reads of one gene and what ARVA made of them.

Where they live in ARVA's model: a Sanger read belongs to a sample, the strain or isolate it was amplified from, like
the sample's sequencing reads. A strain that also has a genome in ARVA is the same sample, so the identification of
its Sanger consensus can be searched against that genome (and its annotation) as one more source, and both results
are shown on the same sample. The original files stay in raw/ untouched, as every upload does.

* sanger_reads: one read from an uploaded .ab1, FASTA or .seq file (a FASTA file may hold several reads), with the
  direction and pair ARVA proposed from the name or the user set.
* sanger_identifications: one question asked of one or two reads: the trimming and consensus settings, the consensus
  (or single trimmed read) that was searched, with every column's evidence, and what the user suspects it is.
* sanger_search_results: the hits of one search job (one source: NCBI 16S, VFDB, MLST alleles, AMRFinderPlus,
  spa repeats, a reference collection or the project's genomes) of an identification. The ranking across sources,
  the 16S reading and the comparison with the suspicion are computed from these rows when they are shown, so changing
  the suspicion needs no new search.
"""
import datetime as dt

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid, utcnow


class SangerRead(TimestampMixin, Base):
    __tablename__ = "sanger_reads"
    __table_args__ = (UniqueConstraint("sample_id", "sha256", "record_index",
                                       name="uq_sanger_reads_sample_id_sha256_record_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_sanger_reads_sample_id"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # abi (.ab1 chromatogram), fasta or seq (bases only)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    # The record's position in its file (a FASTA file may hold several reads); 0 otherwise.
    record_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # SHA-256 and size of the uploaded file (shared by the reads of one FASTA file).
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # forward, reverse or unknown; direction_source: name (ARVA read it from the name), user, or none.
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    direction_source: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    # The name without its direction and primer suffix: reads with the same key are proposed as a pair.
    pair_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
    has_qualities: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_trace: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # arva_core.sanger.SangerRead.summary(): sample name in the file, instrument, base caller, mean quality, Q20
    # share, warnings; and the Mott trimming at the default limit, for the list.
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)


class SangerIdentification(TimestampMixin, Base):
    __tablename__ = "sanger_identifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("samples.id", ondelete="CASCADE", name="fk_sanger_identifications_sample_id"),
        nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # A read used by an identification cannot be deleted while the identification exists (its evidence). A pair has
    # both; a single read is the forward or the reverse one, as the user said.
    forward_read_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sanger_reads.id", name="fk_sanger_identifications_forward_read_id"),
        nullable=True, index=True)
    reverse_read_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sanger_reads.id", name="fk_sanger_identifications_reverse_read_id"),
        nullable=True, index=True)
    # pair (forward + reverse consensus) or single (one trimmed read)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    # Trimming of each read and consensus parameters, as given (with ARVA's defaults filled in).
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)
    # The sequence that is searched, its length and SHA-256.
    sequence: Mapped[str] = mapped_column(Text, nullable=False)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # arva_core.sanger.consensus() for a pair (every column's evidence and every conflict), or the single read's
    # trimming; the reads' summaries and trimming.
    consensus: Mapped[dict] = mapped_column(JSON, nullable=False)
    # What the user suspects: {"kind": "gene" | "species", "value": "..."}, or None.
    suspected: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SangerSearchResult(Base):
    __tablename__ = "sanger_search_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    identification_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sanger_identifications.id", ondelete="CASCADE",
                               name="fk_sanger_search_results_identification_id"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_sanger_search_results_job_id"),
        nullable=False, unique=True)
    # ncbi_16s, vfdb, mlst, amrfinderplus, spa, reference_genomes or genomes
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # One row per subject (arva_core.sanger.hits_from_hsps), best first; AMRFinderPlus and spaTyper rows in their
    # own shape.
    rows: Mapped[list] = mapped_column(JSON, nullable=False)
    # Counts, warnings, the source's description (database, version, genomes searched) and tool facts.
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
