import pytest

from arva_core import variants as v

# Records as bcftools 1.19 wrote them (mpileup | call --ploidy 1 -m -v | norm | filter | csq) on simulated reads of a
# constructed genome (workflows/tool-adapters/tests/test_variant_tools.py); the "##" header is shortened.
VCF = """##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSIM1
chr1\t1010\t.\tT\tA\t225.417\tPASS\tDP=34;AD=0,34;MQ=60;BCSQ=missense|geneA|g1|protein_coding|+|4F>4I|1010T>A\tGT:PL:DP:AD\t1:255,0:34:0,34
chr1\t1150\t.\tT\tA\t225.417\tPASS\tDP=34;BCSQ=synonymous|geneA|g1|protein_coding|+|50S|1150T>A\tGT:PL:DP:AD\t1:255,0:34:0,33
chr1\t5300\t.\tC\tT\t225.417\tPASS\tDP=28;BCSQ=missense|geneB|g2|protein_coding|-|1V>1M|5300C>T\tGT:PL:DP:AD\t1:255,0:28:0,28
chr1\t15000\t.\tG\tGGA\t225.417\tPASS\tINDEL;IDV=31\tGT:PL:DP:AD\t1:255,0:31:0,31
chr1\t24999\t.\tGTAT\tG\t228.352\tLowAltFraction\tINDEL\tGT:PL:DP:AD\t1:255,0:24:3,21
chr1\t26000\t.\tA\tC\t40.1\tLowQual;LowDepth\t.\tGT:PL:DP:AD\t1:70,0:4:0,4
"""


def test_parse_vcf_reads_records_bcsq_and_fractions():
    samples, rows = v.parse_vcf(VCF.splitlines())
    assert samples == ["SIM1"]
    assert [r["type"] for r in rows] == ["snp", "snp", "snp", "insertion", "deletion", "snp"]
    first = rows[0]
    assert first["depth"] == 34 and first["alt_fraction"] == 1.0 and first["pass"]
    assert first["effect"] == "missense"
    assert first["consequences"][0]["aa_change"] == "4F>4I" and first["consequences"][0]["gene"] == "geneA"
    deletion = rows[4]
    assert deletion["end"] == 25002 and deletion["filters"] == ["LowAltFraction"]
    assert deletion["alt_fraction"] == pytest.approx(21 / 24, abs=1e-4)
    assert rows[5]["filters"] == ["LowQual", "LowDepth"] and not rows[5]["pass"]
    assert rows[3]["effect"] is None


def test_parse_vcf_rejects_multiallelic_and_bad_positions():
    with pytest.raises(ValueError, match="several ALT"):
        v.parse_vcf(["chr1\t5\t.\tA\tC,G\t50\tPASS\t."])
    with pytest.raises(ValueError, match="valid position"):
        v.parse_vcf(["chr1\tx\t.\tA\tC\t50\tPASS\t."])


def test_bcsq_compound_terms_and_redirects():
    rows = v.parse_bcsq("@1010,frameshift&stop_gained|g|t|protein_coding|+|5K>5*|.")
    assert rows[0] == {"see_position": 1010}
    assert rows[1]["terms"] == ["frameshift", "stop_gained"]
    assert v.main_effect(rows) == "stop_gained"
    after = v.parse_bcsq("*missense|PER3|ENST1|protein_coding|+|1028M>1028T|7890117T>C")
    assert after[0]["after_stop"] and after[0]["terms"] == ["missense"]


def test_csq_gff_writes_ensembl_style_and_counts_skips():
    features = [
        {"id": 1, "type": "cds", "contig": "c1", "start": 1, "end": 300, "strand": "+", "locus_tag": "AB_1",
         "gene": "dnaA"},
        {"id": 2, "type": "cds", "contig": "c1", "start": 400, "end": 501, "strand": "-", "locus_tag": "AB;2"},
        {"id": 3, "type": "cds", "contig": "c1", "start": 600, "end": 700, "strand": "+", "locus_tag": "AB_3"},
        {"id": 4, "type": "cds", "contig": "c1", "start": 900, "end": 30, "strand": "+", "edge": True},
        {"id": 5, "type": "cds", "contig": "c1", "start": 10, "end": 30, "pseudo": True},
        {"id": 6, "type": "trna", "contig": "c1", "start": 10, "end": 90},
        {"id": 7, "type": "cds", "contig": "zz", "start": 1, "end": 30},
    ]
    text, counts = v.csq_gff(features, {"c1": "contig_1"}, {"contig_1": 1000})
    lines = text.strip().split("\n")
    assert lines[1] == "contig_1\tARVA\tgene\t1\t300\t.\t+\t.\tID=gene:AB_1;biotype=protein_coding;Name=dnaA"
    assert lines[3] == "contig_1\tARVA\tCDS\t1\t300\t.\t+\t0\tParent=transcript:AB_1"
    assert "ID=gene:AB_2" in text
    assert counts == {"written": 2, "pseudo": 1, "wraps_origin": 1, "not_multiple_of_3": 1, "unknown_contig": 1}


def test_start_codon_notes_mark_non_atg_starts_on_both_strands():
    seq = "GTG" + "AAA" * 10 + "TAA" + "CCC" + v.revcomp("TTG" + "AAA" * 3 + "TAA")
    plus_end = 36
    minus_start, minus_end = plus_end + 4, len(seq)
    features = [{"type": "cds", "contig": "c", "start": 1, "end": plus_end, "strand": "+"},
                {"type": "cds", "contig": "c", "start": minus_start, "end": minus_end, "strand": "-"}]
    rows = [{"contig": "c", "pos": 2, "end": 2}, {"contig": "c", "pos": minus_end, "end": minus_end},
            {"contig": "c", "pos": 10, "end": 10}]
    assert v.start_codon_notes(rows, features, {}, {"c": seq}) == 2
    assert rows[0]["start_codon"] == "GTG" and rows[1]["start_codon"] == "TTG" and "start_codon" not in rows[2]


def test_low_depth_intervals_merge_runs():
    rows = [("c", p, d) for p, d in enumerate([0, 3, 12, 12, 9, 9, 9, 15], 1)]
    out = v.low_depth_intervals(rows, 10)
    assert out["intervals"] == {"c": [[1, 2], [5, 7]]}
    assert out["contigs"]["c"] == {"positions": 8, "callable": 3, "mean_depth": 8.62}


def test_distribution_bins_and_summary():
    _, rows = v.parse_vcf(VCF.splitlines())
    d = v.distribution(rows, {"chr1": 30000})
    assert d["bin"] == 100
    c = d["contigs"][0]
    assert sum(c["snp"]) == 3 and sum(c["other"]) == 1
    s = v.summarize(rows)
    assert s["records"] == 6 and s["pass"] == 4
    assert s["by_type"]["snp"] == 3 and s["by_type"]["insertion"] == 1
    assert s["by_filter"] == {"LowAltFraction": 1, "LowQual": 1, "LowDepth": 1}
    assert s["by_effect"] == {"missense": 2, "synonymous": 1, "none": 1}
    assert sum(s["depth_histogram"]["pass"]) == 4


def _rec(pos, ref, alt, ok=True, contig="c"):
    return {"contig": contig, "pos": pos, "end": pos + len(ref) - 1, "ref": ref, "alt": alt,
            "type": v.variant_type(ref, alt), "pass": ok}


def test_snp_matrix_missing_rules_and_distances():
    a = {"id": "a", "label": "A", "variants": [_rec(10, "A", "G"), _rec(20, "C", "T")], "low_depth": {}}
    b = {"id": "b", "label": "B", "variants": [_rec(10, "A", "G"), _rec(30, "G", "A", ok=False),
                                                 _rec(39, "TCAG", "T")], "low_depth": {"c": [[18, 22]]}}
    c = {"id": "c", "label": "C", "variants": [_rec(30, "G", "A"), _rec(40, "C", "A")], "low_depth": {}}
    m = v.snp_matrix([a, b, c])
    assert [s["pos"] for s in m["sites"]] == [10, 20, 30, 40]
    # b: 20 is low depth, 30 failed a filter, 40 lies inside its PASS deletion (39 is the anchor base).
    assert m["alleles"] == ["GTGC", "GNNN", "ACAA"]
    assert m["distances"] == [[0, 0, 4], [0, 0, 1], [4, 1, 0]]
    assert m["compared_sites"][0][1] == 1 and m["compared_sites"][0][2] == 4
    assert m["core_sites"] == 1 and m["missing"] == [0, 3, 0]


def test_nice_bin():
    assert v.nice_bin(2_872_769) == 10_000
    assert v.nice_bin(300) == 1
    assert v.nice_bin(1000) == 5
