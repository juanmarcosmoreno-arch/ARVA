#!/usr/bin/env python3
"""Write a SYNTHETIC draft assembly with known errors, for testing and demonstrating polishing.

Reads the reference.fasta of scripts/make_synthetic_genome.py and writes draft.fasta: the same replicons, renamed
contig_1, contig_2, ..., with substitutions, insertions and deletions at fixed fractions of each replicon's length
(outside the chromosome's repeat copies at 20 % and 60 % and away from the ends). edits.tsv lists every edit in
reference coordinates (the substituted base, the first deleted base, or the base after which bases were inserted); a
perfect polisher would undo all of them.

    python3 scripts/make_polishing_draft.py examples/synthetic-genome/reference.fasta examples/polishing-draft
"""
from __future__ import annotations

import argparse
from pathlib import Path

FASTA_WIDTH = 80
SWAP = {"A": "C", "C": "G", "G": "T", "T": "A"}
# (fraction of the replicon length, kind, inserted bases or deleted length); the first replicon gets CHROMOSOME, the
# others PLASMID.
CHROMOSOME = (
    (0.050, "substitution", None), (0.123, "substitution", None), (0.300, "substitution", None),
    (0.457, "substitution", None), (0.700, "substitution", None), (0.854, "substitution", None),
    (0.150, "insertion", "A"), (0.350, "insertion", "G"), (0.500, "insertion", "TT"), (0.660, "insertion", "C"),
    (0.180, "deletion", 1), (0.400, "deletion", 1), (0.555, "deletion", 3), (0.900, "deletion", 1),
)
PLASMID = ((0.500, "substitution", None), (0.625, "deletion", 1))


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, list[str]]] = []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            records.append((line[1:].split()[0], []))
        elif records:
            records[-1][1].append(line.strip().upper())
    return [(name, "".join(parts)) for name, parts in records]


def edit(seq: str, plan) -> tuple[str, list[tuple[int, str, str, str]]]:
    """The edited sequence and the edits as (1-based reference position, kind, reference bases, draft bases)."""
    s = list(seq)
    done = []
    for fraction, kind, value in sorted(plan, key=lambda e: -e[0]):
        p = round(fraction * len(seq))
        if kind == "substitution":
            done.append((p + 1, kind, s[p], SWAP[s[p]]))
            s[p] = SWAP[s[p]]
        elif kind == "insertion":
            done.append((p, kind, "", value))
            s[p:p] = list(value)
        else:
            done.append((p + 1, kind, "".join(s[p:p + value]), ""))
            del s[p:p + value]
    return "".join(s), sorted(done)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", type=Path)
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args(argv)
    records = read_fasta(args.reference)
    if not records or not all("SYNTHETIC" in name for name, _ in records):
        raise SystemExit("expected the reference.fasta of scripts/make_synthetic_genome.py (SYNTHETIC replicons)")
    args.outdir.mkdir(parents=True, exist_ok=True)
    rows = ["replicon\tcontig\treference_position\tkind\treference_bases\tdraft_bases"]
    with open(args.outdir / "draft.fasta", "w") as fh:
        for n, (name, seq) in enumerate(records, 1):
            draft, done = edit(seq, CHROMOSOME if n == 1 else PLASMID)
            fh.write(f">contig_{n}\n")
            fh.writelines(draft[i:i + FASTA_WIDTH] + "\n" for i in range(0, len(draft), FASTA_WIDTH))
            rows += [f"{name}\tcontig_{n}\t{p}\t{k}\t{r or '.'}\t{d or '.'}" for p, k, r, d in done]
    (args.outdir / "edits.tsv").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
