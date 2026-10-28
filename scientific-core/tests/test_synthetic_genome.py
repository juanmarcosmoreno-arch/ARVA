"""scripts/make_synthetic_genome.py: layout, read geometry, error model and reproducibility."""
import gzip
import importlib.util
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from arva_core.assembly_stats import compute_assembly_stats
from arva_core.seqstats import compute_sequence_stats

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_synthetic_genome.py"
_spec = importlib.util.spec_from_file_location("make_synthetic_genome", SCRIPT)
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(gen)

SMALL = gen.Params(chromosome_length=60_000)
COMP = str.maketrans("ACGT", "TGCA")


def read_fasta(path: Path) -> dict[str, tuple[str, str]]:
    records, name = {}, None
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            name, _, desc = line[1:].partition(" ")
            records[name] = [desc, []]
        else:
            records[name][1].append(line)
    return {k: (d, "".join(s)) for k, (d, s) in records.items()}


def read_fastq(path: Path) -> list[tuple[str, str, str]]:
    with gzip.open(path, "rt") as fh:
        lines = fh.read().splitlines()
    return [(lines[i][1:], lines[i + 1], lines[i + 3]) for i in range(0, len(lines), 4)]


def fields(header: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", header))


def circular(seq: str, start: int, length: int) -> str:
    return (seq + seq)[start - 1:start - 1 + length] if length <= len(seq) else ""


def revcomp(s: str) -> str:
    return s.translate(COMP)[::-1]


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    gen.generate(out, SMALL)
    return out


def test_every_header_is_labelled_synthetic(small):
    for name, (desc, _) in read_fasta(small / "reference.fasta").items():
        assert name.startswith("SYNTHETIC_") and desc.startswith("SYNTHETIC ")
    for fq in ("ont.fastq.gz", "illumina_R1.fastq.gz", "illumina_R2.fastq.gz"):
        assert all(h.startswith("SYNTHETIC_") and " SYNTHETIC " in h for h, _, _ in read_fastq(small / fq))


def test_reference_layout(small):
    ref = read_fasta(small / "reference.fasta")
    chrom, plasmid = ref["SYNTHETIC_chromosome"][1], ref["SYNTHETIC_plasmid"][1]
    assert (len(chrom), len(plasmid)) == (60_000, 15_000)
    # Repeat copies at 20 % and 60 %, as written in the header.
    assert "12001-17000 and 36001-41000" in ref["SYNTHETIC_chromosome"][0]
    assert chrom[12_000:17_000] == chrom[36_000:41_000]
    stats = compute_assembly_stats(small / "reference.fasta")
    assert (stats["contig_count"], stats["total_length"], stats["n50"]) == (2, 75_000, 60_000)
    assert 45 < stats["contigs"][0]["gc_percent"] < 55
    assert 41 < stats["contigs"][1]["gc_percent"] < 51
    # Local GC varies smoothly: 2 kb windows spread more than independent bases at a fixed GC would.
    windows = [sum(b in "GC" for b in chrom[i:i + 2000]) / 2000 for i in range(0, 60_000, 2000)]
    assert np.std(windows) > 3 * math.sqrt(0.25 / 2000)


def test_nanopore_reads(small):
    reads = read_fastq(small / "ont.fastq.gz")
    ref = {k: v[1] for k, v in read_fasta(small / "reference.fasta").items()}
    lengths = np.array([len(s) for _, s, _ in reads])
    assert 5_000 < np.median(lengths) < 7_200
    stats = compute_sequence_stats(small / "ont.fastq.gz")
    # 50x of 60 kb + 2 copies x 15 kb.
    assert 47 < stats["total_bases"] / 90_000 < 53
    # Mean error probability implied by the qualities is close to the 4 % target.
    implied = 10 ** (-stats["quality"]["mean_base_quality"] / 10)
    assert 0.035 < implied < 0.046
    crossing = 0
    for header, seq, qual in reads:
        f = fields(header)
        assert len(seq) == len(qual)
        start, span, rep = int(f["start"]), int(f["span"]), ref[f["replicon"]]
        wraps = start + span - 1 > len(rep)
        assert f["crosses_origin"] == ("yes" if wraps else "no")
        crossing += wraps
    assert crossing > 0
    # Reads come from where the header says, on the stated strand: most of their 15-mers are in that span.
    for header, seq, _ in reads[:40]:
        f = fields(header)
        span = circular(ref[f["replicon"]], int(f["start"]), int(f["span"]))
        if f["strand"] == "-":
            span = revcomp(span)
        kmers = {span[i:i + 15] for i in range(len(span) - 14)}
        shared = sum(seq[i:i + 15] in kmers for i in range(len(seq) - 14)) / (len(seq) - 14)
        assert shared > 0.3, header


def test_ont_error_model_is_calibrated():
    rng = np.random.default_rng(1)
    tally = gen.ReadTally()
    ref = rng.integers(0, 4, 400_000).astype(np.uint8)
    seq, q = gen._ont_errors(rng, ref, 0.04, tally)
    events = tally.substitutions + tally.insertions + tally.deletions
    assert events / ref.size == pytest.approx(0.04, abs=0.002)
    assert float((10.0 ** (-q / 10)).mean()) == pytest.approx(events / ref.size, rel=0.05)
    assert seq.size == ref.size + tally.insertions - tally.deletions
    mix = np.array([tally.substitutions, tally.insertions, tally.deletions]) / events
    assert mix == pytest.approx(gen.ONT_ERROR_MIX, abs=0.02)


def test_illumina_pairs(small):
    ref = {k: v[1] for k, v in read_fasta(small / "reference.fasta").items()}
    r1, r2 = read_fastq(small / "illumina_R1.fastq.gz"), read_fastq(small / "illumina_R2.fastq.gz")
    assert len(r1) == len(r2) == math.ceil(60 * 90_000 / 300)
    inserts = []
    mismatches = bases = 0
    for (h1, s1, q1), (h2, s2, q2) in zip(r1, r2, strict=True):
        assert h1.split()[0][:-2] == h2.split()[0][:-2] and h1.split()[0].endswith("/1") and h2.split()[0].endswith("/2")
        assert len(s1) == len(s2) == len(q1) == len(q2) == 150
        f = fields(h1)
        start, insert = int(f["fragment_start"]), int(f["insert"])
        fragment = circular(ref[f["replicon"]], start, insert)
        top, bottom = fragment[:150], revcomp(fragment)[:150]
        e1, e2 = (bottom, top) if f["strand"] == "-" else (top, bottom)
        mismatches += sum(a != b for a, b in zip(s1, e1, strict=True)) + sum(a != b for a, b in zip(s2, e2, strict=True))
        bases += 300
        inserts.append(insert)
    assert np.mean(inserts) == pytest.approx(350, abs=3)
    assert np.std(inserts) == pytest.approx(50, abs=3)
    assert mismatches / bases == pytest.approx(0.005, abs=0.0006)
    stats = compute_sequence_stats(small / "illumina_R1.fastq.gz")
    assert 10 ** (-stats["quality"]["mean_base_quality"] / 10) == pytest.approx(0.005, abs=0.0006)


def test_readme_and_reproducibility(tmp_path):
    tiny = gen.Params(chromosome_length=20_000, plasmid_length=2_000, repeat_length=1_000, ont_depth=5,
                      illumina_depth=5, insert_mean=350)
    first = gen.generate(tmp_path / "a", tiny)
    assert gen.generate(tmp_path / "b", tiny) == first
    assert gen.generate(tmp_path / "c", gen.Params(**{**tiny.__dict__, "seed": 7})) != first
    readme = (tmp_path / "a" / "README.md").read_text()
    assert "not biological data" in readme
    assert "--chromosome-length 20000" in readme and "--seed" not in readme
    for name, (size, digest) in first.items():
        assert f"| `{name}` | {size:,} | `{digest}` |" in readme


def test_rejects_invalid_parameters(capsys):
    with pytest.raises(SystemExit):
        gen.main(["out", "--repeat-length", "50"])
    assert "--repeat-length must be 100" in capsys.readouterr().err
