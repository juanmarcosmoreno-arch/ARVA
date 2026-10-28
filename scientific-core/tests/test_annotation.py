"""arva_core.annotation: identifier links, cross-reference sorting, coverage and summary, queries and subsets."""
import pytest

from arva_core.annotation import (
    covered_bases,
    fasta_record,
    fasta_subset,
    genbank_subset,
    gff3_attributes,
    gff3_subset,
    links,
    new_feature,
    query,
    read_jsonl,
    region_features,
    sort_xrefs,
    span_length,
    summarize,
    tool_contig,
    write_jsonl,
    xref_url,
)

SEQS = [{"id": "contig_1", "original_id": "chr", "length": 10_000}, {"id": "contig_2", "original_id": "p1",
                                                                       "length": 2_000}]


def cds(i, contig, start, end, **kw):
    return new_feature(id=i, contig=contig, start=start, end=end, type="cds", strand="+",
                       length=span_length(start, end, kw.get("edge", False), 10_000),
                       hypothetical=kw.pop("hypothetical", False), **kw)


@pytest.mark.parametrize("xref, url", [
    ("EC:3.2.2.21", "https://enzyme.expasy.org/EC/3.2.2.21"),
    ("GO:0005840", "https://www.ebi.ac.uk/QuickGO/term/GO:0005840"),
    ("SO:0000652", "https://identifiers.org/SO:0000652"),
    ("COG:COG0122", "https://www.ncbi.nlm.nih.gov/research/cog/cog/COG0122/"),
    ("COG:L", "https://www.ncbi.nlm.nih.gov/research/cog/cogcategory/L/"),
    ("KEGG:K01985", "https://www.kegg.jp/entry/K01985"),
    ("RFAM:RF00001", "https://rfam.org/family/RF00001"),
    ("Pfam:PF00730", "https://www.ebi.ac.uk/interpro/entry/pfam/PF00730/"),
    ("UniRef:UniRef90_P04395", "https://www.uniprot.org/uniref/UniRef90_P04395"),
    ("UniParc:UPI000002ED67", "https://www.uniprot.org/uniparc/UPI000002ED67/entry"),
    ("UniProtKB:P04395", "https://www.uniprot.org/uniprotkb/P04395/entry"),
    ("RefSeq:WP_000004851.1", "https://www.ncbi.nlm.nih.gov/protein/WP_000004851.1"),
])
def test_links_for_reported_identifiers(xref, url):
    assert xref_url(xref) == url


@pytest.mark.parametrize("xref", [
    "EC:3.2.2.-", "EC:3.2.2.21<script>", "GO:12345", "KEGG:K1", "RFAM:RF1", "COG:COG12", "UniProtKB:P0439",
    "IS:ISEc1", "VFDB:VFG000001", "amrfinder:blaTEM", "nodb", "RefSeq:WP_1\"onclick=x", "UniRef:UniRef90_P04395/../x",
])
def test_no_link_for_other_or_malformed_identifiers(xref):
    assert xref_url(xref) is None


def test_links_are_unique_and_include_evidence_accessions():
    f = new_feature(db_xrefs=["EC:1.1.1.1", "EC:1.1.1.1", "IS:ISX"], accessions=["UniProtKB:P04395"])
    assert [link["xref"] for link in links(f)] == ["EC:1.1.1.1", "UniProtKB:P04395"]


def test_sort_xrefs():
    out = sort_xrefs(["EC:1.2.3.4", "EC:1.2.3.-", "COG:COG0001", "COG:KL", "GO:0005524", "GO:0005524", "KEGG:K1"])
    assert out == {"ec": ["1.2.3.4", "1.2.3.-"], "cog": ["COG0001"], "cog_categories": ["K", "L"],
                   "go": ["GO:0005524"]}


def test_unknown_feature_field_is_refused():
    with pytest.raises(KeyError):
        new_feature(colour="red")


def test_covered_bases_counts_overlaps_once_and_wraps_the_origin():
    fs = [cds(1, "contig_1", 1, 100), cds(2, "contig_1", 51, 150), cds(3, "contig_1", 9_901, 50, edge=True),
          cds(4, "contig_2", 10, 19)]
    assert fs[2]["length"] == 150
    assert covered_bases(fs, {"contig_1": 10_000, "contig_2": 2_000}) == 150 + 100 + 10


def test_summary_counts_hypothetical_and_coding_density():
    fs = [cds(1, "contig_1", 1, 300, hypothetical=True), cds(2, "contig_1", 401, 700, ec=["1.1.1.1"],
                                                               cog_categories=["C"]),
          new_feature(id=3, type="trna", contig="contig_1", start=800, end=875), new_feature(id=4, type="gap",
                                                                                          contig="contig_2", start=1,
                                                                                          end=100)]
    s = summarize(fs, SEQS, non_n_bases=11_900, cds_searched=True)
    assert s["counts"] == {"cds": 2, "trna": 1, "gap": 1}
    assert (s["cds"], s["hypothetical"], s["characterised"], s["hypothetical_fraction"]) == (2, 1, 1, 0.5)
    assert s["coding_density"]["value"] == round(600 / 11_900, 6) and s["with_ec"] == 1
    assert s["cog_categories"] == {"C": 1}
    skipped = summarize(fs[2:], SEQS, non_n_bases=11_900, cds_searched=False)
    assert skipped["cds"] is None and skipped["coding_density"]["value"] is None and skipped["hypothetical"] is None


def test_query_filters_region_text_sort_and_bounds():
    fs = [cds(1, "contig_1", 1, 300, gene="dnaA", product="chromosomal replication initiator"),
          cds(2, "contig_1", 9_901, 50, edge=True, product="hypothetical protein", hypothetical=True),
          new_feature(id=3, type="trna", contig="contig_1", start=800, end=875, product="tRNA-Leu",
                      locus_tag="SYNT_03"),
          cds(4, "contig_2", 10, 400, db_xrefs=["EC:2.7.7.7"], ec=["2.7.7.7"])]
    assert query(fs, SEQS)["total"] == 4
    assert [f["id"] for f in query(fs, SEQS, types=["trna"])["items"]] == [3]
    assert [f["id"] for f in query(fs, SEQS, contig="chr", start=20, end=60)["items"]] == [1, 2]
    assert [f["id"] for f in query(fs, SEQS, q="DNAA")["items"]] == [1]
    assert [f["id"] for f in query(fs, SEQS, q="2.7.7")["items"]] == [4]
    assert [f["id"] for f in query(fs, SEQS, q="synt_03")["items"]] == [3]
    assert [f["id"] for f in query(fs, SEQS, hypothetical=True)["items"]] == [2]
    assert [f["id"] for f in query(fs, SEQS, hypothetical=False)["items"]] == [1, 4]
    assert [f["id"] for f in query(fs, SEQS, sort="length", descending=True)["items"]] == [4, 1, 2, 3]
    assert [f["id"] for f in query(fs, SEQS, sort="gene")["items"]] == [1, 2, 3, 4]
    page = query(fs, SEQS, limit=2, offset=2)
    assert page["total"] == 4 and [f["id"] for f in page["items"]] == [3, 4]
    assert query(fs, SEQS, contig="nope")["total"] == 0
    with pytest.raises(ValueError):
        query(fs, SEQS, limit=1001)
    with pytest.raises(ValueError):
        query(fs, SEQS, start=5)
    with pytest.raises(ValueError):
        query(fs, SEQS, sort="colour")


def test_region_features_by_either_name_and_across_the_origin():
    fs = [cds(1, "contig_1", 1, 300), cds(2, "contig_1", 9_901, 50, edge=True), cds(3, "contig_1", 800, 875),
          cds(4, "contig_2", 10, 400)]
    assert tool_contig(SEQS, "chr") == tool_contig(SEQS, "contig_1") == "contig_1" and tool_contig(SEQS, "x") is None
    assert [f["id"] for f in region_features(fs, SEQS, "chr", 250, 800)] == [1, 3]
    assert [f["id"] for f in region_features(fs, SEQS, "contig_1", 9_950, 10_000)] == [2]  # the part before the origin
    assert [f["id"] for f in region_features(fs, SEQS, "contig_1", 40, 45)] == [1, 2]  # and the part after it
    assert [f["id"] for f in region_features(fs, SEQS, "p1", 400, 400)] == [4]
    assert region_features(fs, SEQS, "contig_1", 301, 799) == [] and region_features(fs, SEQS, "x", 1, 9) == []


def test_jsonl_round_trip(tmp_path):
    rows = [new_feature(id=1, product="ß-lactamase"), new_feature(id=2)]
    assert write_jsonl(tmp_path / "f.jsonl", rows) == 2
    assert read_jsonl(tmp_path / "f.jsonl") == rows


GFF = """##gff-version 3
##feature-ontology https://example.org/so.obo
# Annotated with a tool
##sequence-region c1 1 1000
##sequence-region c2 1 500
c1\tT\tgene\t1\t300\t.\t+\t.\tID=A_gene;locus_tag=A
c1\tT\tCDS\t1\t300\t.\t+\t0\tID=A;Parent=A_gene;locus_tag=A;product=x%3B y
c1\tT\tCDS\t400\t600\t.\t-\t0\tID=B;locus_tag=B
c2\tT\tgap\t1\t100\t.\t.\t.\tID=G
##FASTA
>c1
ACGT
"""


def test_gff3_subset_and_attributes():
    out = gff3_subset(GFF, {"A", "G"})
    lines = out.splitlines()
    assert lines[:3] == ["##gff-version 3", "##feature-ontology https://example.org/so.obo", "# Annotated with a tool"]
    assert "##sequence-region c1 1 1000" in lines and "##sequence-region c2 1 500" in lines
    assert [ln.split("\t")[2] for ln in lines if not ln.startswith("#")] == ["gene", "CDS", "gap"]
    assert "##FASTA" not in out and "ID=B" not in out
    assert gff3_attributes("ID=A;product=x%3B y;inference=a,b%2Cc")["inference"] == ["a", "b,c"]
    assert gff3_attributes("ID=A;product=x%3B y")["product"] == ["x; y"]


GBK = """LOCUS       c1   20 bp    DNA     linear       20-OCT-2026
FEATURES             Location/Qualifiers
     source          1..20
                     /mol_type="genomic DNA"
     gene            1..9
                     /locus_tag="A"
     CDS             1..9
                     /locus_tag="A"
                     /product="x"
     CDS             complement(10..18)
                     /locus_tag="B"
ORIGIN
        1 acgtacgtac gtacgtacgt
//
LOCUS       c2   10 bp    DNA     linear       20-OCT-2026
FEATURES             Location/Qualifiers
     source          1..10
     CDS             1..9
                     /locus_tag="C"
ORIGIN
        1 acgtacgtac
//
"""


def test_genbank_subset_keeps_source_headers_and_sequence():
    out = genbank_subset(GBK, {"A"})
    assert out.count("LOCUS") == 1 and "     source          1..20" in out and out.count('/locus_tag="A"') == 2
    assert '/locus_tag="B"' not in out and "        1 acgtacgtac gtacgtacgt" in out and out.endswith("//\n")
    assert genbank_subset(GBK, {"nothing"}) == ""


def test_fasta_subset_and_record(tmp_path):
    text = ">A product one\nACGT\nAC\n>B\nGG\n>AB\nTT\n"
    assert fasta_subset(text, {"A", "AB"}, width=3) == ">A product one\nACG\nTAC\n>AB\nTT\n"
    (tmp_path / "x.fa").write_text(text)
    assert fasta_record(tmp_path / "x.fa", "B") == ("B", "GG")
    assert fasta_record(tmp_path / "x.fa", "C") is None
    assert fasta_record(tmp_path / "missing.fa", "A") is None
