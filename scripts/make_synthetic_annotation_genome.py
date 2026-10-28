#!/usr/bin/env python3
"""Generate a SYNTHETIC genome with gene-like open reading frames, for annotation tests and demos.

Nothing here is biological data: every sequence is random, every FASTA header contains the word SYNTHETIC,
and nothing an annotator reports for it (gene calls, products, RNAs, repeats) describes a real organism.

The sequence is built so that gene finders have something to find:

* ORFs: ATG, a random number of codons drawn uniformly from the 61 sense codons (so no in-frame stop), then
  TAA, TAG or TGA; each is preceded by a Shine-Dalgarno-like motif (AGGAGG) 6-9 bp upstream of the start and
  placed on either strand. Random sequence between ORFs holds stops in every frame, so long ORFs exist only
  where they were planted.
* One CRISPR-like array on the chromosome: a random 30 bp repeat, copied N times with random 35 bp spacers.
* One assembly gap on the chromosome: a run of N.
* A second, smaller sequence ("plasmid") with a few more ORFs.
* Optionally (--insert FASTA) given sequences placed verbatim between chromosome genes, e.g. sequences sampled
  from RNA covariance models with Infernal's cmemit, and (--back-translate FASTA) given protein sequences
  turned into ORFs with a random synonymous codon for every residue, so a similarity search has something to
  find. What an annotator then reports for them reflects that construction, not biology.

The same seed and parameters give the same files on every Python version (random.Random with an integer seed).
Besides the FASTA, a TSV lists every planted ORF, the array and the gap with 1-based inclusive coordinates.

    python3 scripts/make_synthetic_annotation_genome.py examples/synthetic-annotation
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

BASES = "ACGT"
COMPLEMENT = str.maketrans("ACGTN", "TGCAN")
STOPS = ("TAA", "TAG", "TGA")
SENSE = tuple(a + b + c for a in BASES for b in BASES for c in BASES if a + b + c not in STOPS)
RBS = "AGGAGG"
# The standard genetic code in TCAG order (translation table 11 has the same codons; only its starts differ).
_TCAG = "TCAG"
_AMINO = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
CODONS_OF: dict[str, list[str]] = {}
for _i, _aa in enumerate(_AMINO):
    CODONS_OF.setdefault(_aa, []).append(_TCAG[_i // 16] + _TCAG[_i // 4 % 4] + _TCAG[_i % 4])
FASTA_WIDTH = 80
OUTPUTS = ("genome.fasta", "planted_features.tsv")


@dataclass(frozen=True)
class Params:
    seed: int = 20261028
    chromosome_genes: int = 120
    plasmid_genes: int = 8
    min_codons: int = 100
    max_codons: int = 450
    min_spacer: int = 60
    max_spacer: int = 250
    crispr_repeats: int = 7
    gap_length: int = 100

    def errors(self) -> list[str]:
        out = []
        if not 1 <= self.chromosome_genes <= 5_000:
            out.append("--chromosome-genes must be 1-5,000")
        if not 0 <= self.plasmid_genes <= 1_000:
            out.append("--plasmid-genes must be 0-1,000")
        if not 30 <= self.min_codons <= self.max_codons <= 3_000:
            out.append("codon counts must satisfy 30 <= --min-codons <= --max-codons <= 3,000")
        if not 20 <= self.min_spacer <= self.max_spacer <= 5_000:
            out.append("spacers must satisfy 20 <= --min-spacer <= --max-spacer <= 5,000")
        if not 3 <= self.crispr_repeats <= 50:
            out.append("--crispr-repeats must be 3-50")
        if not 1 <= self.gap_length <= 10_000:
            out.append("--gap-length must be 1-10,000")
        return out


def revcomp(seq: str) -> str:
    return seq.translate(COMPLEMENT)[::-1]


class Builder:
    def __init__(self, rng: random.Random, params: Params, name: str):
        self.rng, self.p, self.name = rng, params, name
        self.parts: list[str] = []
        self.length = 0
        self.features: list[dict] = []

    def add(self, seq: str) -> int:
        """Append and return the 1-based start of the appended piece."""
        start = self.length + 1
        self.parts.append(seq)
        self.length += len(seq)
        return start

    def random_dna(self, n: int) -> str:
        return "".join(self.rng.choice(BASES) for _ in range(n))

    def spacer(self) -> None:
        self.add(self.random_dna(self.rng.randint(self.p.min_spacer, self.p.max_spacer)))

    def orf(self, index: int) -> None:
        codons = self.rng.randint(self.p.min_codons, self.p.max_codons)
        cds = "ATG" + "".join(self.rng.choice(SENSE) for _ in range(codons)) + self.rng.choice(STOPS)
        upstream = RBS + self.random_dna(self.rng.randint(6, 9))
        strand = self.rng.choice("+-")
        block = upstream + cds if strand == "+" else revcomp(upstream + cds)
        start = self.add(block)
        cds_start = start + len(upstream) if strand == "+" else start
        self.features.append({"sequence": self.name, "type": "orf", "id": f"{self.name}_orf{index:04d}",
                              "start": cds_start, "end": cds_start + len(cds) - 1, "strand": strand,
                              "length": len(cds)})

    def back_translated(self, name: str, protein: str) -> None:
        """An ORF encoding `protein` (a leading M becomes the ATG start), with a random synonymous codon per
        residue, preceded by the same Shine-Dalgarno-like motif, on the + strand."""
        residues = protein[1:] if protein.startswith("M") else protein
        cds = "ATG" + "".join(self.rng.choice(CODONS_OF[aa]) for aa in residues) + self.rng.choice(STOPS)
        upstream = RBS + self.random_dna(self.rng.randint(6, 9))
        start = self.add(upstream + cds) + len(upstream)
        self.features.append({"sequence": self.name, "type": "back_translated_orf", "id": name, "start": start,
                              "end": start + len(cds) - 1, "strand": "+", "length": len(cds)})

    def insert(self, name: str, seq: str) -> None:
        start = self.add(seq)
        self.features.append({"sequence": self.name, "type": "inserted_sequence", "id": name, "start": start,
                              "end": start + len(seq) - 1, "strand": "+", "length": len(seq)})

    def crispr(self) -> None:
        repeat = self.random_dna(30)
        units = [repeat]
        for _ in range(self.p.crispr_repeats - 1):
            units += [self.random_dna(35), repeat]
        array = "".join(units)
        start = self.add(array)
        self.features.append({"sequence": self.name, "type": "crispr_like_array", "id": f"{self.name}_array",
                              "start": start, "end": start + len(array) - 1, "strand": ".", "length": len(array)})

    def gap(self) -> None:
        start = self.add("N" * self.p.gap_length)
        self.features.append({"sequence": self.name, "type": "gap", "id": f"{self.name}_gap", "start": start,
                              "end": start + self.p.gap_length - 1, "strand": ".", "length": self.p.gap_length})

    @property
    def sequence(self) -> str:
        return "".join(self.parts)


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, list[str]]] = []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            records.append((line[1:].split()[0], []))
        elif records:
            records[-1][1].append(line.strip().upper())
    return [(name, "".join(parts)) for name, parts in records]


def build(params: Params, inserts: list[tuple[str, str]] = (), proteins: list[tuple[str, str]] = ()) -> list[Builder]:
    """Inserted sequences and back-translated proteins are spread evenly among the chromosome's genes."""
    rng = random.Random(params.seed)
    chromosome = Builder(rng, params, "SYNTHETIC_annotation_chromosome")
    extras = [("insert", *r) for r in inserts] + [("protein", *r) for r in proteins]
    every = max(1, params.chromosome_genes // (len(extras) + 1))
    for i in range(1, params.chromosome_genes + 1):
        chromosome.spacer()
        chromosome.orf(i)
        if extras and i % every == 0:
            kind, name, seq = extras.pop(0)
            chromosome.spacer()
            (chromosome.insert if kind == "insert" else chromosome.back_translated)(name, seq)
        if i == params.chromosome_genes // 3:
            chromosome.spacer()
            chromosome.crispr()
        if i == 2 * params.chromosome_genes // 3:
            chromosome.spacer()
            chromosome.gap()
    chromosome.spacer()
    out = [chromosome]
    if params.plasmid_genes:
        plasmid = Builder(rng, params, "SYNTHETIC_annotation_plasmid")
        for i in range(1, params.plasmid_genes + 1):
            plasmid.spacer()
            plasmid.orf(i)
        plasmid.spacer()
        out.append(plasmid)
    return out


def write(out_dir: Path, params: Params, force: bool = False, inserts: list[tuple[str, str]] = (),
          proteins: list[tuple[str, str]] = ()) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not force and (existing := [n for n in OUTPUTS if (out_dir / n).exists()]):
        raise FileExistsError(f"{', '.join(existing)} already exist in {out_dir}; use --force to replace them")
    replicons = build(params, list(inserts), list(proteins))
    lines = []
    for r in replicons:
        lines.append(f">{r.name} SYNTHETIC random sequence with planted ORFs; not biological data")
        seq = r.sequence
        lines += [seq[i:i + FASTA_WIDTH] for i in range(0, len(seq), FASTA_WIDTH)]
    (out_dir / "genome.fasta").write_text("\n".join(lines) + "\n")
    rows = ["# SYNTHETIC planted features (1-based, inclusive); parameters: " + repr(asdict(params)),
            "sequence\ttype\tid\tstart\tend\tstrand\tlength"]
    for r in replicons:
        rows += ["\t".join(str(f[k]) for k in ("sequence", "type", "id", "start", "end", "strand", "length"))
                 for f in r.features]
    (out_dir / "planted_features.tsv").write_text("\n".join(rows) + "\n")
    return {n: hashlib.sha256((out_dir / n).read_bytes()).hexdigest() for n in OUTPUTS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir", type=Path)
    defaults = Params()
    for name, value in asdict(defaults).items():
        ap.add_argument(f"--{name.replace('_', '-')}", type=int, default=value)
    ap.add_argument("--insert", type=Path, help="FASTA of nucleotide sequences to place verbatim between genes")
    ap.add_argument("--back-translate", type=Path, help="FASTA of protein sequences to encode as ORFs")
    ap.add_argument("--force", action="store_true", help="replace existing output files")
    args = ap.parse_args(argv)
    params = Params(**{k: getattr(args, k) for k in asdict(defaults)})
    if errors := params.errors():
        ap.error("; ".join(errors))
    inserts = read_fasta(args.insert) if args.insert else []
    proteins = read_fasta(args.back_translate) if args.back_translate else []
    if bad := [n for n, s in inserts if set(s) - set("ACGTN")]:
        ap.error(f"--insert sequences may contain only A, C, G, T and N: {', '.join(bad)}")
    if bad := [n for n, s in proteins if set(s) - set(CODONS_OF) or "*" in s]:
        ap.error(f"--back-translate sequences may contain only the 20 standard amino acids: {', '.join(bad)}")
    try:
        sums = write(args.out_dir, params, args.force, inserts, proteins)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1
    for name, digest in sums.items():
        print(f"{digest}  {args.out_dir / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
