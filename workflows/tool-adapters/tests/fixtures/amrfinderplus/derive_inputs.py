#!/usr/bin/env python3
"""Derive the edited test input of the AMRFinderPlus fixtures from the downloaded NCBI genome (README.md): every
change is a deliberate edit for a parser case, so this input is a test construct, not biology.

    python3 derive_inputs.py NC_002745.2.fasta NC_003140.1.fasta <output folder>

n315_edited.fna, from S. aureus N315 (chromosome NC_002745.2 and plasmid pN315 NC_003140.1), with the coordinates
AMRFinderPlus 4.2.7 reported for the unedited genome (n315.tsv, n315.mutation_all.tsv):
  * gyrA (chromosome 7005..9665, + strand): the second base of codon 84 changed (TCA, Ser -> TTA, Leu): a known
    point mutation, gyrA_S84L;
  * mecA (chromosome 45034..47037, - strand): the chromosome cut into two contigs 60 % into the gene: a partial gene
    at a contig end;
  * blaZ (plasmid 7948..8790, - strand): codon 100 of the gene (counted from its start on the - strand) replaced by
    a stop codon: an internal stop.
"""
import sys
from pathlib import Path

COMP = str.maketrans("ACGT", "TGCA")


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
    codon = 7005 - 1 + (84 - 1) * 3
    if chrom[codon:codon + 3] != "TCA":
        raise SystemExit(f"gyrA codon 84 is {chrom[codon:codon + 3]}, not TCA")
    chrom = chrom[:codon + 1] + "T" + chrom[codon + 2:]
    stop_end = 8790 - (100 - 1) * 3
    old = plasmid[stop_end - 3:stop_end]
    plasmid = plasmid[:stop_end - 3] + "TAA".translate(COMP)[::-1] + plasmid[stop_end:]
    cut = 47037 - int((47037 - 45034 + 1) * 0.6)
    write(out / "n315_edited.fna", [(f"{chrom_name}_part1", chrom[:cut]), (f"{chrom_name}_part2", chrom[cut:]),
                                    (plasmid_name, plasmid)])
    print(f"gyrA codon 84 at {codon + 1}: TCA -> TTA; blaZ codon 100 ({stop_end - 2}..{stop_end}, - strand) "
          f"{old.translate(COMP)[::-1]} -> TAA; chromosome cut after base {cut} (inside mecA)")


if __name__ == "__main__":
    main()
