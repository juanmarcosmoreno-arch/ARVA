"""Assemblies: registration by the job that wrote them, the expected genome size, and graph reading.

An assembly's files stay in its job's results/ folder; they are checksummed, made read-only and
recorded here, never registered as RawFile reads.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from arva_core.assembly_stats import (
    AssemblyFormatError,
    ContigAnnotation,
    assembly_warnings,
    compute_assembly_stats,
)
from arva_core.gfa import read_gfa
from arva_core.seqstats import SequenceFormatError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, Assembly, AssemblyKind, AssemblyMode, JobStatus
from app.services.jobs import FASTQ_STATS_JOB
from app.storage import get_storage
from app.tasks.common import JobContext, JobFailure

MAX_CONTIG_ROWS = 2000
GRAPH_MAX_NODES = 2000
GRAPH_MAX_EDGES = 5000
# The GFA segment tag that holds each assembler's coverage, and what it measures (arva_core.gfa leaves
# tags uninterpreted because assemblers define them differently).
GRAPH_COVERAGE_TAGS = {
    "Flye": ("dp", "mean read depth"),
    "SPAdes": ("DP", "k-mer coverage (SPAdes; not read depth)"),
    "Unicycler": ("dp", "depth relative to the assembly's median depth (Unicycler; 1 = typical chromosome depth)"),
}
# How the coverage warnings name each assembler's coverage, and its unit.
WARNING_COVERAGE = {"SPAdes": ("k-mer coverage", ""), "Unicycler": ("relative depth", "×"),
                    "Racon": ("mean depth of the mapped polishing reads", "×"),
                    "Pilon": ("mean depth of the mapped polishing reads", "×")}


def expected_genome_size(db: Session, sample_id: str, job_parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    """The genome size the user gave for this assembly, else the one given for the sample's read statistics.

    Read statistics count only when the newest completed statistics of every file that has any agree
    on one value; different values make the size unknown ("inconsistent"). ARVA never assumes a size.
    """
    params = job_parameters or {}
    if given := params.get("genome_size_bp"):
        return {"bp": int(given), "status": "given", "source": "assembly_parameters",
                "basis": params.get("genome_size_basis"), "assumed_depth_x": params.get("assumed_depth_x")}
    rows = db.execute(
        select(AnalysisJob.input_raw_file_ids, AnalysisJob.parameters)
        .where(AnalysisJob.sample_id == sample_id, AnalysisJob.job_type == FASTQ_STATS_JOB,
               AnalysisJob.status == JobStatus.completed)
        .order_by(AnalysisJob.finished_at.desc().nulls_last(), AnalysisJob.created_at.desc())
    ).all()
    latest: dict[str, int | None] = {}
    for file_ids, params in rows:
        for file_id in file_ids or []:
            latest.setdefault(file_id, (params or {}).get("expected_genome_size_bp"))
    sizes = {v for v in latest.values() if v}
    if not sizes:
        return {"bp": None, "status": "not_given", "source": None}
    if len(sizes) > 1:
        return {"bp": None, "status": "inconsistent", "source": None}
    return {"bp": int(next(iter(sizes))), "status": "given", "source": "read_statistics"}


def _sealed(ctx: JobContext, path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    results = ctx.path(ctx.results_rel)
    resolved = path.resolve()
    if results not in resolved.parents or not resolved.is_file():
        raise ValueError(f"{path.name} is not a file in this job's results folder")
    stored = ctx.storage.seal(str(resolved.relative_to(ctx.storage.root)))
    return {"path": stored.relative_path, "sha256": stored.sha256, "size_bytes": stored.size_bytes}


def register_assembly(
    ctx: JobContext,
    *,
    assembler: str,
    mode: AssemblyMode,
    read_type: str,
    contigs: Path,
    graph: Path | None = None,
    info: Path | None = None,
    annotations: Mapping[str, ContigAnnotation] | None = None,
    parent: Assembly | None = None,
) -> Assembly:
    """Summarise the contigs, evaluate the heuristic warnings and add the Assembly to the job's session. With
    `parent` (the draft) the assembly is recorded as a polished version of it."""
    job = ctx.job
    if job.sample_id is None or not job.input_raw_file_ids:
        raise JobFailure("an assembly needs a sample and the read files it was built from")
    try:
        files = {"contigs": _sealed(ctx, contigs), "graph": _sealed(ctx, graph), "info": _sealed(ctx, info)}
    except ValueError as exc:
        raise JobFailure(f"{assembler} output cannot be registered: {exc}") from exc
    try:
        stats = compute_assembly_stats(contigs, annotations)
    except (AssemblyFormatError, SequenceFormatError) as exc:
        raise JobFailure(f"{assembler} wrote contigs that cannot be read: {exc}") from exc
    genome = expected_genome_size(ctx.db, job.sample_id, job.parameters)
    warnings, checks = assembly_warnings(stats, mode.value, genome["bp"], *WARNING_COVERAGE.get(assembler, ()))
    rows = stats.pop("contigs")
    stats.update({
        "contig_rows": {"stored": min(len(rows), MAX_CONTIG_ROWS), "total": len(rows),
                        "truncated": len(rows) > MAX_CONTIG_ROWS},
        "expected_genome_size": genome,
        "warning_checks": checks,
        "files": files,
    })
    assembly = Assembly(
        sample_id=job.sample_id,
        job_id=job.id,
        kind=AssemblyKind.polished if parent is not None else AssemblyKind.assembly,
        parent_assembly_id=parent.id if parent is not None else None,
        assembler=assembler,
        assembler_version=job.tool_version,
        mode=mode,
        read_type=read_type,
        input_file_ids=list(job.input_raw_file_ids),
        contigs_path=files["contigs"]["path"],
        graph_path=files["graph"]["path"] if files["graph"] else None,
        info_path=files["info"]["path"] if files["info"] else None,
        stats=stats,
        contigs=rows[:MAX_CONTIG_ROWS],
        warnings=warnings,
    )
    ctx.db.add(assembly)
    ctx.log(f"Assembly: {stats['contig_count']:,} contigs, {stats['total_length']:,} bp, N50 {stats['n50']:,} bp, "
            f"largest {stats['largest_contig']:,} bp (contigs sha256 {files['contigs']['sha256']})")
    if genome["bp"]:
        basis = {"entered": "; entered by the user", "expected_genome_size": "; the sample's expected genome size",
                 "reads_over_depth": f"; total read bases ÷ an assumed depth of {genome.get('assumed_depth_x')}×"}
        ctx.log(f"Expected genome size {genome['bp']:,} bp ({genome['source'].replace('_', ' ')}"
                f"{basis.get(genome.get('basis') or '', '')})")
    for w in warnings:
        ctx.log(f"Heuristic warning [{w['code']}]: {w['message']}")
    return assembly


def _any_flag(rows: list[dict[str, Any]], key: str) -> bool | None:
    known = [r[key] for r in rows if r.get(key) is not None]
    return any(known) if known else None


def assembly_graph(assembly: Assembly, max_nodes: int, max_edges: int) -> dict[str, Any]:
    """The graph's segments and links, each segment with the assembler's flags for the contigs whose GFA path
    (P line) runs through it: `circular`/`repeat` are true when any such contig has the flag, null when none of
    them reports it (no path, or a contig whose row is not stored).

    Raises FileNotFoundError when the graph file is gone and arva_core.gfa.GfaFormatError when unreadable.
    """
    path = get_storage().resolve(assembly.graph_path) if assembly.graph_path else None
    if path is None or not path.is_file():
        raise FileNotFoundError("assembly graph file")
    graph = read_gfa(path, max_nodes, max_edges)
    rows = {c["name"]: c for c in assembly.contigs}
    for node in graph["nodes"]:
        on = [rows[name] for name in node["paths"] if name in rows]
        node["circular"] = _any_flag(on, "circular")
        node["repeat"] = _any_flag(on, "repeat")
    tag, meaning = GRAPH_COVERAGE_TAGS.get(assembly.assembler, (None, None))
    return {"assembly_id": assembly.id, "assembler": assembly.assembler, "coverage_tag": tag,
            "coverage_meaning": meaning, **graph}
