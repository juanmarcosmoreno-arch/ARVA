#!/usr/bin/env python3
"""Derive the cut test input of the ABRicate fixtures from the downloaded NCBI genome (README.md): the cuts are
deliberate edits for parser cases, so this input is a test construct, not biology.

    python3 derive_inputs.py NC_002745.2.fasta NC_003140.1.fasta <output folder>

n315_cut.fna, from S. aureus N315 (chromosome NC_002745.2 and plasmid pN315 NC_003140.1), with the coordinates
ABRicate 1.4.0 reported for the unedited genome against its VFDB (n315.vfdb.tsv):
  * adsA (chromosome 31006..33324, + strand): the chromosome cut 10 % into the gene, so 90 % of it lies at the
    start of the next contig (a partial hit at a contig end);
  * cap8D (chromosome 169566..171389, + strand): cut halfway, so each contig holds half of the gene (two partial
    pieces, reported only when --mincov is at most 50).
"""
import sys
from pathlib import Path


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


def write(path: Path, records: list[tuple[str, str]]) -> None:
    with open(path, "w") as out:
        for name, seq in records:
            out.write(f">{name}\n" + "\n".join(seq[i:i + 80] for i in range(0, len(seq), 80)) + "\n")


def main() -> None:
    chrom_path, plasmid_path, out = (Path(a) for a in sys.argv[1:4])
    out.mkdir(parents=True, exist_ok=True)
    [(chrom_name, chrom)] = read_fasta(chrom_path)
    [(plasmid_name, plasmid)] = read_fasta(plasmid_path)
    first = 31006 - 1 + (33324 - 31006 + 1) // 10
    second = 169566 - 1 + (171389 - 169566 + 1) // 2
    write(out / "n315_cut.fna", [(f"{chrom_name}_part1", chrom[:first]), (f"{chrom_name}_part2", chrom[first:second]),
                                 (f"{chrom_name}_part3", chrom[second:]), (plasmid_name, plasmid)])
    print(f"chromosome cut after bases {first} (inside adsA) and {second} (inside cap8D)")


if __name__ == "__main__":
    main()
