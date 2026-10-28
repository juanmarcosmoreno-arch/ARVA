"""arva_core.annotation_stats: the numbers behind the annotation charts. Features are made up for the arithmetic (every
expected value is worked out in the comments); they are not biology."""
import pytest

from arva_core.annotation import new_feature
from arva_core.annotation_stats import (
    COG_CATEGORIES,
    annotation_charts,
    cog_profile,
    density_window,
    gene_density,
    hypothetical_counts,
    length_histogram,
    middle_base,
    nice125,
    strand_counts,
    type_counts,
)

SEQS = [{"id": "c1", "original_id": "contig_1", "length": 2_500}, {"id": "c2", "original_id": "plasmid", "length": 1_000}]


def f(n, contig, start, end, strand="+", type="cds", hypothetical=False, **kw):
    length = kw.pop("length", None) or (end - start + 1 if start <= end else 0)
    return new_feature(id=n, contig=contig, start=start, end=end, strand=strand, type=type, length=length,
                       hypothetical=hypothetical if type in ("cds", "sorf") else None, **kw)


FEATURES = [
    f(1, "c1", 1, 300),                                   # middle 150 -> window 1
    f(2, "c1", 1_001, 1_090, "-", "trna"),                # middle 1045 -> window 2
    f(3, "c1", 1_201, 1_800, "-", hypothetical=True),     # middle 1500 -> window 2
    f(4, "c1", 2_001, 2_500, "+", "crispr"),              # not a gene
    f(5, "c2", 901, 100, "+", edge=True, length=200),     # across the origin: 901-1000 and 1-100, middle 1000
    f(6, "c2", 300, 359, ".", "ncrna"),                   # no strand
    f(7, "c2", 400, 999, "-", cog_categories=["J", "K"], cog=["COG0001"]),  # middle 699
]


def test_nice125_and_window():
    assert [nice125(x) for x in (0.4, 1, 3, 7.5, 11, 25, 100, 101)] == [1, 1, 5, 10, 20, 50, 100, 200]
    # the longest sequence (2,500 bp) / 100 windows = 25 bp, but windows are at least 1 kb
    assert density_window(SEQS) == 1_000
    assert density_window([{"id": "x", "length": 5_000_000}]) == 50_000


def test_middle_base_including_across_the_origin():
    assert middle_base(FEATURES[0], 2_500) == 150        # 1-300: 1 + 299 // 2
    assert middle_base(FEATURES[4], 1_000) == 1_000      # 200 bases from 901: the 100th is 1000
    assert middle_base(f(9, "c2", 991, 10, edge=True, length=20), 1_000) == 1_000  # 991-1000, 1-10: 10th is 1000
    assert middle_base(f(9, "c2", 995, 10, edge=True, length=16), 1_000) == 2      # 995-1000, 1-10: 8th is 2


def test_gene_density_counts_each_gene_once_at_its_middle():
    d = gene_density(FEATURES, SEQS, window=1_000)
    c1, c2 = d["contigs"]
    assert c1["start"] == [1, 1_001, 2_001] and c1["end"] == [1_000, 2_000, 2_500]  # the last window is 500 bp
    assert (c1["forward"], c1["reverse"], c1["total"], c1["genes"]) == ([1, 0, 0], [0, 2, 0], [1, 2, 0], 3)
    # c2 has one window: the CDS across the origin (+), the ncRNA (.) and the CDS 400-999 (-)
    assert (c2["forward"], c2["reverse"], c2["unstranded"], c2["genes"]) == ([1], [1], [1], 3)
    assert c2["contig_in_assembly"] == "plasmid"
    with pytest.raises(ValueError, match="windows"):
        gene_density(FEATURES, [{"id": "big", "length": 10**9}], window=1)


def test_length_histogram_bins_classes_and_overflow():
    h = length_histogram(FEATURES, width=100)
    # gene lengths: CDS 300 (characterised), 600 (hypothetical), 200 (characterised), 600 (characterised);
    # tRNA 90, ncRNA 60. 99th percentile (nearest rank) of 6 values = the 6th = 600 -> regular bins 0-699
    assert [b["min"] for b in h["bins"]] == list(range(0, 700, 100))
    assert h["bins"][0]["rna"] == 2 and h["bins"][2]["cds_characterised"] == 1 and h["bins"][3]["cds_characterised"] == 1
    assert h["bins"][6]["cds_characterised"] == 1 and h["bins"][6]["cds_hypothetical"] == 1
    assert h["classes"]["cds_characterised"] == {"n": 3, "min": 200, "median": 300, "mean": 366.7, "max": 600}
    assert h["classes"]["sorf"]["n"] == 0
    many = [f(i, "c1", 1, 100) for i in range(1, 100)] + [f(100, "c1", 1, 9_000, length=9_000)]
    over = length_histogram(many)
    # 99th percentile of 99 x 100 bp and one 9 kb CDS = 100 bp; width 10 bp (the minimum) -> bins 0-109 and >= 110
    assert over["width"] == 10 and over["bins"][-1] == {"min": 110, "max": None, "cds_characterised": 1,
                                                       "cds_hypothetical": 0, "sorf": 0, "rna": 0}
    assert length_histogram([])["bins"] == []


def test_strand_counts_by_type_and_sequence():
    s = strand_counts(FEATURES, SEQS)
    assert s["total"] == {"+": 2, "-": 3, ".": 1}
    assert s["by_type"] == {"cds": {"+": 2, "-": 2, ".": 0}, "trna": {"+": 0, "-": 1, ".": 0},
                            "ncrna": {"+": 0, "-": 0, ".": 1}}
    assert s["by_contig"][0] == {"contig": "c1", "contig_in_assembly": "contig_1", "+": 1, "-": 2, ".": 0}
    assert s["replication_strand"] == "not_determined"


def test_cog_profile_and_hypothetical_counts():
    cog = cog_profile(FEATURES, True)
    assert cog["reported"] and cog["cds_with_category"] == 1 and cog["cds_with_cog_id"] == 1 and cog["cds"] == 4
    assert [(c["letter"], c["cds"]) for c in cog["categories"]] == [("J", 1), ("K", 1)]
    assert cog["categories"][0]["name"] == COG_CATEGORIES["J"] == "Translation, ribosomal structure and biogenesis"
    assert len(COG_CATEGORIES) == 26
    none = cog_profile([f(1, "c1", 1, 300, cog=["COG0122"])], True)
    assert not none["reported"] and none["cds_with_cog_id"] == 1 and none["categories"] == []
    h = hypothetical_counts(FEATURES, SEQS, True)
    assert h["total"] == {"characterised": 3, "hypothetical": 1}
    assert [(r["characterised"], r["hypothetical"]) for r in h["by_contig"]] == [(1, 1), (2, 0)]
    assert hypothetical_counts(FEATURES, SEQS, False) == {"cds_searched": False, "by_contig": [], "total": None}


def test_type_counts_and_the_whole_set():
    t = type_counts(FEATURES, SEQS)
    assert t["types"] == ["cds", "trna", "ncrna", "crispr"] and t["total"]["cds"] == 4
    assert t["by_contig"][1]["counts"] == {"cds": 2, "ncrna": 1}
    charts = annotation_charts(FEATURES, SEQS, cds_searched=False)
    assert charts["genes"] == 6 and charts["cog"]["cds"] is None and charts["hypothetical"]["total"] is None
    assert charts["density"]["window"] == 1_000
