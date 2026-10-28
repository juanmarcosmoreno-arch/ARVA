#!/usr/bin/env python3
"""Generate a SYNTHETIC bacterium-like genome and simulated reads for assembly tests and demos.

Nothing here is biological data. Every FASTA/FASTQ header contains the word SYNTHETIC.

The genome is one circular chromosome holding two identical copies of a repeat, plus one circular
plasmid. Reads are sampled uniformly from either strand of each replicon (weighted by length x copy
number), wrapping across the origin of the circular sequences:

  * Oxford Nanopore-like reads: log-normal lengths, substitutions, insertions and deletions drawn
    from each base's own Phred quality (P(error) = 10^(-Q/10)), so the qualities are calibrated.
  * Illumina-like paired-end reads: normally distributed insert sizes, substitutions only, drawn the
    same way from position-dependent qualities.

The output is identical for the same seed, parameters and numpy/zlib versions (gzip headers carry
no timestamp). README.md in the output folder records the exact command, the layout and the
realised read statistics.

    python3 scripts/make_synthetic_genome.py examples/synthetic-genome
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import math
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

BASES = np.frombuffer(b"ACGT", dtype=np.uint8)
LN10 = math.log(10)
FASTA_WIDTH = 80
ONT_Q_SD = 4.0
ONT_Q_RANGE = (1, 50)
ONT_ERROR_MIX = (0.40, 0.25, 0.35)  # substitution, insertion, deletion
ONT_READ_ERROR_SD = 0.3  # log-normal spread of the per-read error rate around --ont-error-rate
ONT_MIN_LENGTH = 200
ILLUMINA_Q_SD = 5.0
ILLUMINA_Q_RANGE = (2, 41)
ILLUMINA_BATCH = 5000
OUTPUTS = ("reference.fasta", "ont.fastq.gz", "illumina_R1.fastq.gz", "illumina_R2.fastq.gz")


@dataclass(frozen=True)
class Params:
    seed: int = 20261028
    chromosome_length: int = 300_000
    plasmid_length: int = 15_000
    repeat_length: int = 5_000
    gc: float = 0.50
    plasmid_gc: float = 0.46
    plasmid_copies: int = 2
    ont_depth: float = 50.0
    ont_median_length: int = 6_000
    ont_length_sigma: float = 0.6
    ont_error_rate: float = 0.04
    illumina_depth: float = 60.0
    read_length: int = 150
    insert_mean: int = 350
    insert_sd: int = 50
    illumina_error_rate: float = 0.005

    def errors(self) -> list[str]:
        out = []
        if not 10_000 <= self.chromosome_length <= 20_000_000:
            out.append("--chromosome-length must be 10,000-20,000,000")
        if not 1_000 <= self.plasmid_length <= self.chromosome_length:
            out.append("--plasmid-length must be 1,000 up to the chromosome length")
        if not 100 <= self.repeat_length <= self.chromosome_length // 4:
            out.append("--repeat-length must be 100 up to a quarter of the chromosome length")
        for name in ("gc", "plasmid_gc"):
            if not 0.25 <= getattr(self, name) <= 0.75:
                out.append(f"--{name.replace('_', '-')} must be 0.25-0.75")
        if self.plasmid_copies < 1:
            out.append("--plasmid-copies must be >= 1")
        if not 0 < self.ont_depth <= 500 or not 0 < self.illumina_depth <= 500:
            out.append("depths must be > 0 and <= 500")
        if not ONT_MIN_LENGTH <= self.ont_median_length <= 100_000 or not 0 < self.ont_length_sigma <= 2:
            out.append("--ont-median-length must be 200-100,000 and --ont-length-sigma 0-2")
        if not 0.001 <= self.ont_error_rate <= 0.2 or not 0.0001 <= self.illumina_error_rate <= 0.05:
            out.append("--ont-error-rate must be 0.001-0.2 and --illumina-error-rate 0.0001-0.05")
        if not 50 <= self.read_length <= 300:
            out.append("--read-length must be 50-300")
        if self.insert_sd < 0 or not self.read_length <= self.insert_mean <= self.plasmid_length // 2:
            out.append("--insert-mean must be between the read length and half the plasmid length")
        return out


@dataclass
class Replicon:
    name: str
    description: str
    seq: np.ndarray
    copies: int
    repeats: list[tuple[int, int]] = field(default_factory=list)  # 1-based inclusive

    @property
    def length(self) -> int:
        return int(self.seq.size)


# --- Genome -----------------------------------------------------------------------------------

def _gc_profile(rng: np.random.Generator, length: int, mean_gc: float) -> np.ndarray:
    """Mean GC plus two sinusoids with whole numbers of periods, so the profile is continuous across the origin."""
    x = np.arange(length) / length
    slow, fast = max(1, round(length / 100_000)), max(1, round(length / 10_000))
    phase = rng.uniform(0, 2 * math.pi, 2)
    p = mean_gc + 0.06 * np.sin(2 * math.pi * slow * x + phase[0]) + 0.03 * np.sin(2 * math.pi * fast * x + phase[1])
    return np.clip(p, 0.2, 0.8)


def _random_sequence(rng: np.random.Generator, gc_probability: np.ndarray) -> np.ndarray:
    is_gc = rng.random(gc_probability.size) < gc_probability
    second = rng.random(gc_probability.size) < 0.5
    # A=0 C=1 G=2 T=3: G/C draw 1 or 2, A/T draw 0 or 3.
    return np.where(is_gc, np.where(second, 2, 1), np.where(second, 3, 0)).astype(np.uint8)


def build_genome(p: Params, rng: np.random.Generator) -> list[Replicon]:
    chrom = _random_sequence(rng, _gc_profile(rng, p.chromosome_length, p.gc))
    repeat = _random_sequence(rng, np.full(p.repeat_length, p.gc))
    starts = [round(0.2 * p.chromosome_length), round(0.6 * p.chromosome_length)]
    for s in starts:
        chrom[s:s + p.repeat_length] = repeat
    repeats = [(s + 1, s + p.repeat_length) for s in starts]
    plasmid = _random_sequence(rng, _gc_profile(rng, p.plasmid_length, p.plasmid_gc))
    where = " and ".join(f"{a}-{b}" for a, b in repeats)
    return [
        Replicon("SYNTHETIC_chromosome",
                 f"SYNTHETIC circular chromosome, {p.chromosome_length} bp, identical {p.repeat_length} bp repeat "
                 f"copies at {where}; simulated, not biological data", chrom, 1, repeats),
        Replicon("SYNTHETIC_plasmid",
                 f"SYNTHETIC circular plasmid, {p.plasmid_length} bp, {p.plasmid_copies} copies per chromosome; "
                 "simulated, not biological data", plasmid, p.plasmid_copies),
    ]


def gc_fraction(seq: np.ndarray) -> float:
    return float(np.isin(seq, (1, 2)).mean())


def revcomp(seq: np.ndarray) -> np.ndarray:
    return (3 - seq[::-1]).astype(np.uint8)


# --- Read simulation ---------------------------------------------------------------------------

def phred_mean_for_error(error_rate: float, sd: float) -> float:
    """Mean of a normal Phred distribution whose mean error probability E[10^(-Q/10)] equals error_rate."""
    return -10 * math.log10(error_rate) + sd * sd * LN10 / 20


def _qualities(rng: np.random.Generator, mean: np.ndarray | float, sd: float, size, bounds: tuple[int, int]) -> np.ndarray:
    return np.clip(np.rint(rng.normal(mean, sd, size)), *bounds).astype(np.int64)


@dataclass
class ReadTally:
    reads: int = 0
    emitted_bases: int = 0
    reference_bases: int = 0
    substitutions: int = 0
    insertions: int = 0
    deletions: int = 0
    phred_error_sum: float = 0.0
    origin_spanning: int = 0
    lengths: list[int] = field(default_factory=list)
    span_by_replicon: dict[str, int] = field(default_factory=dict)
    inserts: list[int] = field(default_factory=list)

    def add_span(self, name: str, bases: int) -> None:
        self.span_by_replicon[name] = self.span_by_replicon.get(name, 0) + bases


def _ont_errors(rng: np.random.Generator, ref: np.ndarray, error_rate: float, tally: ReadTally):
    n = ref.size
    q = _qualities(rng, phred_mean_for_error(error_rate, ONT_Q_SD), ONT_Q_SD, n, ONT_Q_RANGE)
    err = rng.random(n) < 10.0 ** (-q / 10)
    kind = rng.choice(3, size=n, p=ONT_ERROR_MIX)
    sub, ins, dele = err & (kind == 0), err & (kind == 1), err & (kind == 2)
    base = ref.copy()
    base[sub] = (base[sub] + rng.integers(1, 4, int(sub.sum()))) % 4
    counts = np.ones(n, dtype=np.int64)
    counts[ins] = 2
    counts[dele] = 0
    out, out_q = np.repeat(base, counts), np.repeat(q, counts)
    ends = np.cumsum(counts)
    inserted = ends[ins] - 1
    out[inserted] = rng.integers(0, 4, inserted.size)
    # A deletion lowers the quality of the next emitted base to the deleted base's quality.
    after = ends[dele]
    keep = after < out.size
    np.minimum.at(out_q, after[keep], q[dele][keep])
    tally.substitutions += int(sub.sum())
    tally.insertions += int(ins.sum())
    tally.deletions += int(dele.sum())
    return out.astype(np.uint8), out_q


def _fastq(header: str, seq: np.ndarray, q: np.ndarray) -> bytes:
    return b"".join((b"@", header.encode(), b"\n", BASES[seq].tobytes(), b"\n+\n",
                     (q + 33).astype(np.uint8).tobytes(), b"\n"))


def _weights(replicons: list[Replicon]) -> np.ndarray:
    w = np.array([r.length * r.copies for r in replicons], dtype=np.float64)
    return w / w.sum()


def simulate_ont(p: Params, replicons: list[Replicon], rng: np.random.Generator, out) -> ReadTally:
    tally = ReadTally()
    target = p.ont_depth * sum(r.length * r.copies for r in replicons)
    weights = _weights(replicons)
    mu = math.log(p.ont_median_length)
    spread = ONT_READ_ERROR_SD
    while tally.reference_bases < target:
        rep = replicons[int(rng.choice(len(replicons), p=weights))]
        length = int(min(rep.length, max(ONT_MIN_LENGTH, round(rng.lognormal(mu, p.ont_length_sigma)))))
        start = int(rng.integers(0, rep.length))
        minus = bool(rng.random() < 0.5)
        ref = rep.seq[(start + np.arange(length)) % rep.length]
        if minus:
            ref = revcomp(ref)
        read_error = min(0.2, max(0.005, p.ont_error_rate * math.exp(rng.normal(0, spread) - spread * spread / 2)))
        seq, q = _ont_errors(rng, ref, read_error, tally)
        tally.reads += 1
        tally.reference_bases += length
        tally.emitted_bases += seq.size
        tally.phred_error_sum += float((10.0 ** (-q / 10)).sum())
        tally.lengths.append(int(seq.size))
        tally.add_span(rep.name, length)
        wraps = start + length > rep.length
        tally.origin_spanning += wraps
        header = (f"SYNTHETIC_ont_{tally.reads:06d} SYNTHETIC simulated nanopore-like read; replicon={rep.name} "
                  f"start={start + 1} span={length} strand={'-' if minus else '+'} "
                  f"crosses_origin={'yes' if wraps else 'no'} target_error={read_error:.4f}")
        out.write(_fastq(header, seq, q))
    return tally


def simulate_illumina(p: Params, replicons: list[Replicon], rng: np.random.Generator, out1, out2) -> ReadTally:
    tally = ReadTally()
    L = p.read_length
    pairs = math.ceil(p.illumina_depth * sum(r.length * r.copies for r in replicons) / (2 * L))
    position_error = p.illumina_error_rate * (0.5 + np.arange(L) / (L - 1))  # rises along the read, mean = rate
    q_mean = np.array([phred_mean_for_error(e, ILLUMINA_Q_SD) for e in position_error])
    offsets = np.arange(L)
    choice = rng.choice(len(replicons), size=pairs, p=_weights(replicons))
    done = 0
    while done < pairs:
        n = min(ILLUMINA_BATCH, pairs - done)
        which = choice[done:done + n]
        reads1 = np.empty((n, L), dtype=np.uint8)
        reads2 = np.empty((n, L), dtype=np.uint8)
        starts = np.empty(n, dtype=np.int64)
        inserts = np.empty(n, dtype=np.int64)
        minus = rng.random(n) < 0.5
        for k, rep in enumerate(replicons):
            rows = np.nonzero(which == k)[0]
            if rows.size == 0:
                continue
            s = rng.integers(0, rep.length, rows.size)
            ins = np.clip(np.rint(rng.normal(p.insert_mean, p.insert_sd, rows.size)), L, rep.length).astype(np.int64)
            top = rep.seq[(s[:, None] + offsets[None, :]) % rep.length]
            bottom = 3 - rep.seq[(s[:, None] + ins[:, None] - 1 - offsets[None, :]) % rep.length]
            m = minus[rows][:, None]
            reads1[rows] = np.where(m, bottom, top)
            reads2[rows] = np.where(m, top, bottom)
            starts[rows], inserts[rows] = s, ins
            tally.add_span(rep.name, 2 * L * rows.size)
            tally.origin_spanning += int((s + ins > rep.length).sum())
        quals = []
        for reads in (reads1, reads2):
            q = _qualities(rng, q_mean[None, :], ILLUMINA_Q_SD, reads.shape, ILLUMINA_Q_RANGE)
            sub = rng.random(reads.shape) < 10.0 ** (-q / 10)
            reads[sub] = (reads[sub] + rng.integers(1, 4, int(sub.sum()))) % 4
            tally.substitutions += int(sub.sum())
            tally.phred_error_sum += float((10.0 ** (-q / 10)).sum())
            quals.append(q)
        chunk1, chunk2 = [], []
        for i in range(n):
            rep = replicons[which[i]]
            name = f"SYNTHETIC_ill_{done + i + 1:07d}"
            info = (f"SYNTHETIC simulated Illumina-like pair; replicon={rep.name} fragment_start={starts[i] + 1} "
                    f"insert={inserts[i]} strand={'-' if minus[i] else '+'}")
            chunk1.append(_fastq(f"{name}/1 {info}", reads1[i], quals[0][i]))
            chunk2.append(_fastq(f"{name}/2 {info}", reads2[i], quals[1][i]))
        out1.write(b"".join(chunk1))
        out2.write(b"".join(chunk2))
        tally.inserts.extend(int(v) for v in inserts)
        done += n
    tally.reads = 2 * pairs
    tally.emitted_bases = tally.reference_bases = 2 * pairs * L
    return tally


# --- Output ------------------------------------------------------------------------------------

def _gzip_writer(path: Path):
    """gzip without a timestamp or file name in its header, so identical content gives identical bytes."""
    return gzip.GzipFile(filename="", mode="wb", fileobj=open(path, "wb"), compresslevel=6, mtime=0)


def write_reference(path: Path, replicons: list[Replicon]) -> None:
    with open(path, "wb") as fh:
        for r in replicons:
            fh.write(f">{r.name} {r.description}\n".encode())
            text = BASES[r.seq].tobytes()
            fh.write(b"\n".join(text[i:i + FASTA_WIDTH] for i in range(0, len(text), FASTA_WIDTH)) + b"\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _n50(lengths: list[int]) -> int:
    total, acc = sum(lengths), 0
    for length in sorted(lengths, reverse=True):
        acc += length
        if 2 * acc >= total:
            return length
    return 0


def command_line(outdir: str, p: Params) -> str:
    defaults = Params()
    args = [f"--{k.replace('_', '-')} {getattr(p, k)}" for k in Params.__dataclass_fields__ if getattr(p, k) != getattr(defaults, k)]
    return " ".join(["python3 scripts/make_synthetic_genome.py", outdir, *args])


def readme(outdir: str, p: Params, replicons: list[Replicon], ont: ReadTally, ill: ReadTally, files: dict[str, tuple[int, str]]) -> str:
    genome = sum(r.length * r.copies for r in replicons)
    rows = "\n".join(
        f"| `{r.name}` | {r.length:,} | circular | {r.copies} | {100 * gc_fraction(r.seq):.2f} | "
        + (", ".join(f"{a:,}-{b:,}" for a, b in r.repeats) or "-") + " |"
        for r in replicons
    )
    depth = "\n".join(
        f"| `{r.name}` | {r.copies} | {ont.span_by_replicon.get(r.name, 0) / r.length:.1f} "
        f"({p.ont_depth * r.copies:g}) | {ill.span_by_replicon.get(r.name, 0) / r.length:.1f} "
        f"({p.illumina_depth * r.copies:g}) |"
        for r in replicons
    )
    ont_errors = ont.substitutions + ont.insertions + ont.deletions
    files_table = "\n".join(f"| `{name}` | {size:,} | `{digest}` |" for name, (size, digest) in files.items())
    lengths = np.array(ont.lengths)
    inserts = np.array(ill.inserts)
    params = "\n".join(f"| `{k}` | {getattr(p, k)} |" for k in Params.__dataclass_fields__)
    return f"""# SYNTHETIC genome and simulated reads — not biological data

Everything in this folder was generated by `scripts/make_synthetic_genome.py`. The sequences are
random (no genes, no biological meaning) and every FASTA/FASTQ header contains the word `SYNTHETIC`.
Use them to exercise assembly and assembly-quality steps, where the true genome is known
(`reference.fasta`). Do not interpret any result biologically.

Only this README is kept in git; regenerate the data with:

```bash
{command_line(outdir, p)}
```

The same seed, parameters, numpy and zlib versions give byte-identical files (generated here with
Python {platform.python_version()}, numpy {np.__version__}; random generator `numpy.random.default_rng`, PCG64,
with independent streams for the genome, the nanopore reads and the Illumina reads spawned from the seed).

## Parameters

| Parameter | Value |
|---|---|
{params}

## Genome (`reference.fasta`)

| Replicon | Length (bp) | Topology | Copies | GC (%) | Repeat copies (1-based, inclusive) |
|---|---|---|---|---|---|
{rows}

- Bases are drawn independently; the probability of G or C at each position follows the mean GC plus
  two sinusoids (amplitudes 6 and 3 percentage points, about one period per 100 kb and per 10 kb,
  whole periods per replicon so that the profile is continuous across the origin), clipped to 20–80 %.
- The chromosome carries two identical copies of one {p.repeat_length:,} bp random sequence (same orientation,
  starting at 20 % and 60 % of its length), so the assembly graph has a repeat to resolve. Nanopore
  reads longer than the repeat plus its flanks can span it; Illumina pairs (inserts around
  {p.insert_mean} bp) cannot, so a short-read assembly graph keeps it as one node at about twice the depth.
- Copy number scales the share of reads drawn from the plasmid (reads are sampled in proportion to
  length × copies).

## Nanopore-like reads (`ont.fastq.gz`)

- Reads: {ont.reads:,}; bases: {ont.emitted_bases:,}; median length {int(np.median(lengths)):,} bp, mean
  {lengths.mean():,.0f} bp, N50 {_n50(ont.lengths):,} bp, longest {lengths.max():,} bp.
- Lengths: log-normal with median {p.ont_median_length:,} bp and σ = {p.ont_length_sigma} (natural log), at least
  {ONT_MIN_LENGTH} bp and at most the replicon length. Start positions are uniform on the circle and reads
  wrap across the origin: {ont.origin_spanning:,} reads cross it. Strand: + or − with equal probability.
- Errors: each read gets a target error rate (log-normal around {p.ont_error_rate}, σ = {ONT_READ_ERROR_SD}, clipped to
  0.005–0.2). Each reference base gets a Phred quality Q ~ Normal(μ, {ONT_Q_SD}) rounded and clipped to
  {ONT_Q_RANGE[0]}–{ONT_Q_RANGE[1]}, with μ chosen so that the mean of 10^(−Q/10) equals the target; the base is then in
  error with probability 10^(−Q/10). An error is a substitution, an insertion (the base is followed by
  a random base with the same Q) or a deletion (the base is dropped and the next base's Q is lowered
  to the deleted base's Q) with probabilities {ONT_ERROR_MIX[0]}/{ONT_ERROR_MIX[1]}/{ONT_ERROR_MIX[2]}.
- Realised: {ont.substitutions:,} substitutions, {ont.insertions:,} insertions, {ont.deletions:,} deletions =
  {100 * ont_errors / ont.reference_bases:.2f} % of {ont.reference_bases:,} reference bases; the mean error probability implied by
  the qualities is {100 * ont.phred_error_sum / ont.emitted_bases:.2f} %.

## Illumina-like paired-end reads (`illumina_R1.fastq.gz`, `illumina_R2.fastq.gz`)

- Pairs: {ill.reads // 2:,} of 2 × {p.read_length} bp ({ill.emitted_bases:,} bases); read names match between the files
  (`/1`, `/2`).
- Fragments: start uniform on the circle (wrapping across the origin: {ill.origin_spanning:,} fragments),
  insert size Normal({p.insert_mean}, {p.insert_sd}) rounded and clipped to the read length … replicon length
  (realised mean {inserts.mean():.1f}, SD {inserts.std():.1f}); R1 reads the fragment's 5′ end, R2 the
  reverse complement of its 3′ end; fragment strand + or − with equal probability. No adapters.
- Errors: substitutions only. Q ~ Normal(μ_position, {ILLUMINA_Q_SD}) rounded and clipped to
  {ILLUMINA_Q_RANGE[0]}–{ILLUMINA_Q_RANGE[1]}, where μ gives a mean error probability rising linearly from
  {50 * p.illumina_error_rate:.2f} % at the first base to {150 * p.illumina_error_rate:.2f} % at the last
  (mean {100 * p.illumina_error_rate:.2f} %); each base is substituted with probability 10^(−Q/10).
- Realised: {ill.substitutions:,} substitutions = {100 * ill.substitutions / ill.emitted_bases:.3f} % of bases; the mean error
  probability implied by the qualities is {100 * ill.phred_error_sum / ill.emitted_bases:.3f} %.

## Depth

Read bases drawn from each replicon ÷ its length, i.e. the coverage an assembler sees; in brackets the
expectation, depth target × copies (targets: {p.ont_depth}× nanopore and {p.illumina_depth}× Illumina per copy,
over {genome:,} bp counting every copy).

| Replicon | Copies | Nanopore (×) | Illumina (×) |
|---|---|---|---|
{depth}

## Files

| File | Bytes | SHA-256 |
|---|---|---|
{files_table}
"""


def generate(outdir: Path, p: Params, outdir_label: str | None = None) -> dict[str, tuple[int, str]]:
    genome_rng, ont_rng, ill_rng = (np.random.default_rng(s) for s in np.random.SeedSequence(p.seed).spawn(3))
    replicons = build_genome(p, genome_rng)
    outdir.mkdir(parents=True, exist_ok=True)
    write_reference(outdir / "reference.fasta", replicons)
    with _gzip_writer(outdir / "ont.fastq.gz") as out:
        ont = simulate_ont(p, replicons, ont_rng, out)
    with _gzip_writer(outdir / "illumina_R1.fastq.gz") as r1, _gzip_writer(outdir / "illumina_R2.fastq.gz") as r2:
        ill = simulate_illumina(p, replicons, ill_rng, r1, r2)
    files = {name: ((outdir / name).stat().st_size, sha256(outdir / name)) for name in OUTPUTS}
    (outdir / "README.md").write_text(readme(outdir_label or str(outdir), p, replicons, ont, ill, files), encoding="utf-8")
    return files


def parse_args(argv: list[str] | None) -> tuple[Path, Params]:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir", type=Path)
    for name, f in Params.__dataclass_fields__.items():
        ap.add_argument(f"--{name.replace('_', '-')}", type=type(f.default), default=f.default)
    ns = ap.parse_args(argv)
    params = Params(**{k: getattr(ns, k) for k in Params.__dataclass_fields__})
    if problems := params.errors():
        ap.error("; ".join(problems))
    return ns.outdir, params


def main(argv: list[str] | None = None) -> None:
    outdir, params = parse_args(argv)
    files = generate(outdir, params, outdir_label=str(outdir))
    print(f"Wrote SYNTHETIC genome and reads to {outdir}: " + ", ".join(files))


if __name__ == "__main__":
    main(sys.argv[1:])
