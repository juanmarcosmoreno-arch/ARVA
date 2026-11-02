"""Variants called against a reference (bcftools mpileup + call, haploid): reading the VCF, the GFF3 that bcftools
csq needs, low-depth intervals, summaries for plots, and the SNP matrix and pairwise SNP distances across samples.

Definitions ARVA uses (stated wherever they are shown):

* alternative-allele fraction = AD[alt] / (AD[ref] + AD[alt]) of a (split, biallelic) record;
* a site is "callable" in a sample when its depth (reads with the mapping and base quality floors of the caller) is
  at least the minimum depth of the run's filters; otherwise it is missing (N) in the SNP matrix;
* a SNP of a sample is a PASS record with one reference and one alternative base. A site where the sample has a
  record that failed a filter, or lies inside a PASS indel or complex record, is missing (N), never "reference";
* the SNP distance of two samples counts the sites where both have a base and the bases differ (pairwise
  deletion); the number of sites compared is reported with it. SNP distances against one reference are not a
  phylogeny, and indels, recombination and regions absent from the reference are not counted.
"""
from __future__ import annotations

import bisect
import math
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

VARIANT_TYPES = ("snp", "mnp", "insertion", "deletion", "complex")
# bcftools csq's consequence types from the most to the least severe (csq.c, 1.19); BCSQ writes them without the
# "_variant" suffix, several joined with "&".
CONSEQUENCE_ORDER = ("splice_acceptor", "splice_donor", "stop_gained", "frameshift", "stop_lost", "start_lost",
                     "inframe_altering", "inframe_insertion", "inframe_deletion", "missense", "splice_region",
                     "synonymous", "stop_retained", "start_retained", "non_coding", "5_prime_utr", "3_prime_utr",
                     "intron", "intergenic")
BCSQ_FIELDS = ("consequence", "gene", "transcript", "biotype", "strand", "aa_change", "dna_change")
_RANK = {c: i for i, c in enumerate(CONSEQUENCE_ORDER)}
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")
_COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")
CODING_FEATURES = ("cds", "sorf")


def variant_type(ref: str, alt: str) -> str:
    if len(ref) == len(alt) == 1:
        return "snp"
    if len(ref) == len(alt):
        return "mnp"
    if len(alt) > len(ref) and alt.startswith(ref):
        return "insertion"
    if len(ref) > len(alt) and ref.startswith(alt):
        return "deletion"
    return "complex"


def _term(raw: str) -> str:
    t = raw.strip().lower()
    return t[:-len("_variant")] if t.endswith("_variant") else t


def parse_bcsq(value: str) -> list[dict[str, Any]]:
    """INFO/BCSQ entries. An entry "@POS" means the consequence of a haplotype was written at another position POS
    (bcftools csq groups the variants of one codon)."""
    out: list[dict[str, Any]] = []
    for entry in value.split(","):
        if not entry or entry == ".":
            continue
        if entry.startswith("@"):
            if entry[1:].isdigit():
                out.append({"see_position": int(entry[1:])})
            continue
        parts = entry.split("|")
        row = {k: (parts[i] if i < len(parts) and parts[i] != "" else None) for i, k in enumerate(BCSQ_FIELDS)}
        # csq prefixes with "*" the consequences of a variant downstream of a stop (manual, csq section).
        row["after_stop"] = (row["consequence"] or "").startswith("*")
        row["terms"] = [_term(t.lstrip("*")) for t in (row["consequence"] or "").split("&") if t]
        out.append(row)
    return out


def main_effect(consequences: Sequence[dict[str, Any]]) -> str | None:
    terms = [t for c in consequences for t in c.get("terms", [])]
    if not terms:
        return None
    return min(terms, key=lambda t: _RANK.get(t, len(_RANK)))


def _info(column: str) -> dict[str, str]:
    out = {}
    for item in column.split(";"):
        if item and item != ".":
            k, _, v = item.partition("=")
            out[k] = v
    return out


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "", ".") else None
    except ValueError:
        return None


def parse_vcf(lines: Iterable[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Sample names and records of a single-sample VCF after `bcftools norm -m -any` (one ALT per record). Raises
    ValueError on a malformed line."""
    samples: list[str] = []
    rows: list[dict[str, Any]] = []
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line or line.startswith("##"):
            continue
        f = line.split("\t")
        if line.startswith("#CHROM"):
            samples = f[9:]
            continue
        if len(f) < 8:
            raise ValueError(f"VCF line {n} has {len(f)} columns; a record has at least 8")
        pos = _int(f[1])
        if pos is None or pos < 1:
            raise ValueError(f"VCF line {n} has no valid position")
        ref, alt = f[3].upper(), f[4].upper()
        if "," in alt:
            raise ValueError(f"VCF line {n} has several ALT alleles; ARVA reads normalised, split records")
        info = _info(f[7])
        fmt: dict[str, str] = {}
        if len(f) >= 10:
            fmt = dict(zip(f[8].split(":"), f[9].split(":"), strict=False))
        ad = [x for x in (fmt.get("AD") or info.get("AD") or "").split(",") if x]
        ref_reads = _int(ad[0]) if len(ad) >= 1 else None
        alt_reads = _int(ad[1]) if len(ad) >= 2 else None
        depth = _int(fmt.get("DP")) if fmt.get("DP") not in (None, ".") else _int(info.get("DP"))
        both = (ref_reads or 0) + (alt_reads or 0)
        filters = [] if f[6] in ("PASS", ".") else f[6].split(";")
        consequences = parse_bcsq(info["BCSQ"]) if "BCSQ" in info else []
        rows.append({
            "contig": f[0], "pos": pos, "end": pos + len(ref) - 1, "ref": ref, "alt": alt,
            "type": "complex" if alt in ("*", "<*>") or alt.startswith("<") else variant_type(ref, alt),
            "qual": None if f[5] == "." else round(float(f[5]), 2), "filters": filters, "pass": not filters,
            "depth": depth, "ref_reads": ref_reads, "alt_reads": alt_reads,
            "alt_fraction": round(alt_reads / both, 4) if alt_reads is not None and both else None,
            "genotype": fmt.get("GT"), "consequences": consequences, "effect": main_effect(consequences),
            "after_stop": any(c.get("after_stop") for c in consequences),
        })
    return samples, rows


def _safe(text: str) -> str:
    return _SAFE_ID.sub("_", text)[:100] or "feature"


def csq_gff(features: Iterable[dict[str, Any]], contig_of: dict[str, str],
            lengths: dict[str, int]) -> tuple[str, dict[str, int]]:
    """An Ensembl-style GFF3 of the annotation's coding sequences for bcftools csq: one gene, one transcript and one
    CDS (phase 0) per CDS or sORF, on the reference's contig names (`contig_of` maps the annotator's contig names to
    them). Left out, and counted: pseudogenes, features that wrap around a circular contig's origin, lengths that are
    not a multiple of 3, and features on contigs that are not in the reference."""
    lines = ["##gff-version 3"]
    counts = Counter({"written": 0, "pseudo": 0, "wraps_origin": 0, "not_multiple_of_3": 0, "unknown_contig": 0})
    seen: Counter[str] = Counter()
    for f in features:
        if f.get("type") not in CODING_FEATURES:
            continue
        contig = contig_of.get(f["contig"], f["contig"])
        start, end = int(f["start"]), int(f["end"])
        if f.get("pseudo"):
            counts["pseudo"] += 1
        elif f.get("edge") or start > end:
            counts["wraps_origin"] += 1
        elif contig not in lengths or end > lengths[contig]:
            counts["unknown_contig"] += 1
        elif (end - start + 1) % 3:
            counts["not_multiple_of_3"] += 1
        else:
            base = _safe(f.get("locus_tag") or f.get("tool_id") or f"arva{f.get('id', 0)}")
            seen[base] += 1
            gid = base if seen[base] == 1 else f"{base}.{seen[base]}"
            name = _safe(f.get("gene") or gid)
            strand = f.get("strand") if f.get("strand") in ("+", "-") else "+"
            col = f"{contig}\tARVA\t{{}}\t{start}\t{end}\t.\t{strand}\t{{}}\t{{}}"
            lines.append(col.format("gene", ".", f"ID=gene:{gid};biotype=protein_coding;Name={name}"))
            lines.append(col.format("transcript", ".",
                                    f"ID=transcript:{gid};Parent=gene:{gid};biotype=protein_coding"))
            lines.append(col.format("CDS", "0", f"Parent=transcript:{gid}"))
            counts["written"] += 1
    return "\n".join(lines) + "\n", dict(counts)


def revcomp(seq: str) -> str:
    return seq.translate(_COMP)[::-1]


def start_codon_notes(variants: list[dict[str, Any]], features: Iterable[dict[str, Any]], contig_of: dict[str, str],
                      sequences: dict[str, str]) -> int:
    """Marks (`start_codon` = the reference codon) the variants that touch the first codon of a CDS whose reference
    start codon is not ATG: bcftools csq translates with the standard code and does not report start_lost for them.
    Returns how many variants were marked."""
    starts: dict[str, list[tuple[int, int, str]]] = {}
    for f in features:
        if f.get("type") not in CODING_FEATURES or f.get("pseudo") or f.get("edge"):
            continue
        contig = contig_of.get(f["contig"], f["contig"])
        seq = sequences.get(contig)
        start, end = int(f["start"]), int(f["end"])
        if seq is None or start > end or end > len(seq):
            continue
        if f.get("strand") == "-":
            lo, codon = end - 2, revcomp(seq[end - 3:end]).upper()
        else:
            lo, codon = start, seq[start - 1:start + 2].upper()
        if codon != "ATG":
            starts.setdefault(contig, []).append((lo, lo + 2, codon))
    marked = 0
    for v in variants:
        for lo, hi, codon in starts.get(v["contig"], ()):
            if v["pos"] <= hi and v["end"] >= lo:
                v["start_codon"] = codon
                marked += 1
                break
    return marked


def parse_depth(lines: Iterable[str]) -> Iterator[tuple[str, int, int]]:
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) < 3:
            raise ValueError(f"samtools depth line {n} has {len(f)} columns, expected 3")
        yield f[0], int(f[1]), int(f[2])


def low_depth_intervals(rows: Iterable[tuple[str, int, int]], min_depth: int) -> dict[str, Any]:
    """Intervals (1-based, inclusive) where the depth is below `min_depth`, per contig, with the number of callable
    positions (depth >= min_depth) and the mean depth of each contig."""
    intervals: dict[str, list[list[int]]] = {}
    stats: dict[str, dict[str, Any]] = {}
    for contig, pos, depth in rows:
        s = stats.setdefault(contig, {"positions": 0, "callable": 0, "depth_sum": 0})
        s["positions"] += 1
        s["depth_sum"] += depth
        if depth >= min_depth:
            s["callable"] += 1
            continue
        runs = intervals.setdefault(contig, [])
        if runs and runs[-1][1] == pos - 1:
            runs[-1][1] = pos
        else:
            runs.append([pos, pos])
    contigs = {c: {"positions": s["positions"], "callable": s["callable"],
                   "mean_depth": round(s["depth_sum"] / s["positions"], 2) if s["positions"] else 0.0}
               for c, s in stats.items()}
    return {"min_depth": min_depth, "intervals": intervals, "contigs": contigs}


def nice_bin(length: int, max_bins: int = 300) -> int:
    raw = max(1, math.ceil(length / max_bins))
    exp = 10 ** max(0, len(str(raw)) - 1)
    for m in (1, 2, 5, 10):
        if m * exp >= raw:
            return m * exp
    return 10 * exp


def distribution(variants: Sequence[dict[str, Any]], lengths: dict[str, int]) -> dict[str, Any]:
    """PASS SNPs and PASS indels/other per bin of each contig (one bin width for all contigs)."""
    width = nice_bin(max(lengths.values(), default=1))
    out: dict[str, Any] = {"bin": width, "contigs": []}
    for contig, length in lengths.items():
        n = max(1, math.ceil(length / width))
        snp, other = [0] * n, [0] * n
        for v in variants:
            if v["contig"] == contig and v["pass"]:
                i = min(n - 1, (v["pos"] - 1) // width)
                (snp if v["type"] == "snp" else other)[i] += 1
        if any(snp) or any(other):
            out["contigs"].append({"contig": contig, "length": length, "snp": snp, "other": other})
    return out


def histogram(values: Iterable[float], edges: Sequence[float]) -> list[int]:
    counts = [0] * (len(edges) - 1)
    for v in values:
        i = bisect.bisect_right(edges, v) - 1
        if 0 <= i < len(counts):
            counts[i] += 1
        elif v >= edges[-1]:
            counts[-1] += 1
    return counts


def summarize(variants: Sequence[dict[str, Any]]) -> dict[str, Any]:
    passed = [v for v in variants if v["pass"]]
    depth_edges = [0, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 1000]
    af_edges = [round(x / 20, 2) for x in range(21)]
    return {
        "records": len(variants), "pass": len(passed),
        "by_type": {t: sum(1 for v in passed if v["type"] == t) for t in VARIANT_TYPES},
        "by_filter": dict(Counter(f for v in variants for f in v["filters"])),
        "by_effect": dict(Counter(v["effect"] or "none" for v in passed)),
        "start_codon_notes": sum(1 for v in passed if v.get("start_codon")),
        "after_stop": sum(1 for v in passed if v.get("after_stop")),
        "depth_histogram": {"edges": depth_edges, "pass": histogram((v["depth"] or 0 for v in passed), depth_edges),
                            "filtered": histogram((v["depth"] or 0 for v in variants if not v["pass"]), depth_edges)},
        "alt_fraction_histogram": {"edges": af_edges,
                                   "pass": histogram((v["alt_fraction"] for v in passed
                                                      if v["alt_fraction"] is not None), af_edges),
                                   "filtered": histogram((v["alt_fraction"] for v in variants
                                                          if not v["pass"] and v["alt_fraction"] is not None),
                                                         af_edges)},
    }


def _in_intervals(intervals: list[list[int]], starts: list[int], pos: int) -> bool:
    i = bisect.bisect_right(starts, pos) - 1
    return i >= 0 and intervals[i][0] <= pos <= intervals[i][1]


def snp_matrix(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The SNP sites of several samples called against one reference, each sample's base at every site and the
    pairwise SNP distances. A sample is {"id", "label", "variants" (its records), "low_depth" (low_depth_intervals'
    "intervals")}. See the module docstring for the definitions."""
    sites: dict[tuple[str, int], str] = {}
    per: list[dict[str, Any]] = []
    for s in samples:
        snps: dict[tuple[str, int], str] = {}
        masked: set[tuple[str, int]] = set()
        spans: dict[str, list[list[int]]] = {}
        for v in s["variants"]:
            if v["pass"] and v["type"] == "snp":
                snps[(v["contig"], v["pos"])] = v["alt"]
                sites[(v["contig"], v["pos"])] = v["ref"]
            elif not v["pass"]:
                masked.update((v["contig"], p) for p in range(v["pos"], v["end"] + 1))
            else:
                # The first base of a normalised indel is the shared, unchanged anchor base.
                lo = v["pos"] + (1 if v["ref"][:1] == v["alt"][:1] else 0)
                if lo <= v["end"]:
                    spans.setdefault(v["contig"], []).append([lo, v["end"]])
        low = {c: sorted(iv) for c, iv in (s.get("low_depth") or {}).items()}
        per.append({"snps": snps, "masked": masked, "low": low, "low_starts": {c: [a for a, _ in iv]
                                                                              for c, iv in low.items()},
                    "spans": {c: sorted(iv) for c, iv in spans.items()}})
    order = sorted(sites)
    alleles: list[list[str]] = []
    for p in per:
        row = []
        for key in order:
            contig, pos = key
            if key in p["snps"]:
                row.append(p["snps"][key])
            elif key in p["masked"] or any(a <= pos <= b for a, b in p["spans"].get(contig, ())) or \
                    _in_intervals(p["low"].get(contig, []), p["low_starts"].get(contig, []), pos):
                row.append("N")
            else:
                row.append(sites[key])
        alleles.append(row)
    n = len(samples)
    distances = [[0] * n for _ in range(n)]
    compared = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            d = c = 0
            for a, b in zip(alleles[i], alleles[j], strict=True):
                if a != "N" and b != "N":
                    c += 1
                    d += a != b
            distances[i][j] = distances[j][i] = d
            compared[i][j] = compared[j][i] = c
    core = sum(1 for k in range(len(order)) if all(row[k] != "N" for row in alleles))
    return {"samples": [{"id": s["id"], "label": s["label"]} for s in samples],
            "sites": [{"contig": c, "pos": p, "ref": sites[(c, p)]} for c, p in order],
            "alleles": ["".join(r) for r in alleles], "distances": distances, "compared_sites": compared,
            "core_sites": core,
            "missing": [row.count("N") for row in alleles]}
