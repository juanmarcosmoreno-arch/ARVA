import gzip
from pathlib import Path

import pytest

from arva_core.assembly_stats import (
    AssemblyFormatError,
    AssemblyStatsParameters,
    ContigAnnotation,
    _length_bin_edges,
    assembly_warnings,
    compute_assembly_stats,
    min_length_summary,
)
from arva_core.seqstats import SequenceFormatError


def fasta(path: Path, records: list[tuple[str, str]], compress: bool = False) -> Path:
    text = "".join(f">{name}\n{seq}\n" for name, seq in records).encode()
    path.write_bytes(gzip.compress(text) if compress else text)
    return path


# Lengths 10, 10, 20, 4 (total 44). Ranked: c3 (20), c1 (10, first in the file), c2 (10), c4 (4).
#   c1 ACGTACGTAC: G+C = 5 of 10 ACGT          c2 GGGGCCCCNN: 8 of 8 ACGT, 2 N
#   c3 (AAAAATTTTT)x2: 0 of 20                  c4 ACGR: 2 of 3 ACGT, 1 other IUPAC code
RECORDS = [
    ("c1 first contig", "ACGTACGTAC"),
    ("c2", "GGGGCCCCNN"),
    ("c3", "AAAAATTTTTAAAAATTTTT"),
    ("c4", "ACGR"),
]


def test_basic_statistics(tmp_path):
    s = compute_assembly_stats(fasta(tmp_path / "a.fasta", RECORDS))
    assert s["tool"]["name"] == "arva-core.assembly_stats"
    assert (s["contig_count"], s["total_length"], s["largest_contig"], s["smallest_contig"]) == (4, 44, 20, 4)
    # Cumulative 20, 30, 40, 44. Half of 44 = 22 -> reached at rank 2 (30): N50 = 10, L50 = 2.
    assert (s["n50"], s["l50"]) == (10, 2)
    # 90 % of 44 = 39.6 -> reached at rank 3 (40): N90 = 10, L90 = 3.
    assert (s["n90"], s["l90"]) == (10, 3)
    # G+C = 5 + 8 + 0 + 2 = 15 over A+C+G+T = 10 + 8 + 20 + 3 = 41.
    assert s["gc_percent"] == pytest.approx(100 * 15 / 41)
    assert (s["n_count"], s["other_iupac_count"]) == (2, 1)
    assert s["n_per_100kb"] == pytest.approx(1e5 * 2 / 44)
    assert [(c["name"], c["rank"], c["length"]) for c in s["contigs"]] == [
        ("c3", 1, 20), ("c1", 2, 10), ("c2", 3, 10), ("c4", 4, 4)]
    c = {r["name"]: r for r in s["contigs"]}
    assert c["c1"]["gc_percent"] == pytest.approx(50.0)
    assert (c["c2"]["gc_percent"], c["c2"]["n_count"]) == (pytest.approx(100.0), 2)
    assert c["c3"]["gc_percent"] == 0.0
    assert (c["c4"]["gc_percent"], c["c4"]["other_iupac_count"]) == (pytest.approx(200 / 3), 1)
    assert c["c1"]["coverage"] is None and c["c1"]["circular"] is None
    assert s["cumulative"] == {"rank": [1, 2, 3, 4], "length": [20, 10, 10, 4],
                               "cumulative_length": [20, 30, 40, 44], "downsampled": False}
    assert s["length_histogram"] == [{"min_length": 0, "max_length": 100, "contigs": 4, "total_length": 44}]
    assert s["coverage"] == {"contigs_with_coverage": 0, "length_weighted_median": None}


def test_min_length_summary_keeps_only_contigs_at_or_above_the_threshold(tmp_path):
    path = fasta(tmp_path / "a.fasta", RECORDS)
    s = min_length_summary(path, 10)
    # c4 (4 bp) is left out; c1 and c2 (exactly 10 bp) are kept. Cumulative 20, 30, 40 of 40.
    assert (s["all_contigs"], s["all_total_length"], s["contigs"], s["total_length"]) == (4, 44, 3, 40)
    assert (s["largest_contig"], s["n50"], s["l50"], s["n90"], s["l90"]) == (20, 20, 1, 10, 3)
    assert s["gc_percent"] == pytest.approx(100 * 13 / 38)
    assert (s["n_count"], s["n_per_100kb"]) == (2, pytest.approx(1e5 * 2 / 40))
    # c4's R is left out with c4; at threshold 0 it counts as ambiguous (as QUAST's N) but not as N.
    assert (s["other_iupac_count"], s["ambiguous_per_100kb"]) == (0, pytest.approx(1e5 * 2 / 40))
    # Threshold 0 keeps every contig and agrees with the full statistics.
    full, zero = compute_assembly_stats(path), min_length_summary(path, 0)
    for key in ("total_length", "largest_contig", "n50", "l50", "n90", "l90", "gc_percent", "n_per_100kb"):
        assert zero[key] == pytest.approx(full[key]), key
    assert zero["contigs"] == full["contig_count"]
    assert zero["ambiguous_per_100kb"] == pytest.approx(1e5 * 3 / 44)
    none = min_length_summary(path, 21)
    assert (none["contigs"], none["total_length"], none["n50"], none["gc_percent"]) == (0, 0, None, None)
    with pytest.raises(ValueError):
        min_length_summary(path, -1)


def test_nx_is_inclusive_at_the_boundary_and_ties(tmp_path):
    # 5, 3, 2: half of 10 is reached exactly by the first contig.
    s = compute_assembly_stats(fasta(tmp_path / "a.fa", [("a", "A" * 5), ("b", "C" * 3), ("c", "G" * 2)]))
    assert (s["n50"], s["l50"], s["n90"], s["l90"]) == (5, 1, 2, 3)
    # Two equal contigs: N50 = 5 with one contig; 90 % needs both.
    s = compute_assembly_stats(fasta(tmp_path / "b.fa", [("x", "A" * 5), ("y", "T" * 5)]))
    assert (s["n50"], s["l50"], s["n90"], s["l90"]) == (5, 1, 5, 2)
    assert [c["name"] for c in s["contigs"]] == ["x", "y"]


def test_single_contig_and_gzip(tmp_path):
    s = compute_assembly_stats(fasta(tmp_path / "one.fa.gz", [("only", "ACGTN")], compress=True))
    assert s["file"] == {"compressed": True}
    assert (s["contig_count"], s["n50"], s["l50"], s["n90"], s["l90"]) == (1, 5, 1, 5, 1)
    assert s["gc_percent"] == pytest.approx(50.0) and s["n_count"] == 1


def test_lowercase_and_multiline_fasta(tmp_path):
    path = tmp_path / "soft.fa"
    path.write_text(">m masked\nacgt\nACGT\nnn\n")
    s = compute_assembly_stats(path)
    assert (s["total_length"], s["n_count"]) == (10, 2)
    assert s["gc_percent"] == pytest.approx(50.0)


def test_length_bins_thresholds_and_histogram(tmp_path):
    assert _length_bin_edges(20) == [0, 100]
    assert _length_bin_edges(1000) == [0, 100, 200, 500, 1000, 2000]
    lengths = {"a": 150, "b": 1000, "c": 1500, "d": 25_000}
    s = compute_assembly_stats(fasta(tmp_path / "h.fa", [(k, "A" * v) for k, v in lengths.items()]))
    hist = [(b["min_length"], b["max_length"], b["contigs"], b["total_length"]) for b in s["length_histogram"]]
    assert hist == [(100, 200, 1, 150), (200, 500, 0, 0), (500, 1000, 0, 0), (1000, 2000, 2, 2500),
                    (2000, 5000, 0, 0), (5000, 10000, 0, 0), (10000, 20000, 0, 0), (20000, 50000, 1, 25000)]
    total = 27_650
    assert s["thresholds"] == [
        {"min_length": 1000, "contigs": 3, "total_length": 27_500, "total_length_percent": pytest.approx(100 * 27_500 / total)},
        {"min_length": 10000, "contigs": 1, "total_length": 25_000, "total_length_percent": pytest.approx(100 * 25_000 / total)},
    ]
    s = compute_assembly_stats(tmp_path / "h.fa", params=AssemblyStatsParameters(thresholds=(500,)))
    assert s["parameters"] == {"thresholds": [500]}
    assert [(t["min_length"], t["contigs"]) for t in s["thresholds"]] == [(500, 3)]


def test_cumulative_curve_is_downsampled_but_keeps_head_and_end(tmp_path):
    records = [(f"k{i}", "A" * (2000 - i)) for i in range(1500)]
    s = compute_assembly_stats(fasta(tmp_path / "many.fa", records))
    curve = s["cumulative"]
    assert curve["downsampled"] is True and len(curve["rank"]) == 1000
    assert curve["rank"][:500] == list(range(1, 501)) and curve["rank"][-1] == 1500
    assert curve["cumulative_length"][-1] == s["total_length"] == sum(2000 - i for i in range(1500))
    assert curve["length"][0] == 2000 and curve["length"][-1] == 501
    assert len(s["contigs"]) == 1500


def test_annotations_and_weighted_median_coverage(tmp_path):
    notes = {"c1": ContigAnnotation(coverage=10, circular=True), "c2": ContigAnnotation(coverage=30, repeat=True),
             "c3": ContigAnnotation(coverage=20, circular=False)}
    s = compute_assembly_stats(fasta(tmp_path / "a.fa", RECORDS), notes)
    c = {r["name"]: r for r in s["contigs"]}
    assert (c["c1"]["coverage"], c["c1"]["circular"], c["c1"]["repeat"]) == (10.0, True, None)
    assert (c["c2"]["coverage"], c["c2"]["repeat"]) == (30.0, True)
    assert c["c4"]["coverage"] is None
    # By coverage: c1 (10, 10 bp), c3 (20, 20 bp), c2 (30, 10 bp); half of 40 bp is reached within c3.
    assert s["coverage"] == {"contigs_with_coverage": 3, "length_weighted_median": 20.0}
    assert s["circularity"] == {"contigs_with_circularity": 2, "circular_contigs": 1}


@pytest.mark.parametrize("text,notes,message", [
    (">a\nACGT\n>a\nACGT\n", None, "line 3: contig name 'a' appears more than once"),
    (">e\n", None, "no bases"),
    (">\nACGT\n", None, "line 1: contig without a name"),
    (">a\nACGT\n", {"b": ContigAnnotation(coverage=1)}, "not in the FASTA file: b"),
    ("", None, "contigs FASTA"),
])
def test_rejects_unusable_contig_files(tmp_path, text, notes, message):
    path = tmp_path / "bad.fa"
    path.write_text(text)
    with pytest.raises(AssemblyFormatError, match=message):
        compute_assembly_stats(path, notes)


def test_rejects_fastq_and_invalid_characters(tmp_path):
    fq = tmp_path / "r.fastq"
    fq.write_text("@r\nACGT\n+\nIIII\n")
    with pytest.raises(AssemblyFormatError, match="contigs FASTA"):
        compute_assembly_stats(fq)
    bad = tmp_path / "p.fa"
    bad.write_text(">p\nMKLV*\n")
    with pytest.raises(SequenceFormatError, match="line 2"):
        compute_assembly_stats(bad)


# --- Heuristic warnings ---------------------------------------------------------------------------

def _mixed(tmp_path, circular=False):
    # chrom 100 kb GC 50 %, plasmid 4 kb GC 75 %, junk 2 kb GC 0 %; overall GC = 53,000 / 106,000 = 50 %.
    records = [("chrom", "ACGT" * 25_000), ("plasmid", "GGCA" * 1000), ("junk", "AT" * 1000)]
    notes = {"chrom": ContigAnnotation(coverage=50, circular=circular), "plasmid": ContigAnnotation(coverage=250),
             "junk": ContigAnnotation(coverage=5)}
    return compute_assembly_stats(fasta(tmp_path / "mixed.fa", records), notes)


def test_warnings_for_coverage_gc_and_circularity(tmp_path):
    stats = _mixed(tmp_path)
    assert stats["coverage"]["length_weighted_median"] == 50.0
    warnings, checks = assembly_warnings(stats, "long")
    by_code = {w["code"]: w for w in warnings}
    assert set(by_code) == {"low_coverage_contigs", "high_coverage_contigs", "chromosome_not_circular",
                            "gc_outlier_contigs"}
    assert all(w["heuristic"] for w in warnings)
    # 5 < 0.25 x 50 = 12.5; 250 > 4 x 50 = 200.
    assert by_code["low_coverage_contigs"]["contigs"] == ["junk"]
    assert by_code["high_coverage_contigs"]["contigs"] == ["plasmid"]
    assert by_code["high_coverage_contigs"]["params"] == {"median_coverage": 50.0, "ratio": 4.0, "count": 1}
    # 100 kb >= 50 % of the 106 kb assembly and reported as not circular.
    assert by_code["chromosome_not_circular"]["contigs"] == ["chrom"]
    assert by_code["chromosome_not_circular"]["params"] == {"min_length": 53_000, "basis": "total_length"}
    # |75 - 50| and |0 - 50| > 10 points; the chromosome is at 50 %.
    assert sorted(by_code["gc_outlier_contigs"]["contigs"]) == ["junk", "plasmid"]
    assert {c["code"]: c["evaluated"] for c in checks} == {
        "many_contigs": True, "genome_size_mismatch": False, "low_coverage_contigs": True,
        "high_coverage_contigs": True, "chromosome_not_circular": True, "gc_outlier_contigs": True}
    assert next(c for c in checks if c["code"] == "genome_size_mismatch")["skipped_reason"].startswith("no expected")

    warnings, _ = assembly_warnings(_mixed(tmp_path, circular=True), "long")
    assert "chromosome_not_circular" not in {w["code"] for w in warnings}


def test_genome_size_warning_uses_a_20_percent_tolerance(tmp_path):
    stats = _mixed(tmp_path, circular=True)  # 106,000 bp
    assert "genome_size_mismatch" not in {w["code"] for w in assembly_warnings(stats, "long", 90_000)[0]}  # +17.8 %
    (w,) = [w for w in assembly_warnings(stats, "long", 200_000)[0] if w["code"] == "genome_size_mismatch"]
    assert w["params"]["difference_percent"] == -47.0 and "below" in w["message"]
    # With an expected size, "chromosome-sized" is relative to it: 100 kb < 50 % of 250 kb.
    _, checks = assembly_warnings(stats, "long", 250_000)
    chrom = next(c for c in checks if c["code"] == "chromosome_not_circular")
    assert chrom["evaluated"] is False and chrom["skipped_reason"] == "no contig is chromosome-sized"


def test_many_contigs_threshold_depends_on_mode(tmp_path):
    records = [(f"k{i}", "ACGT" * 250) for i in range(12)]  # 12 kb, counted as 1 Mb
    stats = compute_assembly_stats(fasta(tmp_path / "frag.fa", records))
    (w,) = [w for w in assembly_warnings(stats, "long")[0] if w["code"] == "many_contigs"]
    assert w["params"]["limit_per_mb"] == 10 and w["params"]["per_mb"] == 12
    assert not [w for w in assembly_warnings(stats, "short")[0] if w["code"] == "many_contigs"]
    with pytest.raises(ValueError):
        assembly_warnings(stats, "metagenome")


def test_checks_are_skipped_without_assembler_annotations(tmp_path):
    stats = compute_assembly_stats(fasta(tmp_path / "a.fa", RECORDS))
    warnings, checks = assembly_warnings(stats, "short")
    assert warnings == []
    skipped = {c["code"]: c["skipped_reason"] for c in checks if not c["evaluated"]}
    assert skipped == {
        "genome_size_mismatch": "no expected genome size is known for this sample",
        "low_coverage_contigs": "the assembler reported coverage for fewer than two contigs",
        "high_coverage_contigs": "the assembler reported coverage for fewer than two contigs",
        "chromosome_not_circular": "no contig is chromosome-sized",
        "gc_outlier_contigs": "fewer than two contigs are long enough",
    }
