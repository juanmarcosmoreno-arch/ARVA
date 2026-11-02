"""Comparative genomics: ANI matrices, a similarity ordering for heatmaps, genome layouts and what ARVA derives from
whole-genome alignment blocks (per-pair summaries, conservation along a reference).

What each value is, and what it is not:

* ANI values are the tools' own (skani triangle, FastANI all-vs-all). A pair a tool did not report (screened out,
  or below its aligned-fraction cut-off) stays None: it is never filled with a guess.
* `similarity_order` is average-linkage (UPGMA) clustering of 100 - ANI, used only to place similar genomes next
  to each other in a heatmap. It is similarity clustering, not a phylogeny: ANI is not an evolutionary distance
  model, and the order says nothing about ancestry. For the ordering only, a pair without a value is placed at the
  largest distance (100), and a pair with values in both directions (FastANI) uses their mean.
* Alignment blocks are the aligner's rows (minimap2 -c PAF, or show-coords) in 1-based inclusive coordinates.
  Conservation along a reference is ARVA's summary of them: for each window, the share of reference bases covered
  by at least one block, and the mean, over those bases, of the highest identity of a block covering each base.
  Blocks are similarity, not evidence of descent or of transfer.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

MISSING_DISTANCE = 100.0
MAX_WINDOWS = 2000
MIN_WINDOW = 1000


def contig_lengths(records: Iterable[tuple[bytes, bytes, Any, int]]) -> list[dict[str, Any]]:
    """(name, length) of each FASTA record, the name being the header's first word as aligners report it."""
    out = []
    for header, seq, _q, _line in records:
        name = header[1:].split(maxsplit=1)[0].decode("utf-8", "replace") if header[1:].strip() else ""
        out.append({"name": name, "length": len(seq)})
    return out


def layout(contigs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Each contig's offset when the genome's contigs are drawn end to end in file order."""
    offsets, total = {}, 0
    for c in contigs:
        offsets[c["name"]] = total
        total += int(c["length"])
    return {"offsets": offsets, "total": total}


def ani_matrix(ids: Sequence[str], pairs: Iterable[Mapping[str, Any]], directional: bool) -> dict[str, Any]:
    """Square matrices indexed like `ids`: ani[i][j] is the ANI of genome i (query) against genome j (reference) and
    af[i][j] the share of genome i aligned in that comparison. Undirected pairs (skani) fill both cells; directional
    ones (FastANI) only their own. Missing pairs and the diagonal (unless a tool reported it) stay None."""
    index = {g: i for i, g in enumerate(ids)}
    n = len(ids)
    ani: list[list[float | None]] = [[None] * n for _ in range(n)]
    af: list[list[float | None]] = [[None] * n for _ in range(n)]
    for p in pairs:
        q, r = index[p["query"]], index[p["reference"]]
        ani[q][r], af[q][r] = p["ani"], p.get("af_query")
        if not directional:
            ani[r][q], af[r][q] = p["ani"], p.get("af_reference")
    return {"ids": list(ids), "ani": ani, "af": af, "directional": directional}


def _pair_distance(ani: list[list[float | None]], i: int, j: int) -> float:
    values = [v for v in (ani[i][j], ani[j][i]) if v is not None]
    return MISSING_DISTANCE if not values else 100.0 - sum(values) / len(values)


def similarity_order(ani: list[list[float | None]]) -> dict[str, Any]:
    """Average-linkage clustering of 100 - ANI (see average_linkage)."""
    n = len(ani)
    dist = [[0.0 if i == j else _pair_distance(ani, i, j) for j in range(n)] for i in range(n)]
    return average_linkage(dist, "average linkage (UPGMA) on 100 - ANI")


def average_linkage(dist: Sequence[Sequence[float]], method: str) -> dict[str, Any]:
    """Average-linkage (UPGMA) clustering of a symmetric distance matrix: the leaf order and the merges ([a, b,
    distance, size], clusters numbered as in SciPy's linkage: leaves 0..n-1, then n, n+1, ...). Ties merge the
    earliest clusters first."""
    n = len(dist)
    if n == 0:
        return {"order": [], "merges": [], "method": method}
    members: dict[int, list[int]] = {i: [i] for i in range(n)}
    pair = {(i, j): float(dist[i][j]) for i in range(n) for j in range(i + 1, n)}
    merges: list[list[Any]] = []

    def d(a: int, b: int) -> float:
        return pair[(a, b) if a < b else (b, a)]

    while len(members) > 1:
        keys = sorted(members)
        a, b = min(((x, y) for k, x in enumerate(keys) for y in keys[k + 1:]), key=lambda p: (d(*p), p))
        new = n + len(merges)
        size_a, size_b = len(members[a]), len(members[b])
        for c in members:
            if c not in (a, b):
                pair[(c, new)] = (d(a, c) * size_a + d(b, c) * size_b) / (size_a + size_b)
        merges.append([a, b, round(d(a, b), 6), size_a + size_b])
        members[new] = members.pop(a) + members.pop(b)
    return {"order": next(iter(members.values())), "merges": merges, "method": method}


def auto_window(total: int) -> int:
    """A window (a multiple of 1 kb, at least 1 kb) giving at most MAX_WINDOWS windows over `total` bases."""
    return max(MIN_WINDOW, math.ceil(total / MAX_WINDOWS / MIN_WINDOW) * MIN_WINDOW)


def pair_summary(blocks: Sequence[Mapping[str, Any]], ref_total: int, query_total: int) -> dict[str, Any]:
    """Bases of each genome covered by at least one block (overlaps counted once), the block-length-weighted mean
    identity, and the number of blocks on each strand."""
    def covered(key: str) -> int:
        spans: dict[str, list[tuple[int, int]]] = {}
        for b in blocks:
            spans.setdefault(b[key], []).append((b[f"{key}_start"], b[f"{key}_end"]))
        total = 0
        for intervals in spans.values():
            end = 0
            for s, e in sorted(intervals):
                if e > end:
                    total += e - max(s - 1, end)
                    end = e
        return total

    weight = sum(b["length"] for b in blocks)
    ref_cov, query_cov = covered("ref"), covered("query")
    return {
        "blocks": len(blocks),
        "forward": sum(1 for b in blocks if b["strand"] == "+"),
        "reverse": sum(1 for b in blocks if b["strand"] == "-"),
        "ref_aligned": ref_cov, "query_aligned": query_cov,
        "ref_fraction": round(ref_cov / ref_total, 6) if ref_total else None,
        "query_fraction": round(query_cov / query_total, 6) if query_total else None,
        "identity": round(sum(b["identity"] * b["length"] for b in blocks) / weight, 3) if weight else None,
    }


def conservation(ref_contigs: Sequence[Mapping[str, Any]], blocks: Sequence[Mapping[str, Any]],
                 window: int) -> list[dict[str, Any]]:
    """Per reference window: covered share (0-1) and mean best identity of the covered bases (None if none)."""
    by_contig: dict[str, list[Mapping[str, Any]]] = {}
    for b in blocks:
        by_contig.setdefault(b["ref"], []).append(b)
    out = []
    for c in ref_contigs:
        length = int(c["length"])
        best = np.zeros(length, dtype=np.float32)
        for b in by_contig.get(c["name"], ()):
            s, e = max(b["ref_start"] - 1, 0), min(b["ref_end"], length)
            np.maximum(best[s:e], np.float32(b["identity"]), out=best[s:e])
        for start in range(0, length, window):
            seg = best[start:start + window]
            hit = seg[seg > 0]
            out.append({"contig": c["name"], "start": start + 1, "end": start + len(seg),
                        "covered": round(len(hit) / len(seg), 4),
                        "identity": round(float(hit.mean()), 3) if len(hit) else None})
    return out
