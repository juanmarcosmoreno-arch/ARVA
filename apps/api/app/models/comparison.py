import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid, utcnow


class ComparisonSet(TimestampMixin, Base):
    """A named, reusable selection of assemblies to compare (comparative genomics). The assemblies may come from any
    sample of any project; the set itself is kept in one project (`project_id`), which holds its jobs, results and
    report section."""

    __tablename__ = "comparison_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE", name="fk_comparison_sets_project_id"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    members: Mapped[list["ComparisonMember"]] = relationship(
        back_populates="comparison_set", cascade="all, delete-orphan", order_by="ComparisonMember.position")


class ComparisonMember(Base):
    """One assembly of a comparison set, at its position in the set's order, with the label shown in plots."""

    __tablename__ = "comparison_members"
    __table_args__ = (UniqueConstraint("set_id", "assembly_id", name="uq_comparison_members_set_id_assembly_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("comparison_sets.id", ondelete="CASCADE", name="fk_comparison_members_set_id"),
        nullable=False, index=True,
    )
    assembly_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assemblies.id", ondelete="CASCADE", name="fk_comparison_members_assembly_id"),
        nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    comparison_set: Mapped[ComparisonSet] = relationship(back_populates="members")


class ComparisonResult(Base):
    """The result of one comparative job on a set: `analysis` ani (skani triangle or FastANI all-vs-all: the matrix
    and the similarity ordering in `summary`) or alignment (minimap2 or NUCmer, with dnadiff per pair: per-pair
    summaries, conservation and structural differences in `summary`; the alignment blocks in the results file
    `files["alignment.json"]`). `genomes` is the snapshot of the compared assemblies (label, sample, contigs and their
    SHA-256) taken when the job ran, so the result stays readable after the set changes."""

    __tablename__ = "comparison_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("comparison_sets.id", ondelete="CASCADE", name="fk_comparison_results_set_id"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_comparison_results_job_id"),
        nullable=False, unique=True,
    )
    analysis: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    genomes: Mapped[list] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False)
    files: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GeneQuery(Base):
    """A query sequence for Custom Gene Investigation, saved once and reused: pasted or uploaded FASTA, or a feature
    of an annotation (`source` says which, with the annotation, feature and annotator). One record per molecule and
    sequence (SHA-256 of the upper-case residues)."""

    __tablename__ = "gene_queries"
    __table_args__ = (UniqueConstraint("molecule", "sha256", name="uq_gene_queries_molecule_sha256"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    molecule: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence: Mapped[str] = mapped_column(Text, nullable=False)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PhyloTreeView(Base):
    """How a phylogeny result (a comparison_results row with analysis "phylogeny") is shown: the rooting chosen
    (none, midpoint or an outgroup; ARVA roots the inferred tree for drawing, never re-infers it) and the Tree
    Explorer's display choices (layout, collapsed clades, branch colours, leaf colouring, metadata bands). One row per
    result, changed by the user at any time."""

    __tablename__ = "phylo_tree_views"
    __table_args__ = (UniqueConstraint("result_id", name="uq_phylo_tree_views_result_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("comparison_results.id", ondelete="CASCADE", name="fk_phylo_tree_views_result_id"),
        nullable=False,
    )
    rooting: Mapped[dict] = mapped_column(JSON, nullable=False)
    style: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow,
                                                    nullable=False)
