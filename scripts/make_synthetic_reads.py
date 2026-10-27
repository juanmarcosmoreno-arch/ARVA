#!/usr/bin/env python3
"""Generate small, clearly-labelled SYNTHETIC FASTQ files for tests and demos.

Sequences are uniformly random (no biological meaning) and every read header
contains the word "synthetic". Output is deterministic for a given seed.

    python scripts/make_synthetic_reads.py examples/synthetic
"""
import argparse
import gzip
import random
from pathlib import Path


def nanopore_like(path: Path, n_reads: int, rng: random.Random) -> None:
    with gzip.open(path, "wt", compresslevel=9) as fh:
        for i in range(n_reads):
            length = max(200, int(rng.lognormvariate(8.0, 0.7)))
            seq = "".join(rng.choices("ACGT", k=length))
            qual = "".join(chr(33 + min(40, max(3, int(rng.gauss(14, 4))))) for _ in range(length))
            fh.write(f"@synthetic_ont_{i} SYNTHETIC random sequence\n{seq}\n+\n{qual}\n")


def illumina_pair(r1: Path, r2: Path, n_pairs: int, read_len: int, rng: random.Random) -> None:
    with gzip.open(r1, "wt", compresslevel=9) as f1, gzip.open(r2, "wt", compresslevel=9) as f2:
        for i in range(n_pairs):
            for fh, mate in ((f1, 1), (f2, 2)):
                seq = "".join(rng.choices("ACGT", weights=(0.33, 0.17, 0.17, 0.33), k=read_len))
                # Quality decays towards the 3' end, as is typical of short-read chemistries.
                qual = "".join(
                    chr(33 + min(41, max(2, int(rng.gauss(37 - 12 * (p / read_len) ** 2, 3)))))
                    for p in range(read_len)
                )
                fh.write(f"@synthetic_ill_{i}/{mate} SYNTHETIC random sequence\n{seq}\n+\n{qual}\n")


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
