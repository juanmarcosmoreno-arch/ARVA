"""Contig statistics and heuristic warnings for a genome assembly (a contigs FASTA).

Definitions (docs/scientific-methods.md, "Assembly statistics"):

* Contigs are ranked by length, longest first. Contigs of equal length keep their order in the FASTA
  file (stable sort); Nx and Lx do not depend on that order because tied contigs have equal lengths.
* Nx is the length of the ranked contig at which the cumulative length first reaches at least
  x % of the total length; Lx is its rank, i.e. the smallest number of contigs whose lengths add up to
  at least x % of the total (the definitions QUAST uses).
* GC % = (G + C) / (A + C + G + T) x 100, over unambiguous bases only. N and the other IUPAC codes
  are counted separately and never enter the GC denominator (QUAST divides by every base except N).

Coverage, circularity and repeat flags are not computed here: the assembler reports them per contig
and they are passed in as ContigAnnotation values. The warnings are heuristics with fixed, stated
thresholds; they flag results worth checking, they are not quality verdicts.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from arva_core import __version__
from arva_core.formats import SequenceFormat, open_sequence_file, sniff_format
from arva_core.seqstats import _DECOMPRESSION_ERRORS, SequenceFormatError, iter_fasta

TOOL_NAME = "arva-core.assembly_stats"
TOOL_VERSION = __version__
SCHEMA_VERSION = 1

MAX_CURVE_POINTS = 1000
CURVE_HEAD = 500  # the longest contigs are always kept exactly in a down-sampled curve
WARNING_CONTIG_NAMES = 50

AssemblyMode = Literal["long", "short", "hybrid"]

# Heuristic thresholds (stated in every check and in docs/scientific-methods.md).
CONTIGS_PER_MB = {"long": 10, "hybrid": 10, "short": 100}
GENOME_SIZE_TOLERANCE = 0.20
LOW_COVERAGE_RATIO = 0.25
HIGH_COVERAGE_RATIO = 4.0
CHROMOSOME_FRACTION = 0.5
GC_OUTLIER_POINTS = 10.0
GC_OUTLIER_MIN_LENGTH = 1_000


class AssemblyFormatError(ValueError):
    """The contigs file cannot be summarised (not FASTA, duplicate names, no bases, ...)."""


@dataclass(frozen=True)
class ContigAnnotation:
    coverage: float | None = None
    circular: bool | None = None
    repeat: bool | None = None


@dataclass
class AssemblyStatsParameters:
    thresholds: tuple[int, ...] = (1_000, 10_000)

    def as_dict(self) -> dict[str, Any]:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}


def _length_bin_edges(max_length: int) -> list[int]:
    """0, 100, 200, 500, 1,000, 2,000, 5,000, ... up to the first edge above max_length."""
    edges, scale = [0], 100
    while edges[-1] <= max_length:
        for step in (1, 2, 5):
            edges.append(step * scale)
            if edges[-1] > max_length:
                break
        scale *= 10
    return edges


def _histogram(lengths: np.ndarray) -> list[dict[str, int]]:
    edges = _length_bin_edges(int(lengths.max()))
    idx = np.searchsorted(edges, lengths, side="right") - 1
    counts = np.bincount(idx, minlength=len(edges) - 1)
    bases = np.bincount(idx, weights=lengths, minlength=len(edges) - 1)
    first = int(idx.min())
    return [
        {"min_length": edges[i], "max_length": edges[i + 1], "contigs": int(counts[i]), "total_length": int(bases[i])}
        for i in range(first, len(edges) - 1)
    ]


def _nx(desc: np.ndarray, cumulative: np.ndarray, percent: int) -> tuple[int, int]:
    # Integer comparison 100 x cumulative >= percent x total: no floating-point rounding at the boundary.
    rank = int(np.searchsorted(100 * cumulative, percent * int(cumulative[-1]), side="left"))
    return int(desc[rank]), rank + 1


def _curve(desc: np.ndarray, cumulative: np.ndarray) -> dict[str, Any]:
    n = desc.size
    if n <= MAX_CURVE_POINTS:
        idx = np.arange(n)
    else:
        tail = np.linspace(CURVE_HEAD, n - 1, MAX_CURVE_POINTS - CURVE_HEAD).round().astype(np.int64)
        idx = np.unique(np.concatenate([np.arange(CURVE_HEAD), tail]))
    return {
        "rank": [int(i) + 1 for i in idx],
        "length": [int(desc[i]) for i in idx],
        "cumulative_length": [int(cumulative[i]) for i in idx],
        "downsampled": n > MAX_CURVE_POINTS,
    }


def weighted_median_coverage(contigs: list[dict[str, Any]]) -> float | None:
    """Coverage of the contig holding the middle base when contigs with a coverage are ordered by coverage."""
    rows = sorted((c for c in contigs if c["coverage"] is not None and c["length"] > 0), key=lambda c: c["coverage"])
    total = sum(c["length"] for c in rows)
    if not total:
        return None
    acc = 0
    for c in rows:
        acc += c["length"]
        if 2 * acc >= total:
            return float(c["coverage"])
    return None


def compute_assembly_stats(
    path: Path,
    annotations: Mapping[str, ContigAnnotation] | None = None,
    params: AssemblyStatsParameters | None = None,
) -> dict[str, Any]:
    """Statistics of every contig in a (possibly gzip-compressed) FASTA file.

    Raises SequenceFormatError for malformed FASTA and AssemblyFormatError for files that are not a
    usable contigs FASTA. annotations are keyed by contig name (the header up to the first space);
    a name that is not in the file is an error, because it means the annotations belong to other contigs.
    """
    params = params or AssemblyStatsParameters()
    annotations = annotations or {}
    info = sniff_format(Path(path))
    if info.decompression_error:
        raise SequenceFormatError(f"compressed stream is corrupt or truncated ({info.decompression_error})")
    if info.format is not SequenceFormat.fasta:
        raise AssemblyFormatError("expected a contigs FASTA file (records starting with '>')")

    contigs: list[dict[str, Any]] = []
    seen: set[str] = set()
    totals = {"gc": 0, "acgt": 0, "n": 0, "other": 0}
    try:
        with open_sequence_file(Path(path)) as fh:
            for header, seq, _qual, line in iter_fasta(fh):
                name = header[1:].split(maxsplit=1)[0].decode("utf-8", "replace") if header[1:].strip() else ""
                if not name:
                    raise AssemblyFormatError(f"line {line}: contig without a name")
                if name in seen:
                    raise AssemblyFormatError(f"line {line}: contig name '{name}' appears more than once")
                seen.add(name)
                upper = seq.upper()
                gc = upper.count(b"G") + upper.count(b"C")
                acgt = gc + upper.count(b"A") + upper.count(b"T")
                n_count = upper.count(b"N")
                other = len(seq) - acgt - n_count
                for key, value in (("gc", gc), ("acgt", acgt), ("n", n_count), ("other", other)):
                    totals[key] += value
                note = annotations.get(name, ContigAnnotation())
                contigs.append({
                    "name": name,
                    "length": len(seq),
                    "gc_percent": 100.0 * gc / acgt if acgt else None,
                    "n_count": n_count,
                    "other_iupac_count": other,
                    "coverage": None if note.coverage is None else float(note.coverage),
                    "circular": note.circular,
                    "repeat": note.repeat,
                })
    except _DECOMPRESSION_ERRORS as exc:
        raise SequenceFormatError(f"compressed stream is corrupt or truncated ({exc})") from exc

    if not contigs:
        raise AssemblyFormatError("the FASTA file contains no contigs")
    if unknown := sorted(set(annotations) - seen):
        raise AssemblyFormatError(
            f"annotations name {len(unknown)} contig(s) that are not in the FASTA file: " + ", ".join(unknown[:10])
        )
    contigs.sort(key=lambda c: -c["length"])  # stable: ties keep file order
    for rank, c in enumerate(contigs, start=1):
        c["rank"] = rank
    desc = np.array([c["length"] for c in contigs], dtype=np.int64)
    total = int(desc.sum())
    if total == 0:
        raise AssemblyFormatError("the contigs contain no bases")
    cumulative = np.cumsum(desc)
    n50, l50 = _nx(desc, cumulative, 50)
    n90, l90 = _nx(desc, cumulative, 90)
    with_coverage = sum(c["coverage"] is not None for c in contigs)
    with_circularity = [c for c in contigs if c["circular"] is not None]

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "parameters": params.as_dict(),
        "file": {"compressed": info.compressed},
        "contig_count": len(contigs),
        "total_length": total,
        "largest_contig": int(desc[0]),
        "smallest_contig": int(desc[-1]),
        "n50": n50,
        "l50": l50,
        "n90": n90,
        "l90": l90,
        "gc_percent": 100.0 * totals["gc"] / totals["acgt"] if totals["acgt"] else None,
        "n_count": totals["n"],
        "n_per_100kb": 1e5 * totals["n"] / total,
        "other_iupac_count": totals["other"],
        "length_histogram": _histogram(desc),
        "cumulative": _curve(desc, cumulative),
        "thresholds": [
            {
                "min_length": t,
                "contigs": int((desc >= t).sum()),
                "total_length": int(desc[desc >= t].sum()),
                "total_length_percent": 100.0 * int(desc[desc >= t].sum()) / total,
            }
            for t in params.thresholds
        ],
        "coverage": {
            "contigs_with_coverage": with_coverage,
            "length_weighted_median": weighted_median_coverage(contigs),
        },
        "circularity": {
            "contigs_with_circularity": len(with_circularity),
            "circular_contigs": sum(bool(c["circular"]) for c in with_circularity),
        },
        "contigs": contigs,
    }


# --- Heuristic warnings ---------------------------------------------------------------------

def _names(rows: list[dict[str, Any]]) -> list[str]:
    return [r["name"] for r in rows[:WARNING_CONTIG_NAMES]]


def _warning(code: str, message: str, params: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows or []
    return {"code": code, "heuristic": True, "message": message, "params": params,
            "contigs": _names(rows), "contigs_total": len(rows)}


def _check(code: str, rule: str, skipped: str | None = None) -> dict[str, Any]:
    return {"code": code, "rule": rule, "evaluated": skipped is None, "skipped_reason": skipped}


def assembly_warnings(
    stats: dict[str, Any], mode: AssemblyMode, expected_genome_size_bp: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Heuristic warnings for compute_assembly_stats() output, and the list of checks with their rules.

    Every check is listed, also when it could not be evaluated (with the reason), so an absent
    warning is never mistaken for a passed check that was not run.
    """
    if mode not in CONTIGS_PER_MB:
        raise ValueError(f"unknown assembly mode {mode!r}")
    contigs: list[dict[str, Any]] = stats["contigs"]
    total = stats["total_length"]
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    limit = CONTIGS_PER_MB[mode]
    per_mb = stats["contig_count"] / max(total / 1e6, 1.0)
    checks.append(_check("many_contigs", f"more than {limit} contigs per Mb of assembly ({mode}-read assemblies; "
                                         "assemblies under 1 Mb are counted as 1 Mb)"))
    if per_mb > limit:
        warnings.append(_warning(
            "many_contigs",
            f"{stats['contig_count']:,} contigs for {total:,} bp ({per_mb:.1f} per Mb; heuristic threshold {limit} "
            f"per Mb for {mode}-read assemblies): the assembly is fragmented.",
            {"contigs": stats["contig_count"], "total_length": total, "per_mb": round(per_mb, 2), "limit_per_mb": limit,
             "mode": mode},
        ))

    rule = f"total length differs from the expected genome size by more than {GENOME_SIZE_TOLERANCE:.0%}"
    if expected_genome_size_bp:
        checks.append(_check("genome_size_mismatch", rule))
        diff = (total - expected_genome_size_bp) / expected_genome_size_bp
        if abs(diff) > GENOME_SIZE_TOLERANCE:
            warnings.append(_warning(
                "genome_size_mismatch",
                f"Total length {total:,} bp is {abs(diff):.0%} {'above' if diff > 0 else 'below'} the expected genome "
                f"size of {expected_genome_size_bp:,} bp (heuristic threshold {GENOME_SIZE_TOLERANCE:.0%}): the genome "
                "may be incomplete, or the assembly may contain contamination or duplicated sequence.",
                {"total_length": total, "expected_genome_size_bp": expected_genome_size_bp,
                 "difference_percent": round(100 * diff, 1), "tolerance_percent": round(100 * GENOME_SIZE_TOLERANCE)},
            ))
    else:
        checks.append(_check("genome_size_mismatch", rule, "no expected genome size is known for this sample"))

    median = stats["coverage"]["length_weighted_median"]
    for code, ratio, compare, meaning in (
        ("low_coverage_contigs", LOW_COVERAGE_RATIO, lambda c, m: c < LOW_COVERAGE_RATIO * m,
         "possible contamination, or sequence present in only part of the cells"),
        ("high_coverage_contigs", HIGH_COVERAGE_RATIO, lambda c, m: c > HIGH_COVERAGE_RATIO * m,
         "possible plasmids or other multi-copy elements, or collapsed repeats"),
    ):
        side = "below" if code.startswith("low") else "above"
        rule = f"contig coverage {side} {ratio:g} × the length-weighted median coverage"
        if median is None or stats["coverage"]["contigs_with_coverage"] < 2:
            checks.append(_check(code, rule, "the assembler reported coverage for fewer than two contigs"))
            continue
        checks.append(_check(code, rule))
        rows = [c for c in contigs if c["coverage"] is not None and compare(c["coverage"], median)]
        if rows:
            warnings.append(_warning(
                code,
                f"{len(rows)} contig(s) with coverage {side} {ratio:g} × the length-weighted median of {median:g}× "
                f"(heuristic): {meaning}.",
                {"median_coverage": median, "ratio": ratio, "count": len(rows)}, rows,
            ))

    reference = expected_genome_size_bp or total
    basis = "the expected genome size" if expected_genome_size_bp else "the total assembly length"
    rule = f"a contig of at least {CHROMOSOME_FRACTION:.0%} of {basis} that the assembler did not report as circular"
    large = [c for c in contigs if c["length"] >= CHROMOSOME_FRACTION * reference]
    if not large:
        checks.append(_check("chromosome_not_circular", rule, "no contig is chromosome-sized"))
    elif all(c["circular"] is None for c in large):
        checks.append(_check("chromosome_not_circular", rule, "the assembler reported no circularity"))
    else:
        checks.append(_check("chromosome_not_circular", rule))
        rows = [c for c in large if c["circular"] is False]
        if rows:
            warnings.append(_warning(
                "chromosome_not_circular",
                f"{len(rows)} chromosome-sized contig(s) (≥ {CHROMOSOME_FRACTION:.0%} of {basis}) not reported as "
                "circular (heuristic): the chromosome may be incomplete or contain a misassembly.",
                {"min_length": round(CHROMOSOME_FRACTION * reference), "basis": "expected_genome_size"
                 if expected_genome_size_bp else "total_length"}, rows,
            ))

    overall = stats["gc_percent"]
    rule = (f"GC of a contig of at least {GC_OUTLIER_MIN_LENGTH:,} bp differs from the assembly's GC by more than "
            f"{GC_OUTLIER_POINTS:g} percentage points")
    eligible = [c for c in contigs if c["length"] >= GC_OUTLIER_MIN_LENGTH and c["gc_percent"] is not None]
    if overall is None or len(eligible) < 2:
        checks.append(_check("gc_outlier_contigs", rule, "fewer than two contigs are long enough"))
    else:
        checks.append(_check("gc_outlier_contigs", rule))
        rows = [c for c in eligible if abs(c["gc_percent"] - overall) > GC_OUTLIER_POINTS]
        if rows:
            warnings.append(_warning(
                "gc_outlier_contigs",
                f"{len(rows)} contig(s) whose GC differs from the assembly's {overall:.1f} % by more than "
                f"{GC_OUTLIER_POINTS:g} percentage points (heuristic): possible contamination, or plasmids and "
                "other mobile elements, which often differ in GC.",
                {"assembly_gc_percent": round(overall, 2), "points": GC_OUTLIER_POINTS,
                 "min_length": GC_OUTLIER_MIN_LENGTH, "count": len(rows)}, rows,
            ))
    return warnings, checks
