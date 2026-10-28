"""Two SYNTHETIC assemblies of the synthetic genome with known differences, for QUAST fixtures and tests.

Usage: python3 make_assemblies.py <reference.fasta from scripts/make_synthetic_genome.py> <output folder>

edited.fasta (8 contigs) — every difference from the reference is placed on purpose:
  A  chromosome 1-140,000 with substitutions at 0-based positions 10,000, 50,000 and 90,000
  B  chromosome 140,001-300,000, reverse complement
  C  chromosome 20,001-30,000 joined to 240,001-250,000 (one relocation)
  D  plasmid rotated to start at position 5,001 (a circular replicon: not a misassembly)
  E  2,000 random bases (Python's random.Random(7)) with bases 1,001-1,050 replaced by N (unaligned)
  F, G, H  chromosome pieces of 400, 499 and 500 bp (below, just below and at QUAST's default --min-contig)
perfect.fasta (2 contigs): the chromosome rotated to start at position 1,001, and the plasmid.
"""
import random
import sys
from pathlib import Path


def read_fasta(path: Path) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    name = ""
    for line in Path(path).read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            out[name] = []
        else:
            out[name].append(line.strip())
    return {k: "".join(v) for k, v in out.items()}


def revcomp(seq: str) -> str:
    return seq.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def write(path: Path, records: list[tuple[str, str]]) -> None:
    path.write_text("".join(f">{name}\n{seq}\n" for name, seq in records))


def make_assemblies(reference: Path, outdir: Path) -> tuple[Path, Path]:
    ref = read_fasta(reference)
    chromosome, plasmid = ref["SYNTHETIC_chromosome"], ref["SYNTHETIC_plasmid"]
    a = list(chromosome[:140_000])
    for pos in (10_000, 50_000, 90_000):
        a[pos] = "ACGT"[("ACGT".index(a[pos]) + 1) % 4]
    rng = random.Random(7)
    unaligned = "".join(rng.choice("ACGT") for _ in range(2_000))
    unaligned = unaligned[:1_000] + "N" * 50 + unaligned[1_050:]
    outdir.mkdir(parents=True, exist_ok=True)
    edited, perfect = outdir / "edited.fasta", outdir / "perfect.fasta"
    write(edited, [
        ("SYNTHETIC_A_3_substitutions", "".join(a)),
        ("SYNTHETIC_B_reverse_strand", revcomp(chromosome[140_000:])),
        ("SYNTHETIC_C_relocation", chromosome[20_000:30_000] + chromosome[240_000:250_000]),
        ("SYNTHETIC_D_plasmid_rotated", plasmid[5_000:] + plasmid[:5_000]),
        ("SYNTHETIC_E_unaligned_50N", unaligned),
        ("SYNTHETIC_F_400bp", chromosome[100_000:100_400]),
        ("SYNTHETIC_G_499bp", chromosome[110_000:110_499]),
        ("SYNTHETIC_H_500bp", chromosome[120_000:120_500]),
    ])
    write(perfect, [("SYNTHETIC_chromosome_rotated", chromosome[1_000:] + chromosome[:1_000]),
                    ("SYNTHETIC_plasmid", plasmid)])
    return edited, perfect


if __name__ == "__main__":
    make_assemblies(Path(sys.argv[1]), Path(sys.argv[2]))
