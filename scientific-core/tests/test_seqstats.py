import gzip
import math
from pathlib import Path

import pytest

from arva_core.formats import SequenceFormat, sniff_format
from arva_core.seqstats import (
    SequenceFormatError,
    StatsParameters,
    compute_sequence_stats,
    quick_validate,
)


def write(path: Path, text: str, compress: bool = False) -> Path:
    data = text.encode()
    if compress:
        path.write_bytes(gzip.compress(data))
    else:
        path.write_bytes(data)
    return path


# Three reads, lengths 4, 6, 10. Qualities chosen so error probabilities are exact.
#   'I' = Q40, '5' = Q20, '+' = Q10
FASTQ = (
    "@r1\nACGT\n+\nIIII\n"
    "@r2\nGGGCCC\n+\n555555\n"
    "@r3\nAAAAATTTTT\n+\n++++++++++\n"
)


def test_fastq_basic_stats(tmp_path):
    stats = compute_sequence_stats(write(tmp_path / "r.fastq", FASTQ))
    assert stats["file"] == {"format": "fastq", "compressed": False}
    assert stats["read_count"] == 3
    assert stats["total_bases"] == 20
    assert stats["min_length"] == 4
    assert stats["max_length"] == 10
    assert stats["mean_length"] == pytest.approx(20 / 3)
    assert stats["median_length"] == 6
    # Sorted desc: 10 (cum 10 >= 10) -> N50 = 10 with one read.
    assert (stats["n50"], stats["l50"]) == (10, 1)
    # 90% of 20 = 18: 10 + 6 = 16 < 18, + 4 = 20 -> N90 = 4, L90 = 3
    assert (stats["n90"], stats["l90"]) == (4, 3)
    # GC: r1 2/4, r2 6/6, r3 0/10 -> 8 / 20 = 40 %
    assert stats["gc_percent"] == pytest.approx(40.0)
    gc_hist = {b["gc_percent"]: b["reads"] for b in stats["gc_histogram"]}
    assert gc_hist == {0: 1, 50: 1, 100: 1}


def test_fastq_quality(tmp_path):
    q = compute_sequence_stats(write(tmp_path / "r.fastq", FASTQ))["quality"]
    assert q["encoding"] == "phred+33"
    assert (q["min_base_quality"], q["max_base_quality"]) == (10, 40)
    # Uniform-quality reads: per-read mean Q equals the base Q.
    assert q["mean_read_quality"] == pytest.approx((40 + 20 + 10) / 3)
    assert q["median_read_quality"] == pytest.approx(20.0)
    total_err = 4 * 1e-4 + 6 * 1e-2 + 10 * 1e-1
    assert q["mean_base_quality"] == pytest.approx(-10 * math.log10(total_err / 20))
    assert q["q20_bases_percent"] == pytest.approx(50.0)
    assert q["q30_bases_percent"] == pytest.approx(20.0)
    above = {r["threshold"]: r["reads"] for r in q["reads_above_quality"]}
    assert above[10] == 3 and above[12] == 2 and above[20] == 2 and above[30] == 1
    pp = q["per_position"]
    assert pp["positions"][:2] == [1, 2] and len(pp["positions"]) == 10
    assert pp["mean_quality"][0] == pytest.approx((40 + 20 + 10) / 3, abs=1e-3)
    assert pp["reads_covering"][4] == 2 and pp["reads_covering"][9] == 1


def test_zero_length_records_are_counted_and_reported(tmp_path):
    stats = compute_sequence_stats(write(tmp_path / "r.fastq", FASTQ + "@empty\n\n+\n\n"))
    assert (stats["read_count"], stats["zero_length_reads"], stats["total_bases"]) == (4, 1, 20)
    assert compute_sequence_stats(write(tmp_path / "s.fastq", FASTQ))["zero_length_reads"] == 0


def test_mean_read_quality_uses_error_probabilities(tmp_path):
    # One base Q40 and one base Q10: arithmetic mean would be 25,
    # error-probability mean is -10*log10((1e-4 + 1e-1)/2) ~= 13.0
    stats = compute_sequence_stats(write(tmp_path / "m.fastq", "@x\nAC\n+\nI+\n"))
    expected = -10 * math.log10((1e-4 + 1e-1) / 2)
    assert stats["quality"]["mean_read_quality"] == pytest.approx(expected)


def test_gzip_detected_by_content(tmp_path):
    path = write(tmp_path / "reads.dat", FASTQ, compress=True)
    stats = compute_sequence_stats(path)
    assert stats["file"]["compressed"] is True
    assert stats["read_count"] == 3


def test_fasta_multiline(tmp_path):
    fasta = ">contig1 desc\nACGT\nACGT\n\n>contig2\nNNGG\n"
    stats = compute_sequence_stats(write(tmp_path / "a.fasta", fasta))
    assert stats["file"]["format"] == "fasta"
    assert stats["read_count"] == 2
    assert stats["total_bases"] == 12
    assert stats["quality"] is None
    assert stats["ambiguous_bases"] == 2
    # GC over unambiguous bases only: (4 + 2) / 10
    assert stats["gc_percent"] == pytest.approx(60.0)


def test_coverage_estimate_only_when_genome_size_given(tmp_path):
    path = write(tmp_path / "r.fastq", FASTQ)
    assert compute_sequence_stats(path)["coverage_estimate"] is None
    cov = compute_sequence_stats(path, StatsParameters(expected_genome_size_bp=10))
    assert cov["coverage_estimate"]["estimated_depth"] == pytest.approx(2.0)


def test_histograms_conserve_counts(tmp_path):
    stats = compute_sequence_stats(write(tmp_path / "r.fastq", FASTQ), StatsParameters(length_bins=3))
    hist = stats["length_histogram"]
    assert sum(hist["reads"]) == 3
    assert sum(hist["bases"]) == 20
    assert stats["length_histogram_log"] is None  # max/min < 10
    cum = stats["cumulative_yield"]
    assert cum[0] == {"min_length": 10, "reads": 1, "bases": 10}
    assert cum[-1] == {"min_length": 4, "reads": 3, "bases": 20}


def test_sampling_is_reproducible(tmp_path):
    lines = "".join(f"@r{i}\n{'A' * (i % 50 + 1)}\n+\n{'I' * (i % 50 + 1)}\n" for i in range(500))
    path = write(tmp_path / "many.fastq", lines)
    p = StatsParameters(sample_size=20)
    a = compute_sequence_stats(path, p)["sample_points"]["points"]
    b = compute_sequence_stats(path, p)["sample_points"]["points"]
    assert a == b and len(a) == 20


@pytest.mark.parametrize(
    "content, line, fragment",
    [
        ("@r1\nACGT\n+\nIIII\nr2\nA\n+\nI\n", 5, "must start with '@'"),
        ("@r1\nACGT\n+\nIII\n", 4, "differs from quality length"),
        ("@r1\nACXT\n+\nIIII\n", 2, "invalid nucleotide"),
        ("@r1\nACGT\nIIII\n", 1, "truncated"),
        ("@r1\nACGT\n-\nIIII\n", 3, "'+' separator"),
        ("@r1\nACGT\n+\nII I\n", 4, "Phred+33"),
        ("@r1\nACGT\n+\nIIII\n\n@r2\nA\n+\nI\n", 5, "blank line"),
    ],
)
def test_fastq_errors_report_line(tmp_path, content, line, fragment):
    with pytest.raises(SequenceFormatError) as exc:
        compute_sequence_stats(write(tmp_path / "bad.fastq", content))
    assert exc.value.line_number == line
    assert fragment in str(exc.value)


def test_trailing_blank_lines_are_tolerated(tmp_path):
    stats = compute_sequence_stats(write(tmp_path / "r.fastq", FASTQ + "\n\n"))
    assert stats["read_count"] == 3


def test_truncated_gzip_header_is_rejected(tmp_path):
    data = gzip.compress(FASTQ.encode())
    path = tmp_path / "trunc.fastq.gz"
    path.write_bytes(data[:20])
    with pytest.raises(SequenceFormatError, match="corrupt or truncated"):
        compute_sequence_stats(path)
    assert not quick_validate(path).is_valid


def test_gzip_truncated_mid_stream_is_rejected(tmp_path):
    import random

    rng = random.Random(1)
    records = []
    for i in range(3000):
        seq = "".join(rng.choice("ACGT") for _ in range(100))
        records.append(f"@r{i}\n{seq}\n+\n{'I' * 100}\n")
    data = gzip.compress("".join(records).encode())
    path = tmp_path / "trunc.fastq.gz"
    path.write_bytes(data[: len(data) // 2])
    assert sniff_format(path).format is SequenceFormat.fastq
    with pytest.raises(SequenceFormatError, match="corrupt or truncated"):
        compute_sequence_stats(path)


def test_unknown_format(tmp_path):
    path = write(tmp_path / "x.txt", "hello world\n")
    assert sniff_format(path).format is SequenceFormat.unknown
    with pytest.raises(SequenceFormatError, match="unrecognised format"):
        compute_sequence_stats(path)


def test_quick_validate(tmp_path):
    ok = quick_validate(write(tmp_path / "ok.fastq", FASTQ))
    assert ok.is_valid and ok.records_checked == 3
    bad = quick_validate(write(tmp_path / "bad.fastq", "@r1\nACGT\n+\nII\n"))
    assert not bad.is_valid and "line 4" in bad.message
    empty = quick_validate(write(tmp_path / "e.fastq", ""))
    assert not empty.is_valid


def test_quick_validate_returns_the_headers_it_read(tmp_path, monkeypatch):
    fastq = quick_validate(write(tmp_path / "r.fastq.gz", FASTQ, compress=True))
    assert fastq.headers == [b"@r1", b"@r2", b"@r3"]
    fasta = quick_validate(write(tmp_path / "c.fa", ">c1 first\nACGT\nAC\n>c2\nGG\n"))
    assert fasta.headers == [b">c1 first", b">c2"]
    many = "".join(f"@read{i}\nA\n+\nI\n" for i in range(50))
    assert len(quick_validate(write(tmp_path / "m.fastq", many), max_records=10).headers) == 10
    bad = quick_validate(write(tmp_path / "bad.fastq", "@ok\nA\n+\nI\n@broken\nAC\n+\nI\n"))
    assert not bad.is_valid and bad.headers == [b"@ok"]
    monkeypatch.setattr("arva_core.seqstats.MAX_HEADER_BYTES", 8)
    assert quick_validate(write(tmp_path / "s.fastq", FASTQ)).headers == [b"@r1", b"@r2"]
