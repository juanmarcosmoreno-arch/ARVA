"""Independent cross-check of ARVA statistics against SeqKit.

Tolerances reflect only SeqKit's output rounding (avg_len to 1 decimal, percentages
to 2 decimals). Quartiles are not compared: some SeqKit releases (e.g. 2.3.0)
report incorrect quartiles. GC is compared only when the file has no ambiguous
bases, because the two tools may treat N differently.
"""
from __future__ import annotations

from typing import Any

NOTE = (
    "Exact agreement is expected for counts and lengths; small tolerances only absorb SeqKit's "
    "rounding. Quartiles are not compared (incorrect in some SeqKit releases)."
)


def compare(arva: dict[str, Any], seqkit: dict[str, Any]) -> list[dict[str, Any]]:
    q = arva.get("quality") or {}
    rows: list[tuple[str, float | None, float | None, float]] = [
        ("Reads", arva["read_count"], seqkit.get("num_seqs"), 0),
        ("Total bases", arva["total_bases"], seqkit.get("sum_len"), 0),
        ("Minimum length", arva["min_length"], seqkit.get("min_len"), 0),
        ("Maximum length", arva["max_length"], seqkit.get("max_len"), 0),
        ("Mean length", arva["mean_length"], seqkit.get("avg_len"), 0.051),
        ("N50", arva["n50"], seqkit.get("N50"), 0),
    ]
    if q:
        rows += [
            ("Bases ≥ Q20 (%)", q["q20_bases_percent"], seqkit.get("Q20(%)"), 0.0051),
            ("Bases ≥ Q30 (%)", q["q30_bases_percent"], seqkit.get("Q30(%)"), 0.0051),
        ]
    gc_comparable = arva.get("ambiguous_bases", 0) == 0
    rows.append(("GC (%)", arva["gc_percent"], seqkit.get("GC(%)") if gc_comparable else None, 0.0051))

    out = []
    for metric, a, s, tol in rows:
        agrees = None if a is None or s is None else abs(float(a) - float(s)) <= tol
        out.append({"metric": metric, "arva": a, "tool": s, "tolerance": tol, "agrees": agrees})
    return out
