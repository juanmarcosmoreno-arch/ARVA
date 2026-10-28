"""The numbers behind the annotation charts (spec §11, "Visualizaciones"): gene lengths, gene density along each
sequence, strand, COG functional categories, hypothetical against characterised CDS and features by type.

Every number counts the annotator's features as reported (arva_core.annotation); nothing is predicted here.

* Genes are features of GENE_TYPES: CDS, small ORFs, tRNA, tmRNA, rRNA and ncRNA genes (regulatory ncRNA regions,
  CRISPR arrays, origins and gaps are not genes), as in the Genome Explorer.
* A gene's length is the bases it spans (a gene across the origin of a circular sequence spans both ends).
* Gene density: genes per window of `window` bases on a grid from each sequence's first base; a gene counts once, in
  the window holding its middle base. The last window of a sequence is shorter when the length is not a multiple of
  the window, so it is reported with its own length.
* Strand is the strand of the sequence as written. Leading and lagging strand would need the replication origin and
  terminus, which ARVA does not locate, so genes are not classified that way.
* COG categories are the letters the annotator reported for a CDS (a CDS with several letters counts in each);
  category names are those of NCBI's COG 2020 release.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from typing import Any

from arva_core.annotation import FEATURE_TYPES

GENE_TYPES = ("cds", "sorf", "trna", "tmrna", "rrna", "ncrna")
RNA_TYPES = frozenset({"trna", "tmrna", "rrna", "ncrna"})
LENGTH_CLASSES = ("cds_characterised", "cds_hypothetical", "sorf", "rna")
STRANDS = ("+", "-", ".")
TARGET_BINS = 40
MIN_BIN = 10
TARGET_WINDOWS = 100
MIN_WINDOW = 1_000
MAX_WINDOWS = 20_000

# NCBI COG 2020 functional categories (https://ftp.ncbi.nih.gov/pub/COG/COG2020/data/fun-20.tab, retrieved
# 2026-10-28): letter and description, in the file's order.
COG_CATEGORIES: dict[str, str] = {
    "J": "Translation, ribosomal structure and biogenesis",
    "A": "RNA processing and modification",
    "K": "Transcription",
    "L": "Replication, recombination and repair",
    "B": "Chromatin structure and dynamics",
    "D": "Cell cycle control, cell division, chromosome partitioning",
    "Y": "Nuclear structure",
    "V": "Defense mechanisms",
    "T": "Signal transduction mechanisms",
    "M": "Cell wall/membrane/envelope biogenesis",
    "N": "Cell motility",
    "Z": "Cytoskeleton",
    "W": "Extracellular structures",
    "U": "Intracellular trafficking, secretion, and vesicular transport",
    "O": "Posttranslational modification, protein turnover, chaperones",
    "X": "Mobilome: prophages, transposons",
    "C": "Energy production and conversion",
    "G": "Carbohydrate transport and metabolism",
    "E": "Amino acid transport and metabolism",
    "F": "Nucleotide transport and metabolism",
    "H": "Coenzyme transport and metabolism",
    "I": "Lipid transport and metabolism",
    "P": "Inorganic ion transport and metabolism",
    "Q": "Secondary metabolites biosynthesis, transport and catabolism",
    "R": "General function prediction only",
    "S": "Function unknown",
}
COG_SOURCE = "NCBI COG 2020 (fun-20.tab)"


def nice125(x: float) -> int:
    """The smallest 1-2-5 number (1, 2, 5, 10, 20, ...) not below x."""
    if x <= 1:
        return 1
    magnitude = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * magnitude >= x:
            return int(m * magnitude)
    return int(10 * magnitude)


def length_class(f: dict[str, Any]) -> str | None:
    if f["type"] == "cds":
        return "cds_hypothetical" if f["hypothetical"] else "cds_characterised"
    if f["type"] == "sorf":
        return "sorf"
    return "rna" if f["type"] in RNA_TYPES else None


def middle_base(f: dict[str, Any], length: int) -> int:
    """The 1-based position of a feature's middle base (for an even length, the one before the middle)."""
    if f["edge"] and f["start"] > f["end"]:
        span = length - f["start"] + 1 + f["end"]
        return (f["start"] - 1 + (span - 1) // 2) % length + 1
    lo, hi = min(f["start"], f["end"]), max(f["start"], f["end"])
    return lo + (hi - lo) // 2


def _describe(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "min": None, "median": None, "mean": None, "max": None}
    return {"n": len(values), "min": min(values), "median": statistics.median(values),
            "mean": round(statistics.fmean(values), 1), "max": max(values)}


def length_histogram(features: Sequence[dict[str, Any]], width: int | None = None) -> dict[str, Any]:
    """Genes by length class in bins of `width` bp (default: a 1-2-5 width giving about TARGET_BINS bins up to the
    99th percentile of the lengths); longer genes go to a last open bin, so one very long gene does not squeeze
    the rest."""
    lengths: dict[str, list[int]] = {c: [] for c in LENGTH_CLASSES}
    for f in features:
        c = length_class(f)
        if c is not None:
            lengths[c].append(f["length"])
    every = sorted(v for vs in lengths.values() for v in vs)
    if not every:
        return {"width": None, "bins": [], "classes": {c: _describe([]) for c in LENGTH_CLASSES}}
    p99 = every[max(0, math.ceil(0.99 * len(every)) - 1)]
    if width is None:
        width = max(MIN_BIN, nice125(p99 / TARGET_BINS))
    if width < 1:
        raise ValueError("the bin width must be at least 1 bp")
    regular = max(1, p99 // width + 1)
    if regular > 1_000:
        raise ValueError(f"{regular:,} bins of {width:,} bp: use a wider bin")
    counts = {c: [0] * (regular + 1) for c in LENGTH_CLASSES}
    for c, vs in lengths.items():
        for v in vs:
            counts[c][min(v // width, regular)] += 1
    bins = [{"min": k * width, "max": (k + 1) * width if k < regular else None,
             **{c: counts[c][k] for c in LENGTH_CLASSES}} for k in range(regular + 1)]
    if not any(bins[-1][c] for c in LENGTH_CLASSES):
        bins.pop()
    return {"width": width, "bins": bins, "classes": {c: _describe(vs) for c, vs in lengths.items()}}


def density_window(sequences: Sequence[dict[str, Any]]) -> int:
    """A 1-2-5 window (at least MIN_WINDOW bp) giving the longest sequence about TARGET_WINDOWS windows."""
    longest = max((s["length"] for s in sequences), default=0)
    return max(MIN_WINDOW, nice125(longest / TARGET_WINDOWS))


def gene_density(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]],
                 window: int | None = None) -> dict[str, Any]:
    """Genes per window along each sequence, by strand, counted at each gene's middle base."""
    window = window or density_window(sequences)
    if window < 1:
        raise ValueError("the window must be at least 1 bp")
    total_windows = sum(-(-s["length"] // window) for s in sequences)
    if total_windows > MAX_WINDOWS:
        raise ValueError(f"{total_windows:,} windows of {window:,} bp (at most {MAX_WINDOWS:,}): use a larger window")
    by_contig = {s["id"]: {st: [0] * -(-s["length"] // window) for st in STRANDS} for s in sequences}
    lengths = {s["id"]: s["length"] for s in sequences}
    for f in features:
        if f["type"] not in GENE_TYPES or f["contig"] not in by_contig:
            continue
        k = (middle_base(f, lengths[f["contig"]]) - 1) // window
        by_contig[f["contig"]][f["strand"] if f["strand"] in STRANDS else "."][k] += 1
    out = []
    for s in sequences:
        c = by_contig[s["id"]]
        n = len(c["+"])
        totals = [c["+"][k] + c["-"][k] + c["."][k] for k in range(n)]
        out.append({"contig": s["id"], "contig_in_assembly": s.get("original_id") or s["id"], "length": s["length"],
                    "start": [k * window + 1 for k in range(n)],
                    "end": [min((k + 1) * window, s["length"]) for k in range(n)],
                    "forward": c["+"], "reverse": c["-"], "unstranded": c["."], "total": totals,
                    "genes": sum(totals)})
    return {"window": window, "contigs": out}


def strand_counts(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Genes by strand: per gene type, per sequence and in total."""
    by_type = {t: dict.fromkeys(STRANDS, 0) for t in GENE_TYPES}
    by_contig = {s["id"]: dict.fromkeys(STRANDS, 0) for s in sequences}
    for f in features:
        if f["type"] not in GENE_TYPES:
            continue
        strand = f["strand"] if f["strand"] in STRANDS else "."
        by_type[f["type"]][strand] += 1
        if f["contig"] in by_contig:
            by_contig[f["contig"]][strand] += 1
    total = {st: sum(v[st] for v in by_type.values()) for st in STRANDS}
    return {"by_type": {t: v for t, v in by_type.items() if any(v.values())},
            "by_contig": [{"contig": s["id"], "contig_in_assembly": s.get("original_id") or s["id"],
                           **by_contig[s["id"]]} for s in sequences],
            "total": total, "replication_strand": "not_determined"}


def cog_profile(features: Sequence[dict[str, Any]], cds_searched: bool) -> dict[str, Any]:
    """CDS per COG category letter the annotator reported, in the COG file's order (letters ARVA does not know
    are kept and listed last)."""
    cds = [f for f in features if f["type"] == "cds"]
    counts = Counter(c for f in cds for c in dict.fromkeys(f["cog_categories"]))
    order = [c for c in COG_CATEGORIES if counts[c]] + sorted(c for c in counts if c not in COG_CATEGORIES)
    return {"cds_searched": cds_searched, "cds": len(cds) if cds_searched else None,
            "reported": bool(counts), "cds_with_category": sum(1 for f in cds if f["cog_categories"]),
            "cds_with_cog_id": sum(1 for f in cds if f["cog"]),
            "categories": [{"letter": c, "name": COG_CATEGORIES.get(c), "cds": counts[c]} for c in order],
            "names_source": COG_SOURCE}


def hypothetical_counts(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]],
                        cds_searched: bool) -> dict[str, Any]:
    """Characterised and hypothetical CDS per sequence and in total (None when the CDS step did not run)."""
    if not cds_searched:
        return {"cds_searched": False, "by_contig": [], "total": None}
    rows = {s["id"]: {"characterised": 0, "hypothetical": 0} for s in sequences}
    for f in features:
        if f["type"] == "cds" and f["contig"] in rows:
            rows[f["contig"]]["hypothetical" if f["hypothetical"] else "characterised"] += 1
    total = {k: sum(r[k] for r in rows.values()) for k in ("characterised", "hypothetical")}
    return {"cds_searched": True,
            "by_contig": [{"contig": s["id"], "contig_in_assembly": s.get("original_id") or s["id"], **rows[s["id"]]}
                          for s in sequences],
            "total": total}


def type_counts(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Features by type, per sequence and in total, in FEATURE_TYPES order (types without features left out)."""
    per = {s["id"]: Counter() for s in sequences}
    for f in features:
        if f["contig"] in per:
            per[f["contig"]][f["type"]] += 1
    total = Counter(f["type"] for f in features)
    types = [t for t in FEATURE_TYPES if total[t]]
    return {"types": types, "total": {t: total[t] for t in types},
            "by_contig": [{"contig": s["id"], "contig_in_assembly": s.get("original_id") or s["id"],
                           "counts": {t: per[s["id"]][t] for t in types if per[s["id"]][t]}} for s in sequences]}


def annotation_charts(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]], cds_searched: bool,
                      length_bin: int | None = None, window: int | None = None) -> dict[str, Any]:
    return {"cds_searched": cds_searched,
            "genes": sum(1 for f in features if f["type"] in GENE_TYPES),
            "lengths": length_histogram(features, length_bin),
            "density": gene_density(features, sequences, window),
            "strand": strand_counts(features, sequences),
            "cog": cog_profile(features, cds_searched),
            "hypothetical": hypothetical_counts(features, sequences, cds_searched),
            "types": type_counts(features, sequences)}
