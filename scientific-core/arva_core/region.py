"""Genome regions across genomes: the matches of a query sequence in a genome (Custom Gene Investigation) and the
gene neighbourhoods around a gene of interest in several genomes (Genome Region Explorer).

Everything here works on BLAST+ HSPs (arva_tools.blast.parse_tabular: 1-based inclusive positions, s_lo <= s_hi,
sstrand) and on ARVA's annotation features (arva_core.annotation). Thresholds are always the caller's.

ARVA's rules (heuristics, and labelled so where results are shown):

* Matches: HSPs of one query on one subject sequence and strand are chained into one match when they are in the same
  order on the query and on the subject, overlap by at most OVERLAP_FRACTION of the shorter piece on either, and are
  at most `max_gap` bp apart on the subject. A match of several HSPs is "split": something interrupts the copy (an
  insertion such as an IS element, a frameshift or stop codon, an assembly break) and the HSPs alone do not say
  what. A one-HSP match covering at least `complete_coverage` % of the query is "complete", otherwise "partial". An
  HSP over bases a better match already uses (another alignment of the same bases) is not counted as a copy.
* A match within EDGE_BP of either end of its sequence is flagged: the copy may continue past the assembled sequence.
* Homology groups (Region Explorer): single-linkage clusters of the proteins of all windows, two proteins linked when
  a blastp HSP has at least `min_identity` % identity and covers at least `min_coverage` % of both. Group colours in
  a figure mean shared similarity above those thresholds, not orthology.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Any

OVERLAP_FRACTION = 0.2
EDGE_BP = 20
DRAWN_TYPES = frozenset({"cds", "sorf", "trna", "tmrna", "rrna", "ncrna", "ncrna_region", "crispr", "oric", "oriv",
                         "orit", "other"})
CODING = frozenset({"cds", "sorf"})


def union_length(intervals: Iterable[tuple[int, int]]) -> int:
    total, cur_lo, cur_hi = 0, None, None
    for lo, hi in sorted(intervals):
        if cur_hi is None or lo > cur_hi + 1:
            if cur_hi is not None:
                total += cur_hi - cur_lo + 1
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None:
        total += cur_hi - cur_lo + 1
    return total


def _overlap(a_lo: int, a_hi: int, b_lo: int, b_hi: int) -> int:
    return max(0, min(a_hi, b_hi) - max(a_lo, b_lo) + 1)


def _chainable(pieces: list[dict[str, Any]], max_gap: int) -> bool:
    """Consecutive pieces (sorted on the query) advance on the subject in the strand's direction, with small
    overlaps only and gaps of at most `max_gap` bp."""
    pieces = sorted(pieces, key=lambda h: h["qstart"])
    for a, b in pairwise(pieces):
        q_tol = OVERLAP_FRACTION * min(a["qend"] - a["qstart"] + 1, b["qend"] - b["qstart"] + 1)
        s_tol = OVERLAP_FRACTION * min(a["s_hi"] - a["s_lo"] + 1, b["s_hi"] - b["s_lo"] + 1)
        if b["qstart"] - a["qend"] - 1 < -q_tol:
            return False
        gap = b["s_lo"] - a["s_hi"] - 1 if a["sstrand"] == "+" else a["s_lo"] - b["s_hi"] - 1
        if gap < -s_tol or gap > max_gap:
            return False
    return True


def chain_matches(hsps: Sequence[dict[str, Any]], *, min_identity: float, min_coverage: float,
                  complete_coverage: float, max_gap: int) -> list[dict[str, Any]]:
    """The matches of one query in one genome (see the module's rules), best first. Identity is over the aligned
    columns of all pieces (sum of identical / sum of alignment lengths); coverage is the share of the query covered
    by the union of the pieces."""
    kept = sorted((h for h in hsps if h["pident"] >= min_identity),
                  key=lambda h: (-h["bitscore"], h["evalue"], h["sseqid"], h["s_lo"]))
    groups: list[list[dict[str, Any]]] = []
    for h in kept:
        same = [g for g in groups if g[0]["sseqid"] == h["sseqid"]]
        if any(_overlap(p["s_lo"], p["s_hi"], h["s_lo"], h["s_hi"])
               > OVERLAP_FRACTION * min(h["s_hi"] - h["s_lo"] + 1, p["s_hi"] - p["s_lo"] + 1)
               for g in same for p in g):
            continue
        for g in same:
            if g[0]["sstrand"] == h["sstrand"] and _chainable([*g, h], max_gap):
                g.append(h)
                break
        else:
            groups.append([h])
    matches = []
    for g in groups:
        pieces = sorted(g, key=lambda h: h["qstart"])
        qlen, slen = pieces[0]["qlen"], pieces[0]["slen"]
        coverage = round(100 * union_length((p["qstart"], p["qend"]) for p in pieces) / qlen, 2)
        if coverage < min_coverage:
            continue
        s_lo, s_hi = min(p["s_lo"] for p in pieces), max(p["s_hi"] for p in pieces)
        kind = "split" if len(pieces) > 1 else ("complete" if coverage >= complete_coverage else "partial")
        matches.append({
            "subject": pieces[0]["sseqid"], "subject_length": slen, "start": s_lo, "end": s_hi,
            "strand": pieces[0]["sstrand"], "kind": kind, "query_coverage": coverage,
            "identity": round(100 * sum(p["nident"] for p in pieces) / sum(p["length"] for p in pieces), 2),
            "evalue": min(p["evalue"] for p in pieces), "bitscore": round(sum(p["bitscore"] for p in pieces), 1),
            "query_start": min(p["qstart"] for p in pieces), "query_end": max(p["qend"] for p in pieces),
            "query_length": qlen, "at_contig_edge": s_lo <= EDGE_BP or s_hi > slen - EDGE_BP,
            "pieces": [{k: p[k] for k in ("qstart", "qend", "s_lo", "s_hi", "pident", "length", "evalue",
                                          "bitscore")} for p in pieces],
        })
    matches.sort(key=lambda m: (-m["bitscore"], m["subject"], m["start"]))
    for n, m in enumerate(matches, 1):
        m["copy"] = n
    return matches


def redundant_hsps(hsps: Sequence[dict[str, Any]], matches: Sequence[dict[str, Any]], min_identity: float) -> int:
    """HSPs above the identity threshold that are not part of any reported match."""
    used = sum(len(m["pieces"]) for m in matches)
    return sum(1 for h in hsps if h["pident"] >= min_identity) - used


def window(start: int, end: int, flank: int, length: int) -> dict[str, Any]:
    """The window of `flank` bp on each side of [start, end] on a linear reading of a sequence of `length` bp."""
    lo, hi = start - flank, end + flank
    return {"start": max(1, lo), "end": min(length, hi), "clipped_left": lo < 1, "clipped_right": hi > length}


def to_relative(pos_lo: int, pos_hi: int, anchor_start: int, anchor_end: int, flip: bool) -> tuple[int, int]:
    """Positions on a track whose origin is the start of the gene of interest, which points right: a flipped track
    is read on the other strand, so the anchor's end becomes the origin."""
    if flip:
        return anchor_end - pos_hi, anchor_end - pos_lo
    return pos_lo - anchor_start, pos_hi - anchor_start


def track_features(features: Iterable[dict[str, Any]], contig: str, lo: int, hi: int, anchor_start: int,
                   anchor_end: int, flip: bool) -> list[dict[str, Any]]:
    """The drawable features of one window, clipped to it (`clipped`: part of the feature lies outside), in
    relative coordinates. A feature across the origin of a circular sequence is drawn up to the window's edge."""
    out = []
    for f in features:
        if f["contig"] != contig or f["type"] not in DRAWN_TYPES:
            continue
        start, end = (f["start"], f["end"]) if not f.get("edge") else (f["start"], hi)
        if end < lo or start > hi:
            continue
        a, b = max(start, lo), min(end, hi)
        rel = to_relative(a, b, anchor_start, anchor_end, flip)
        strand = f["strand"] if not flip else {"+": "-", "-": "+"}.get(f["strand"], f["strand"])
        out.append({"id": f["id"], "locus_tag": f.get("locus_tag"), "gene": f.get("gene"), "product": f.get("product"),
                    "type": f["type"], "start": f["start"], "end": f["end"], "strand": f["strand"],
                    "length": f.get("length"), "pseudo": bool(f.get("pseudo")), "rel_start": rel[0],
                    "rel_end": rel[1], "rel_strand": strand, "clipped": a != start or b != end or bool(f.get("edge"))})
    out.sort(key=lambda x: x["rel_start"])
    return out


def best_protein_hit(hsps: Sequence[dict[str, Any]], min_identity: float, min_coverage: float) -> list[dict[str, Any]]:
    """blastp hits of one query protein, each subject protein once (its best HSP), passing identity and coverage
    of both proteins; best first."""
    best: dict[str, dict[str, Any]] = {}
    for h in hsps:
        qcov = 100 * (h["qend"] - h["qstart"] + 1) / h["qlen"]
        scov = 100 * (h["s_hi"] - h["s_lo"] + 1) / h["slen"]
        if h["pident"] < min_identity or qcov < min_coverage or scov < min_coverage:
            continue
        if h["sseqid"] not in best or h["bitscore"] > best[h["sseqid"]]["bitscore"]:
            best[h["sseqid"]] = {"subject": h["sseqid"], "identity": h["pident"], "query_coverage": round(qcov, 2),
                                 "subject_coverage": round(scov, 2), "evalue": h["evalue"], "bitscore": h["bitscore"]}
    return sorted(best.values(), key=lambda x: (-x["bitscore"], x["subject"]))


def homology_groups(proteins: Sequence[str], hsps: Iterable[dict[str, Any]], min_identity: float,
                    min_coverage: float) -> dict[str, int]:
    """Single-linkage groups of `proteins` from all-against-all blastp HSPs; groups numbered from 0 by size (largest
    first), then by first appearance. Proteins without a qualifying HSP form groups of one."""
    parent = {p: p for p in proteins}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for h in hsps:
        q, s = h["qseqid"], h["sseqid"]
        if q == s or q not in parent or s not in parent:
            continue
        qcov = 100 * (h["qend"] - h["qstart"] + 1) / h["qlen"]
        scov = 100 * (h["s_hi"] - h["s_lo"] + 1) / h["slen"]
        if h["pident"] >= min_identity and qcov >= min_coverage and scov >= min_coverage:
            parent[find(q)] = find(s)
    members: dict[str, list[str]] = {}
    for p in proteins:
        members.setdefault(find(p), []).append(p)
    ordered = sorted(members.values(), key=lambda m: (-len(m), proteins.index(m[0])))
    return {p: n for n, m in enumerate(ordered) for p in m}


def group_name(features: Sequence[dict[str, Any]]) -> str | None:
    """The gene name most of a group's features carry, else their most common informative product."""
    genes = Counter(f["gene"] for f in features if f.get("gene"))
    if genes:
        return genes.most_common(1)[0][0]
    products = Counter(f["product"] for f in features
                       if f.get("product") and f["product"].lower() != "hypothetical protein")
    return products.most_common(1)[0][0] if products else None


def links(hsps: Iterable[dict[str, Any]], upper: dict[str, Any], lower: dict[str, Any], min_identity: float,
          min_length: int) -> list[dict[str, Any]]:
    """blastn HSPs between the window sequences of two neighbouring tracks (query = upper window, subject = lower
    window, both read forward from the window's start) in each track's relative coordinates."""
    out = []
    for h in hsps:
        if h["pident"] < min_identity or h["length"] < min_length:
            continue
        a = to_relative(upper["start"] + h["qstart"] - 1, upper["start"] + h["qend"] - 1, upper["anchor_start"],
                        upper["anchor_end"], upper["flipped"])
        b = to_relative(lower["start"] + h["s_lo"] - 1, lower["start"] + h["s_hi"] - 1, lower["anchor_start"],
                        lower["anchor_end"], lower["flipped"])
        inverted = (h["sstrand"] == "-") != (upper["flipped"] != lower["flipped"])
        out.append({"upper_start": a[0], "upper_end": a[1], "lower_start": b[0], "lower_end": b[1],
                    "identity": h["pident"], "length": h["length"], "inverted": inverted})
    out.sort(key=lambda x: -x["length"])
    return out
