#!/usr/bin/env python3
"""Generate small, clearly-labelled SYNTHETIC FASTQ files for tests and demos.

Sequences are random (no biological meaning) and every read header contains
the word "SYNTHETIC". Output is deterministic for a given seed.

To exercise QC and filtering tools, the read sets deliberately contain:
  * Illumina pairs: ~8% low-quality pairs and ~7% short-insert pairs whose reads
    run into the Illumina TruSeq adapters (adapter read-through).
  * Nanopore-like reads: a log-normal length distribution including short reads
    and ~12% low-accuracy reads.

    python scripts/make_synthetic_reads.py examples/synthetic
"""
import argparse
import gzip
import random
from pathlib import Path

# Illumina TruSeq adapter sequences (Illumina Adapter Sequences document).
TRUSEQ_R1 = "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA"
TRUSEQ_R2 = "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT"
_COMP = str.maketrans("ACGT", "TGCA")


def revcomp(s: str) -> str:
    return s.translate(_COMP)[::-1]


def qual_string(rng: random.Random, n: int, mean: float, sd: float, decay: float = 0.0) -> str:
    return "".join(
        chr(33 + min(41, max(2, int(rng.gauss(mean - decay * (p / max(n, 1)) ** 2, sd)))))
        for p in range(n)
    )


def nanopore_like(path: Path, n_reads: int, rng: random.Random) -> None:
    with gzip.open(path, "wt", compresslevel=9) as fh:
        for i in range(n_reads):
            length = max(200, int(rng.lognormvariate(8.0, 0.7)))
            seq = "".join(rng.choices("ACGT", k=length))
            low = rng.random() < 0.12
            qual = qual_string(rng, length, 7 if low else 14, 2 if low else 4)
            fh.write(f"@synthetic_ont_{i} SYNTHETIC random sequence\n{seq}\n+\n{qual}\n")


def random_seq(rng: random.Random, n: int) -> str:
    return "".join(rng.choices("ACGT", weights=(0.33, 0.17, 0.17, 0.33), k=n))


def illumina_pair(r1: Path, r2: Path, n_pairs: int, read_len: int, rng: random.Random) -> None:
    with gzip.open(r1, "wt", compresslevel=9) as f1, gzip.open(r2, "wt", compresslevel=9) as f2:
        for i in range(n_pairs):
            kind = rng.random()
            if kind < 0.07:
                # Short insert: both reads run through the fragment into the adapter.
                insert = random_seq(rng, rng.randint(60, 120))
                s1 = (insert + TRUSEQ_R1 + random_seq(rng, read_len))[:read_len]
                s2 = (revcomp(insert) + TRUSEQ_R2 + random_seq(rng, read_len))[:read_len]
                q1 = qual_string(rng, read_len, 37, 3, 12)
                q2 = qual_string(rng, read_len, 36, 3, 14)
            else:
                s1, s2 = random_seq(rng, read_len), random_seq(rng, read_len)
                if kind < 0.15:
                    q1 = qual_string(rng, read_len, 9, 3)
                    q2 = qual_string(rng, read_len, 9, 3)
                else:
                    # Quality decays towards the 3' end, as is typical of short-read chemistries.
                    q1 = qual_string(rng, read_len, 37, 3, 12)
                    q2 = qual_string(rng, read_len, 36, 3, 14)
            f1.write(f"@synthetic_ill_{i}/1 SYNTHETIC random sequence\n{s1}\n+\n{q1}\n")
            f2.write(f"@synthetic_ill_{i}/2 SYNTHETIC random sequence\n{s2}\n+\n{q2}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--seed", type=int, default=20241027)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    nanopore_like(args.outdir / "SYNTHETIC_nanopore_reads.fastq.gz", 400, rng)
    illumina_pair(
        args.outdir / "SYNTHETIC_illumina_R1_001.fastq.gz",
        args.outdir / "SYNTHETIC_illumina_R2_001.fastq.gz",
        2000,
        150,
        rng,
    )
    print(f"Wrote synthetic reads to {args.outdir}")


if __name__ == "__main__":
    main()
