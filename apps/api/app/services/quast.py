"""QUAST evaluation requests: which assemblies and reference can be used, their labels, and ARVA's cross-check.

QUAST's numbers are QUAST's. Beside them ARVA shows its own statistics of the same contigs at the same minimum
contig length (arva_core.assembly_stats.min_length_summary), so a difference in definition or a fault in either
program is visible rather than hidden.
"""
from __future__ import annotations

import math
from typing import Any

from arva_core.assembly_stats import AssemblyFormatError, min_length_summary
from arva_core.seqstats import SequenceFormatError
from arva_tools import ToolStatus
from arva_tools.quast import DEFAULT_MIN_CONTIG, MAX_ASSEMBLIES, aligner, assembly_label
from arva_tools.registry import detect
from sqlalchemy.orm import Session

from app.models import Assembly, FileFormat, RawFile, Sample
from app.services.performance import Resources, effective_resources
from app.storage import get_storage

REFERENCE_FORMATS = (FileFormat.fasta, FileFormat.fasta_gz)
# QUAST field, key in min_length_summary, decimals QUAST prints (None: an exact count or length).
CROSSCHECK = (
    ("# contigs", "contigs", None),
    ("Total length", "total_length", None),
    ("Largest contig", "largest_contig", None),
    ("N50", "n50", None),
    ("L50", "l50", None),
    ("N90", "n90", None),
    ("L90", "l90", None),
    ("GC (%)", "gc_percent", 2),
    # QUAST counts the IUPAC codes it turned into N as N's; ARVA's own n_per_100kb counts N only.
    ("# N's per 100 kbp", "ambiguous_per_100kb", 2),
    ("# contigs (>= 0 bp)", "all_contigs", None),
    ("Total length (>= 0 bp)", "all_total_length", None),
)


class InputError(ValueError):
    """The selected assemblies or reference cannot be evaluated with QUAST as requested (HTTP 400)."""


def assemblies_for(db: Session, sample: Sample, ids: list[str]) -> list[Assembly]:
    if not 1 <= len(ids) <= MAX_ASSEMBLIES:
        raise InputError(f"Choose between 1 and {MAX_ASSEMBLIES} assemblies")
    if len(set(ids)) != len(ids):
        raise InputError("The same assembly was given more than once")
    out = []
    for assembly_id in ids:
        a = db.get(Assembly, assembly_id)
        if a is None or a.sample_id != sample.id:
            raise InputError(f"Assembly {assembly_id} does not belong to this sample")
        if not get_storage().resolve(a.contigs_path).is_file():
            raise InputError(f"The contigs file of assembly {labels([a])[a.id]} is missing on disk")
        out.append(a)
    return out


def reference_for(db: Session, sample: Sample, file_id: str | None) -> RawFile | None:
    if file_id is None:
        return None
    f = db.get(RawFile, file_id)
    if f is None or f.sample_id != sample.id:
        raise InputError(f"File {file_id} does not belong to this sample")
    if f.file_format not in REFERENCE_FORMATS:
        raise InputError(f"{f.original_filename} is not a FASTA file; a reference genome must be FASTA (.fasta, .fa, "
                         "optionally gzip-compressed)")
    if not f.is_valid:
        raise InputError(f"{f.original_filename} failed validation and cannot be used: {f.validation_message}")
    return f


def labels(assemblies: list[Assembly]) -> dict[str, str]:
    return {a.id: assembly_label(a.assembler, a.assembler_version, a.id) for a in assemblies}


def summary_at(assembly: Assembly, min_contig: int) -> dict[str, Any]:
    try:
        return min_length_summary(get_storage().resolve(assembly.contigs_path), min_contig)
    except (AssemblyFormatError, SequenceFormatError, OSError) as exc:
        raise InputError(f"The contigs of assembly {assembly.id} cannot be read: {exc}") from exc


def check_contigs_kept(assemblies: list[Assembly], summaries: list[dict[str, Any]], min_contig: int) -> None:
    """QUAST skips an assembly without a contig of at least --min-contig bp and still succeeds; ARVA refuses."""
    names = labels(assemblies)
    empty = [names[a.id] for a, s in zip(assemblies, summaries, strict=True) if not s["contigs"]]
    if empty:
        raise InputError(f"No contig of {', '.join(empty)} is at least {min_contig:,} bp long, so QUAST would leave "
                         "the assembly out; lower the minimum contig length")


def tool_status(res: Resources) -> dict[str, Any]:
    """Detected afresh: a preview should describe the QUAST and minimap2 that a run started now would use."""
    d = detect("quast", refresh=True)
    a = aligner(d.path) if d.status is ToolStatus.available and d.path else None
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "aligner": a, "max_threads": res.max_threads,
            "default_threads": res.threads,
            "default_min_contig": DEFAULT_MIN_CONTIG}


def plan(db: Session, sample: Sample, assembly_ids: list[str], reference_id: str | None, min_contig: int) -> dict[str, Any]:
    assemblies = assemblies_for(db, sample, assembly_ids)
    reference = reference_for(db, sample, reference_id)
    names = labels(assemblies)
    rows = []
    for a in assemblies:
        s = summary_at(a, min_contig)
        rows.append({
            "assembly_id": a.id, "label": names[a.id], "assembler": a.assembler,
            "assembler_version": a.assembler_version, "read_type": a.read_type, "created_at": a.created_at,
            "contigs": s["all_contigs"], "total_length": s["all_total_length"], "contigs_kept": s["contigs"],
            "length_kept": s["total_length"], "contigs_left_out": s["all_contigs"] - s["contigs"],
            "length_left_out": s["all_total_length"] - s["total_length"],
        })
    return {
        "tool": tool_status(effective_resources(db)),
        "min_contig": min_contig,
        "assemblies": rows,
        "reference": None if reference is None else {
            "file_id": reference.id, "name": reference.original_filename, "size_bytes": reference.size_bytes,
            "origin": reference.origin},
    }


def _agrees(quast: Any, arva: Any, decimals: int | None) -> bool | None:
    if quast is None or arva is None or not isinstance(quast, int | float):
        return None
    if decimals is None:
        return quast == arva
    # QUAST prints these rounded; ARVA's exact value must round to it.
    return math.isclose(quast, arva, abs_tol=0.5 * 10 ** -decimals + 1e-9)


def crosscheck(quast_values: dict[str, Any], arva: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per metric both programs report, with whether ARVA's value equals (or rounds to) QUAST's."""
    rows = []
    for field, key, decimals in CROSSCHECK:
        if field not in quast_values:
            continue
        rows.append({"metric": field, "arva_key": key, "quast": quast_values[field], "arva": arva.get(key),
                     "decimals": decimals, "agrees": _agrees(quast_values[field], arva.get(key), decimals)})
    return rows
