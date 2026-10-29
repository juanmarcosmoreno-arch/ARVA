#!/usr/bin/env python3
"""Derive the test inputs of the mlst fixtures from the downloaded NCBI genomes (README.md): every change is a
deliberate edit for a parser case, so these inputs are test constructs, not biology.

    python3 derive_inputs.py NC_007795.1.fasta NC_000913.3.fasta <mlst db/pubmlst folder> <output folder>

saureus_edited.fna, from NC_007795.1 (S. aureus NCTC 8325, ST8 = arcC 3, aroE 3, glpF 1, gmk 1, pta 4, tpi 4, yqiL 3):
  * arcC_3: the base in the middle of the allele replaced (A<->C, G<->T) -> a full-length inexact match;
  * gmk_1: the chromosome cut into two contigs 60 % into the allele -> a partial match on one contig;
  * tpi_4: the allele's bases removed -> no match;
  * yqiL_1 from the scheme's own allele file appended as an extra contig -> two exact yqiL alleles (1 and 3).
mixed.fna: both genomes in one file, as in a mixed culture.
"""
import sys
from pathlib import Path

SWAP = {"A": "C", "C": "A", "G": "T", "T": "G"}
COMP = str.maketrans("ACGTN", "TGCAN")


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records, name, seq = [], None, []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(seq)))
            name, seq = line[1:].split()[0], []
        elif line.strip():
            seq.append(line.strip().upper())
    if name is not None:
        records.append((name, "".join(seq)))
    return records


def allele(pubmlst: Path, scheme: str, locus: str, number: int) -> str:
    for name, seq in read_fasta(pubmlst / scheme / f"{locus}.tfa"):
        if name in (f"{locus}_{number}", f"{locus}-{number}"):
            return seq
    raise SystemExit(f"{scheme} {locus}_{number} not in the scheme's allele file")


def locate(genome: str, seq: str) -> int:
    hits = [genome.find(s) for s in (seq, seq.translate(COMP)[::-1])]
    hits = [h for h in hits if h >= 0]
    if len(hits) != 1 or genome.count(seq) + genome.count(seq.translate(COMP)[::-1]) != 1:
        raise SystemExit("the allele is not found exactly once")
    return hits[0]


def write(path: Path, records: list[tuple[str, str]]) -> None:
    with open(path, "w") as out:
        for name, seq in records:
            out.write(f">{name}\n" + "\n".join(seq[i:i + 80] for i in range(0, len(seq), 80)) + "\n")


def main() -> None:
    saureus, ecoli, pubmlst, out = (Path(a) for a in sys.argv[1:5])
    out.mkdir(parents=True, exist_ok=True)
    [(name, chrom)] = read_fasta(saureus)
    arc, gmk, tpi = (allele(pubmlst, "saureus", locus, n) for locus, n in (("arcC", 3), ("gmk", 1), ("tpi", 4)))
    p_arc, p_gmk, p_tpi = locate(chrom, arc), locate(chrom, gmk), locate(chrom, tpi)
    mid = p_arc + len(arc) // 2
    edits = sorted([("tpi", p_tpi), ("arc", mid)], key=lambda e: -e[1])
    for what, pos in edits:
        chrom = chrom[:pos] + chrom[pos + len(tpi):] if what == "tpi" else chrom[:pos] + SWAP[chrom[pos]] + chrom[pos + 1:]
    p_gmk = locate(chrom, gmk)
    cut = p_gmk + int(len(gmk) * 0.6)
    records = [(f"{name}_part1", chrom[:cut]), (f"{name}_part2", chrom[cut:]),
               ("yqiL_1_from_scheme", allele(pubmlst, "saureus", "yqiL", 1))]
    write(out / "saureus_edited.fna", records)
    write(out / "mixed.fna", read_fasta(saureus) + read_fasta(ecoli))
    print(f"arcC_3 at {p_arc + 1}: base {mid + 1} replaced; tpi_4 at {p_tpi + 1} removed ({len(tpi)} bp); "
          f"cut at {cut} (gmk_1 starts at {p_gmk + 1} after the deletion, {len(gmk)} bp)")


if __name__ == "__main__":
    main()
