"""Sanger reads: .ab1 reading, trimming, reverse complement, the F+R consensus and the reading of hits. The .ab1 files
are Biopython 1.88's public test chromatograms (fixtures/sanger/README.md); hit rows are built around the thresholds,
and the real BLAST outputs are tested in workflows/tool-adapters/tests/test_sanger_tools.py."""
from dataclasses import replace
from pathlib import Path

import pytest

from arva_core import sanger
from arva_core.sanger import (
    CLSI_16S,
    ConsensusParams,
    SangerRead,
    compare_suspected,
    consensus,
    hits_from_hsps,
    interpret_16s,
    mixed_peaks,
    mott_trim,
    name_by_features,
    ncbi_accession,
    parse_16s_title,
    parse_abricate_id,
    parse_mlst_allele,
    parse_sequence_text,
    peak_heights,
    rank_hits,
    read_abi,
    reverse_complement,
    trace_view,
    trim_read,
)

FX = Path(__file__).parent / "fixtures" / "sanger"


def codes(items):
    return [x["code"] for x in items]


@pytest.fixture(scope="module")
def r3100():
    return read_abi(FX / "3100.ab1")


# --- Reading ------------------------------------------------------------------------------------------------------

def test_read_abi_3100(r3100):
    r = r3100
    assert (r.name, r.sample, len(r), r.source_format) == ("3100", "16S_S2_1387R", 795, "abi")
    assert r.instrument["model"] == "3100" and r.instrument["basecaller"] == "KB 1.4.1.8"
    assert r.instrument["base_order"] == "GATC" and r.instrument["run_date"] == "2010-01-27"
    assert r.has_qualities and r.has_trace and r.warnings == []
    assert len(r.qualities) == len(r.peaks) == 795 and set(r.traces) == set("ACGT")
    assert all(len(v) == 10303 for v in r.traces.values())
    assert r.peaks == sorted(r.peaks)
    # The channel mapping (DATA9+i is base FWO_1[i]) checked on the real trace.
    top = [max(peak_heights(r, i).items(), key=lambda kv: kv[1])[0] for i in range(20, 580)]
    assert sum(t == r.bases[i] for t, i in zip(top, range(20, 580), strict=True)) == 560
    s = r.summary()
    assert s["mean_quality"] == 46.8 and s["has_trace"] and s["trim"] is None


def test_read_abi_from_bytes_matches_the_file(r3100):
    b = read_abi((FX / "3100.ab1").read_bytes(), name="upload")
    assert b.name == "upload" and b.bases == r3100.bases and b.qualities == r3100.qualities
    assert b.peaks == r3100.peaks


def test_read_abi_without_qualities():
    r = read_abi(FX / "310.ab1")
    assert len(r) == 868 and not r.has_qualities and codes(r.warnings) == ["no_qualities"]
    assert r.summary()["mean_quality"] is None
    t = trim_read(r)
    assert t.trim["method"] == "none" and len(t) == 868
    assert codes(t.warnings) == ["no_qualities", "not_trimmed_no_qualities"]


@pytest.mark.parametrize("data", [(FX / "fake.ab1").read_bytes(), b"", (FX / "3100.ab1").read_bytes()[:2000]])
def test_read_abi_rejects_broken_files(data):
    with pytest.raises(ValueError):
        read_abi(data)


def test_parse_sequence_text_fasta_and_seq():
    reads = parse_sequence_text("﻿>r1 forward read\nacgt\nNNRY\n>r2\nGGCC\n")
    assert [(r.name, r.bases, r.source_format) for r in reads] == [("r1", "ACGTNNRY", "fasta"), ("r2", "GGCC", "fasta")]
    assert not reads[0].has_qualities and codes(reads[0].warnings) == ["no_qualities"]
    (seq,) = parse_sequence_text("ACGT ACGT\r\nTTTT\n", name="sample-F")
    assert (seq.name, seq.bases, seq.source_format) == ("sample-F", "ACGTACGTTTTT", "seq")
    for bad, msg in (("ACGU", "not DNA"), (">x\n\n", "no sequence"), ("hello\n>x\nACGT", "before the first"),
                     ("", "no sequence"), ("ACGT-ACGT", "not DNA")):
        with pytest.raises(ValueError, match=msg):
            parse_sequence_text(bad)


def test_read_validates_lengths():
    with pytest.raises(ValueError, match="qualities has 2 values for 3 bases"):
        SangerRead(name="x", bases="ACG", source_format="seq", qualities=[1, 2])


# --- Trimming -----------------------------------------------------------------------------------------------------

def test_mott_trim_3100(r3100):
    t = mott_trim(r3100.qualities, 0.05)
    assert (t["start"], t["end"], t["length"], t["mean_quality"], t["q20_percent"]) == (19, 697, 679, 53.0, 97.8)
    loose, strict = mott_trim(r3100.qualities, 0.2), mott_trim(r3100.qualities, 0.01)
    assert loose["length"] >= t["length"] >= strict["length"]
    tr = trim_read(r3100)
    assert len(tr) == 679 and tr.bases == r3100.bases[18:697] and tr.origin[0] == 18 and tr.peaks[0] == r3100.peaks[18]
    assert tr.trim["start"] == 19 and tr.traces is r3100.traces
    with pytest.raises(ValueError, match="already trimmed"):
        trim_read(tr)


def test_mott_trim_starts_after_the_last_zero():
    # A good base, a bad stretch that returns the running sum to zero, then the good segment: the kept part is the
    # maximum-scoring segment (bases 5-10), not from the first positive base (Biopython's abi-trim start).
    q = [40, 2, 2, 2, 40, 40, 40, 40, 40, 40, 2, 2]
    t = mott_trim(q, 0.05)
    assert (t["start"], t["end"]) == (5, 10)
    assert mott_trim([40] * 5)["length"] == 5
    none = mott_trim([0, 1, 2, 3])
    assert none["start"] is None and none["length"] == 0 and none["mean_quality"] is None
    for bad in (0, 1, -0.1):
        with pytest.raises(ValueError):
            mott_trim(q, bad)


def test_trim_read_manual_and_nothing_kept(r3100):
    m = trim_read(r3100, manual=(10, 20))
    assert m.bases == r3100.bases[9:20] and m.trim == {"method": "manual", "limit": None, "original_length": 795,
                                                       "start": 10, "end": 20, "length": 11}
    with pytest.raises(ValueError, match="within 1-795"):
        trim_read(r3100, manual=(0, 5))
    low = SangerRead(name="low", bases="ACGT", source_format="abi", qualities=[1, 2, 1, 2])
    t = trim_read(low)
    assert len(t) == 0 and codes(t.warnings) == ["nothing_kept"]


# --- Orientation, peaks and the trace view --------------------------------------------------------------------------

def test_reverse_complement(r3100):
    rc = reverse_complement(r3100)
    assert rc.bases[:5] == sanger.reverse_complement(SangerRead("x", r3100.bases[-5:], "seq")).bases
    assert rc.strand == "-" and rc.origin[0] == 794 and rc.qualities[0] == r3100.qualities[-1]
    assert reverse_complement(rc).bases == r3100.bases
    h, hrc = peak_heights(r3100, 794), peak_heights(rc, 0)
    assert hrc == {"T": h["A"], "G": h["C"], "C": h["G"], "A": h["T"]}
    iupac = SangerRead("x", "ACGTNRYSWKMBDHV", "seq")
    assert reverse_complement(iupac).bases == "BDHVKMWSRYNACGT"


def test_mixed_peaks(r3100):
    flagged = mixed_peaks(r3100)
    assert 0 < len(mixed_peaks(trim_read(r3100))) < len(flagged)
    assert all(f["ratio"] is None or f["ratio"] >= 0.33 or f["base"] not in "ACGT" for f in flagged)
    assert len(mixed_peaks(r3100, 1.0)) <= len(mixed_peaks(r3100, 0.5)) <= len(flagged)
    calls = mixed_peaks(SangerRead("x", "ACRN", "seq"))
    assert [(c["position"], c["base"], c["ratio"]) for c in calls] == [(3, "R", None), (4, "N", None)]
    with pytest.raises(ValueError):
        mixed_peaks(r3100, 0)


def test_trace_view_keeps_peaks(r3100):
    v = trace_view(r3100, max_points=1000)
    assert v["step"] == 11 and len(v["channels"]["G"]) <= 1000 and len(v["markers"]) == 795
    assert max(v["channels"]["A"]) == max(r3100.traces["A"])
    m = v["markers"][100]
    assert m["position"] == 101 and m["scan"] == r3100.peaks[100] and m["point"] == r3100.peaks[100] // 11
    w = trace_view(r3100, 1000, 2000, max_points=5000)
    assert w["step"] == 1 and len(w["channels"]["C"]) == 1000
    assert all(1000 <= x["scan"] < 2000 for x in w["markers"])
    with pytest.raises(ValueError):
        trace_view(SangerRead("x", "ACGT", "seq"))
    with pytest.raises(ValueError):
        trace_view(r3100, 50, 50)


# --- Consensus ----------------------------------------------------------------------------------------------------

def mutate(read: SangerRead, i: int, base: str | None = None, quality: int | None = None,
           delete: bool = False) -> SangerRead:
    bases, qual = list(read.bases), list(read.qualities)
    if delete:
        del bases[i], qual[i]
        peaks, origin = read.peaks[:i] + read.peaks[i + 1:], read.origin[:i] + read.origin[i + 1:]
        return replace(read, bases="".join(bases), qualities=qual, peaks=peaks, origin=origin)
    bases[i] = base or bases[i]
    qual[i] = qual[i] if quality is None else quality
    return replace(read, bases="".join(bases), qualities=qual)


@pytest.fixture(scope="module")
def pair(r3100):
    """A forward/reverse pair built from the trimmed 3100 read: forward = trimmed bases 1-500, reverse = the reverse
    complement of trimmed bases 181-679 (as a reverse read comes off the instrument); 320 bases overlap."""
    t = trim_read(r3100)
    fwd = replace(t, bases=t.bases[:500], qualities=t.qualities[:500], peaks=t.peaks[:500], origin=t.origin[:500])
    part = replace(t, bases=t.bases[180:], qualities=t.qualities[180:], peaks=t.peaks[180:], origin=t.origin[180:])
    return fwd, reverse_complement(part)


def test_consensus_of_agreeing_reads(pair):
    fwd, rev = pair
    c = consensus(fwd, rev)
    assert c["status"] == "ok" and c["sequence"] == trim_read(read_abi(FX / "3100.ab1")).bases
    assert c["overlap"]["columns"] == 320 and c["overlap"]["identity"] == 100.0
    assert (c["overlap"]["consensus_start"], c["overlap"]["consensus_end"]) == (181, 500)
    assert c["counts"] == {"agree": 320, "forward_only": 180, "reverse_only": 179, "resolved": 0, "unresolved": 0}
    assert c["conflicts"] == [] and c["warnings"] == [] and c["score"] == 640.0
    col = c["columns"][200]
    assert col["status"] == "agree" and col["forward"]["origin"] == col["reverse"]["origin"] == 219
    assert col["forward"]["heights"] == col["reverse"]["heights"]
    assert c["columns"][0]["status"] == "forward_only" and c["columns"][0]["reverse"] is None
    assert c["params"]["gap_open"] == -5.0 and c["forward"]["length"] == 500


def test_consensus_conflicts_by_quality(pair):
    fwd, rev = pair
    # Reverse-read index j holds trimmed base 679 - j; trimmed base 300 (0-based 299) is reverse index 379.
    base = fwd.bases[299]
    other = "A" if base != "A" else "C"
    weak = mutate(rev, 379, other.translate(sanger.COMPLEMENT), quality=5)
    c = consensus(fwd, weak)
    (conf,) = c["conflicts"]
    assert conf["status"] == "resolved" and conf["rule"] == "higher_quality" and conf["base"] == base
    assert conf["kind"] == "mismatch" and conf["reverse"]["base"] == other and conf["reverse"]["quality"] == 5
    assert c["sequence"] == consensus(fwd, rev)["sequence"]
    strong = mutate(rev, 379, other.translate(sanger.COMPLEMENT), quality=fwd.qualities[299])
    c2 = consensus(fwd, strong)
    (conf2,) = c2["conflicts"]
    assert conf2["status"] == "unresolved" and conf2["rule"] == "qualities_too_close"
    assert conf2["base"] == sanger.IUPAC_PAIR[frozenset((base, other))]
    assert codes(c2["warnings"]) == ["unresolved_conflicts"]
    no_call = mutate(rev, 379, "N", quality=fwd.qualities[299])
    (conf3,) = consensus(fwd, no_call)["conflicts"]
    assert (conf3["status"], conf3["rule"], conf3["base"]) == ("resolved", "no_call_in_other_read", base)


def test_consensus_gap_conflict(pair):
    fwd, rev = pair
    # A low-quality extra base in the forward read inside the overlap: dropped by the quality rule.
    ins = replace(fwd, bases=fwd.bases[:300] + "T" + fwd.bases[300:],
                  qualities=[*fwd.qualities[:300], 3, *fwd.qualities[300:]],
                  peaks=[*fwd.peaks[:300], fwd.peaks[300], *fwd.peaks[300:]],
                  origin=[*fwd.origin[:300], fwd.origin[300], *fwd.origin[300:]])
    c = consensus(ins, rev)
    gaps = [x for x in c["conflicts"] if x["kind"] == "gap"]
    assert len(gaps) == 1 and gaps[0]["status"] == "resolved" and gaps[0]["base"] == "" and gaps[0]["position"] is None
    assert c["sequence"] == consensus(fwd, rev)["sequence"] and c["overlap"]["gaps"] == 1
    # A base missing from the reverse read between two good bases, against a good forward base: unresolved (N).
    deleted = mutate(rev, 379, delete=True)
    (g2,) = consensus(fwd, deleted)["conflicts"]
    assert (g2["kind"], g2["status"], g2["rule"], g2["base"]) == ("gap", "unresolved", "qualities_too_close", "N")
    # The same with poor reverse bases on both sides of the gap: the forward base is kept.
    poor = mutate(mutate(deleted, 378, quality=4), 379, quality=4)
    (g3,) = consensus(fwd, poor)["conflicts"]
    assert (g3["status"], g3["rule"], g3["base"]) == ("resolved", "higher_quality", fwd.bases[299])


def test_consensus_without_qualities_never_resolves():
    f = parse_sequence_text(">f\n" + "ACGTTGCAAGCTTAGGCTAACGTAGCTAGCTTGACCGATCGATTACG")[0]
    r = reverse_complement(parse_sequence_text(">r\n" + "ACGTTGCAAGCTTAGGCTAACGTAGCTGGCTTGACCGATCGATTACG")[0])
    c = consensus(f, r)
    (conf,) = c["conflicts"]
    assert conf["status"] == "unresolved" and conf["rule"] == "no_qualities" and conf["base"] == "R"
    assert codes(c["warnings"]) == ["unresolved_conflicts", "conflicts_without_qualities"]


def test_consensus_no_overlap_and_orientation(pair):
    fwd, rev = pair
    unrelated = parse_sequence_text(">u\n" + "AC" * 150)[0]
    c = consensus(fwd, unrelated)
    assert c["status"] == "no_overlap" and c["sequence"] == "" and "no_overlap" in codes(c["warnings"])
    same_strand = reverse_complement(rev)  # a "reverse" read that is already in the forward orientation
    c2 = consensus(fwd, same_strand)
    assert "orientation_suspect" in codes(c2["warnings"])
    ok = consensus(fwd, same_strand, ConsensusParams(reverse_complement_second=False))
    assert ok["status"] == "ok" and ok["overlap"]["identity"] == 100.0
    with pytest.raises(ValueError):
        consensus(fwd, rev, ConsensusParams(mismatch=1))
    with pytest.raises(ValueError):
        consensus(fwd, replace(rev, bases="", qualities=[], peaks=[], origin=[]))


# --- Names --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title,species,genus,strain,subspecies", [
    ("Staphylococcus epidermidis strain Fussel 16S ribosomal RNA, partial sequence", "Staphylococcus epidermidis",
     "Staphylococcus", "Fussel", None),
    ("Staphylococcus capitis subsp. urealyticus strain MAW 8436 16S ribosomal RNA, partial sequence",
     "Staphylococcus capitis", "Staphylococcus", "MAW 8436", "urealyticus"),
    ("Bacillus amyloliquefaciens DSM 7 = ATCC 23350 16S ribosomal RNA, partial sequence",
     "Bacillus amyloliquefaciens", "Bacillus", None, None),
    ("Candidatus Pelagibacter ubique HTCC1062 16S ribosomal RNA, partial sequence", "Candidatus Pelagibacter ubique",
     "Candidatus Pelagibacter", None, None),
    ("Rhodococcus (subgen. Prescottella) equi strain DSM 20307 16S ribosomal RNA, partial sequence",
     "Rhodococcus equi", "Rhodococcus", "DSM 20307", None),
    ("[Clostridium] cellulosi strain AS 1.1777 16S ribosomal RNA, partial sequence", "[Clostridium] cellulosi",
     "[Clostridium]", "AS 1.1777", None),
])
def test_parse_16s_title(title, species, genus, strain, subspecies):
    p = parse_16s_title(title)
    assert (p["species"], p["genus"], p["strain"], p["subspecies"]) == (species, genus, strain, subspecies)


def test_parse_database_ids():
    assert ncbi_accession("gi|310975040|ref|NR_036904.1|") == "NR_036904.1"
    assert ncbi_accession("NC_003923.1") == "NC_003923.1"
    sid = "vfdb~~~hly/hla~~~WP_000857485~~~"
    v = parse_abricate_id(sid, sid + " (hly/hla) Alpha-Hemolysin precursor [Alpha-hemolysin (VF0001) - Exotoxin "
                          "(VFC0235)] [Staphylococcus aureus subsp. aureus MW2]")
    assert v == {"database": "vfdb", "gene": "hly/hla", "accession": "WP_000857485",
                 "product": "Alpha-Hemolysin precursor", "factor": "Alpha-hemolysin (VF0001)",
                 "category": "Exotoxin (VFC0235)", "organism": "Staphylococcus aureus subsp. aureus MW2"}
    assert sanger.gene_aliases(v["gene"]) == ["hly", "hla"]
    assert parse_abricate_id("vfdb~~~AAA92657~~~AAA92657~~~")["gene"] is None
    p = parse_abricate_id("plasmidfinder~~~Col(BS512)_1~~~NC_010656~~~",
                          "plasmidfinder~~~Col(BS512)_1~~~NC_010656~~~ Col(BS512)_1__NC_010656")
    assert (p["gene"], p["product"], p["organism"]) == ("Col(BS512)_1", "Col(BS512)_1__NC_010656", None)
    assert parse_abricate_id("NR_036904.1")["gene"] is None
    assert parse_mlst_allele("saureus.arcC_1") == {"scheme": "saureus", "locus": "arcC", "allele": "1"}
    assert parse_mlst_allele("arcC_822") == {"scheme": None, "locus": "arcC", "allele": "822"}
    assert parse_mlst_allele("abaumannii_2.Oxf_gltA_1") == {"scheme": "abaumannii_2", "locus": "Oxf_gltA", "allele": "1"}
    assert parse_mlst_allele("arcC") is None


# --- Hits and their reading -------------------------------------------------------------------------------------------

def hsp(sseqid, pident, length, qstart, qend, s_lo, s_hi, bitscore, qlen=600, slen=1500, strand="+", **extra):
    return {"qseqid": "q", "sseqid": sseqid, "pident": pident, "length": length, "nident": round(pident * length / 100),
            "qstart": qstart, "qend": qend, "s_lo": s_lo, "s_hi": s_hi, "sstrand": strand, "evalue": 0.0,
            "bitscore": bitscore, "qlen": qlen, "slen": slen, **extra}


def row(name, identity, coverage=100.0, bitscore=None, kind="species", subject=None, aligned=600, qs=1, qe=600,
        ss=1, se=600, **extra):
    r = {"source": {"kind": "ncbi_16s" if kind == "species" else "vfdb", "name": "db"}, "subject": subject or name,
         "identity": identity, "query_coverage": coverage, "subject_coverage": extra.pop("subject_coverage", 40.0),
         "aligned_length": aligned, "query_start": qs, "query_end": qe, "subject_start": ss, "subject_end": se,
         "bitscore": bitscore if bitscore is not None else identity * 10, "evalue": 0.0, "gene": None,
         "species": None, "genus": None}
    if kind == "species":
        r["species"], r["genus"] = name, name.split()[0]
    else:
        r["gene"] = name
    return {**r, **extra}


def test_hits_from_hsps_chains_split_hits_and_counts_copies():
    # The real hlb case (fixtures in tool-adapters): VFDB hlb in MW2 in two pieces 42,588 bp apart.
    hsps = [hsp("NC_003923.1", 99.636, 824, 170, 993, 2088807, 2089630, 1506, qlen=993, slen=2820462),
            hsp("NC_003923.1", 100.0, 183, 1, 183, 2046036, 2046218, 339, qlen=993, slen=2820462)]
    (r,) = hits_from_hsps(hsps, {"kind": "assembly", "name": "MW2"})
    assert r["kind"] == "split" and r["query_coverage"] == 100.0 and r["copies"] == 1 and len(r["pieces"]) == 2
    assert r["identity"] == 100 * (821 + 183) / (824 + 183) and r["bitscore"] == 1845.0
    assert (r["subject_start"], r["subject_end"]) == (2046036, 2089630) and r["source"]["name"] == "MW2"
    apart = hits_from_hsps(hsps, {"kind": "assembly"}, max_gap=5000)[0]
    assert apart["kind"] == "partial" and apart["copies"] == 2 and apart["query_coverage"] == 100 * 824 / 993
    bakta = [{"id": 1842, "contig": "NC_003923.1", "type": "cds", "start": 2046033, "end": 2046233, "strand": "+",
              "gene": None, "product": "Phospholipase C", "locus_tag": "P000011265_01842"},
             {"id": 1898, "contig": "NC_003923.1", "type": "cds", "start": 2088806, "end": 2089630, "strand": "+",
              "gene": None, "product": "Phospholipase C", "locus_tag": "P000011265_01898"},
             {"id": 1, "contig": "NC_003923.1", "type": "cds", "start": 1, "end": 1000, "strand": "+", "gene": "dnaA",
              "product": None, "locus_tag": "x"}]
    named = name_by_features(r, bakta)
    assert [(f["locus_tag"], f["feature_coverage"], f["hit_inside"]) for f in named] == [
        ("P000011265_01898", 99.88, 81.83), ("P000011265_01842", 91.04, 18.17)]


def test_hits_from_hsps_names_and_two_copies():
    hsps = [hsp("contig_1", 100.0, 600, 1, 600, 1001, 1600, 1100, slen=50_000, stitle="t1"),
            hsp("contig_1", 99.5, 600, 1, 600, 30001, 30600, 1090, slen=50_000, stitle="t1"),
            hsp("contig_2", 90.0, 300, 1, 300, 1, 300, 400, slen=300, strand="-")]
    rows = hits_from_hsps(hsps, {"kind": "assembly"}, lambda h: {"gene": "rrs" if h["sseqid"] == "contig_1" else None})
    by = {r["subject"]: r for r in rows}
    assert by["contig_1"]["copies"] == 2 and by["contig_1"]["identity"] == 100.0 and by["contig_1"]["gene"] == "rrs"
    assert by["contig_1"]["title"] == "t1" and by["contig_2"]["subject_coverage"] == 100.0
    assert by["contig_2"]["strand"] == "-" and by["contig_2"]["query_coverage"] == 50.0
    ranked = rank_hits(rows)
    assert [r["subject"] for r in ranked] == ["contig_1", "contig_2"] and ranked[0]["tied_with_best"]
    assert ranked[1]["rank"] == 2 and not ranked[1]["tied_with_best"]


def test_name_by_features_across_the_origin():
    r = {"subject": "c", "subject_length": 1000, "pieces": [{"s_lo": 1, "s_hi": 50}]}
    edge = {"id": 1, "contig": "c", "type": "cds", "start": 951, "end": 100, "edge": True, "gene": "x"}
    (f,) = name_by_features(r, [edge])
    assert f["length"] == 150 and f["feature_coverage"] == 33.33 and f["hit_inside"] == 100.0


def test_interpret_16s_levels():
    sp = interpret_16s([row("Staphylococcus aureus", 99.9), row("Staphylococcus argenteus", 99.0)])
    assert sp["level"] == "species" and sp["species"] == "Staphylococcus aureus" and sp["separation"] == pytest.approx(0.9)
    assert codes(sp["caveats"]) == ["criteria_quoted", "staphylococcus_16s_limit", "closest_type_strain"]
    assert sp["caveats"][1]["params"]["genes"] == ["rpoB", "sodA", "tuf", "gap"] and sp["thresholds"] == CLSI_16S
    g = interpret_16s([row("Staphylococcus taiwanensis", 100.0), row("Staphylococcus aureus", 99.83),
                       row("Staphylococcus argenteus", 99.83), row("Mammaliicoccus sciuri", 98.7)])
    assert g["level"] == "genus" and g["genus"] == "Staphylococcus" and g["species"] is None
    assert codes(g["reasons"]) == ["species_not_separated"]
    assert [x["species"] for x in g["within_separation"]] == ["Staphylococcus taiwanensis",
                                                               "Staphylococcus argenteus", "Staphylococcus aureus"]
    assert len(g["above_species_threshold"]) == 3 and g["next_species"]["species"] == "Staphylococcus argenteus"
    low = interpret_16s([row("Bacillus subtilis", 98.0), row("Bacillus velezensis", 97.9)])
    assert low["level"] == "genus" and codes(low["reasons"]) == ["below_species_identity"]
    mixed = interpret_16s([row("Escherichia coli", 100.0), row("Shigella flexneri", 99.9)])
    assert mixed["level"] == "inconclusive" and "genera_not_separated" in codes(mixed["reasons"])
    assert interpret_16s([row("Bacillus subtilis", 96.0)])["level"] == "inconclusive"
    assert interpret_16s([])["level"] == "no_hits"


def test_interpret_16s_coverage_length_and_region():
    short = interpret_16s([row("Staphylococcus aureus", 100.0, qs=1, qe=400, aligned=400)])
    assert short["level"] == "inconclusive" and codes(short["reasons"]) == ["short_alignment"]
    # A partial hit at higher identity does not outrank a full-length one.
    r = interpret_16s([row("Staphylococcus hominis", 100.0, coverage=60.0),
                       row("Staphylococcus aureus", 99.9, ss=790, se=1390)])
    assert r["level"] == "species" and r["species"] == "Staphylococcus aureus"
    assert "not_first_500" in codes(r["caveats"])
    only_partial = interpret_16s([row("Staphylococcus aureus", 100.0, coverage=60.0)])
    assert codes(only_partial["reasons"]) == ["low_query_coverage"]


def test_compare_suspected_genes():
    rows = [row("seh", 100.0, bitscore=1310, kind="gene", subject_coverage=100.0),
            row("selk", 91.43, coverage=4.82, bitscore=50.9, kind="gene", subject_coverage=4.8),
            row("hly/hla", 70.0, coverage=90.0, bitscore=40, kind="gene", subject_coverage=90.0)]
    m = compare_suspected(rows, "SEH", "gene")
    assert m["outcome"] == "match" and m["best_suspected"]["gene"] == "seh" and m["better_other"] == []
    n = compare_suspected(rows, "selk", "gene")
    assert n["outcome"] == "no_match" and codes(n["reasons"]) == ["better_hit_other_name"]
    assert n["better_other"][0]["gene"] == "seh" and n["better_other_count"] == 1
    assert compare_suspected(rows, "sea", "gene")["reasons"][0]["code"] == "not_found"
    hla = compare_suspected([rows[2]], "hla", "gene")
    assert hla["outcome"] == "no_match" and codes(hla["reasons"]) == ["below_thresholds"]
    assert hla["best_suspected"]["gene"] == "hly/hla"
    tie = compare_suspected([row("sea", 99.0, kind="gene", bitscore=900), row("sep", 99.0, kind="gene", bitscore=899)],
                            "sea", "gene")
    assert tie["outcome"] == "ambiguous" and tie["tied_other"][0]["gene"] == "sep"
    # A read inside a longer gene: low subject coverage, full query coverage, still a match.
    inside = compare_suspected([row("hlb", 99.5, coverage=100.0, kind="gene", subject_coverage=60.0)], "hlb", "gene")
    assert inside["outcome"] == "match"
    with pytest.raises(ValueError):
        compare_suspected(rows, " ", "gene")
    with pytest.raises(ValueError):
        compare_suspected(rows, "seh", "protein")


def test_compare_suspected_species_and_genus():
    rows = [row("Staphylococcus taiwanensis", 100.0), row("Staphylococcus aureus", 99.83),
            row("Staphylococcus argenteus", 99.83), row("Staphylococcus epidermidis", 99.0),
            row("Mammaliicoccus sciuri", 98.7), row("Bacillus cereus", 100.0, coverage=50.0)]
    a = compare_suspected(rows, "Staphylococcus aureus", "species")
    assert a["outcome"] == "ambiguous" and a["tied_other_count"] == 2 and a["better_other_count"] == 0
    assert {x["species"] for x in a["tied_other"]} == {"Staphylococcus taiwanensis", "Staphylococcus argenteus"}
    e = compare_suspected(rows, "Staphylococcus epidermidis", "species")
    assert e["outcome"] == "no_match" and codes(e["reasons"]) == ["better_hit_other_name"]
    # 1.0 and 0.83 points better: all three species above it are separated from it by the 0.8 % margin.
    assert e["better_other"][0]["species"] == "Staphylococcus taiwanensis" and e["better_other_count"] == 3
    g = compare_suspected(rows, "staphylococcus", "species")
    assert g["kind"] == "genus" and g["outcome"] == "match" and g["thresholds"]["min_identity"] == 97.0
    m = compare_suspected(rows, "Mammaliicoccus", "species")
    assert m["outcome"] == "no_match" and m["better_other"][0]["species"] == "Staphylococcus taiwanensis"
    b = compare_suspected(rows, "Bacillus cereus", "species")
    assert b["outcome"] == "no_match" and codes(b["reasons"]) == ["below_coverage"]
    clear = compare_suspected([row("Staphylococcus aureus", 99.9), row("Staphylococcus argenteus", 99.0)],
                              "Staphylococcus aureus", "species")
    assert clear["outcome"] == "match"


def test_thresholds_use_unrounded_identities():
    # 593 of 599 bases is 98.998 %: shown as 99.0 when rounded, but below the species threshold.
    near = interpret_16s([row("Staphylococcus aureus", 100 * 593 / 599)])
    assert near["level"] == "genus" and codes(near["reasons"]) == ["below_species_identity"]
    assert near["above_species_threshold"] == []
    # 100 % against 496/500 = 99.2 %: a separation of exactly 0.8 points (0.7999999999999972 in floating point).
    exact = interpret_16s([row("Staphylococcus aureus", 100.0), row("Staphylococcus argenteus", 100 * 496 / 500)])
    assert exact["level"] == "species" and exact["separation"] == pytest.approx(0.8)
    tie = compare_suspected([row("Staphylococcus aureus", 100.0), row("Staphylococcus argenteus", 100 * 496 / 500)],
                            "Staphylococcus argenteus", "species")
    assert tie["outcome"] == "no_match" and tie["better_other_count"] == 1


# --- Damaged and crafted chromatograms ------------------------------------------------------------------------------

def _with_shared_entries(data: bytes, extra: int, block: int) -> bytes:
    """3100.ab1 with `extra` added directory entries ('ZZZZ', element type 4, short) that all point at one block of
    `block` bytes appended to the file: the file grows by `block` bytes, the decoded tags by `extra` times that."""
    import struct

    head = struct.unpack(">H4sI2H3I", data[4:30])
    size, count, offset = head[4], head[5], head[7]
    directory = data[offset:offset + size * count]
    block_at = len(data)
    body = data + b"\x00\x01" * (block // 2)
    entries = b"".join(struct.pack(">4sI2H4I", b"ZZZZ", i + 1, 4, 2, block // 2, block, block_at, 0)
                       for i in range(extra))
    new_offset = len(body)
    out = bytearray(body + directory + entries)
    out[4:30] = struct.pack(">H4sI2H3I", head[0], head[1], head[2], head[3], size, count + extra,
                            size * (count + extra), new_offset)
    return bytes(out)


def test_check_abif_refuses_entries_that_share_data():
    data = (FX / "3100.ab1").read_bytes()
    sanger.check_abif(data)
    # One added entry with its own block is a well-formed file (Biopython reads it).
    one = _with_shared_entries(data, 1, 4096)
    sanger.check_abif(one)
    assert read_abi(one).bases == read_abi(data).bases
    crafted = _with_shared_entries(data, 60, 1 << 20)
    with pytest.raises(ValueError, match="more data than the file holds"):
        read_abi(crafted)
    with pytest.raises(ValueError, match="does not start"):
        sanger.check_abif(b"ABIF")


def test_read_abi_turns_biopython_assertions_into_value_errors():
    import struct

    data = bytearray((FX / "3100.ab1").read_bytes())
    head = struct.unpack(">H4sI2H3I", bytes(data[4:30]))
    size, count, offset = head[4], head[5], head[7]
    for i in range(count):
        at = offset + i * size
        if struct.unpack(">4sI", data[at:at + 8]) == (b"PBAS", 2):
            (dsize,) = struct.unpack(">I", data[at + 16:at + 20])
            data[at + 16:at + 20] = struct.pack(">I", dsize + 1)
    with pytest.raises(ValueError, match="AssertionError"):
        read_abi(bytes(data))


# --- Names a microbiologist writes ----------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["16S", "16S rRNA", "16s_rRNA", "16S ribosomal RNA", "rrs", "rrsA", "16S rDNA gene"])
def test_every_name_of_the_16s_gene_is_one_gene(name):
    assert sanger.gene_key(name) == "16s rrna"
    assert sanger.gene_key("hla") == "hla" and sanger.gene_key("16S_rRNA_methylase") != "16s rrna"


def test_16s_rows_are_the_16s_gene_without_a_gene_field():
    assert sanger.is_16s(row("Staphylococcus aureus", 100.0))
    assert sanger.is_16s({"source": {"source": "genomes"}, "gene": None, "product": "16S ribosomal RNA"})
    assert sanger.is_16s(row("streptomyces16S", 84.0, kind="gene", gene="16S"))
    assert not sanger.is_16s(row("tuf", 99.0, kind="gene"))


def test_suspected_16s_gene_matches_the_16s_hits_not_an_mlst_locus():
    rows = [row("Staphylococcus borealis", 100.0, bitscore=1105), row("Staphylococcus aureus", 99.83, bitscore=1100),
            row("bwashoensis.16S", 84.16, kind="gene", bitscore=575, gene="16S")]
    for written in ("16S rRNA", "16S", "rrs"):
        c = compare_suspected(rows, written, "gene")
        assert c["outcome"] == "match" and c["best_suspected"]["species"] == "Staphylococcus borealis", written
        assert c["best"]["subject"] == "Staphylococcus borealis"


def test_best_overall_is_over_every_row_and_unnamed_better_rows_are_listed():
    rows = [row("seh", 99.0, bitscore=900, kind="gene"),
            {**row("contig_1", 100.0, bitscore=1000, kind="gene"), "gene": None}]
    c = compare_suspected(rows, "seh", "gene")
    assert c["best"]["subject"] == "contig_1" and c["best_suspected"]["gene"] == "seh"
    # A better hit without a gene name (an unannotated genome) neither supports nor contradicts the suspicion.
    assert c["outcome"] == "match" and c["better_unnamed_count"] == 1 and c["better_other_count"] == 0


@pytest.mark.parametrize("written,outcome", [
    ("S. aureus", "ambiguous"), ("Staph. aureus", "ambiguous"), ("staphylococcus aureus", "ambiguous"),
    ("Staphylococcus aureus subsp. aureus", "ambiguous"), ("Staphylococcus aureus strain X", "ambiguous"),
    ("S.", "match"), ("Staphylococcus", "match"), ("Mammaliicoccus", "no_match"), ("E. coli", "no_match"),
])
def test_species_as_microbiologists_write_them(written, outcome):
    rows = [row("Staphylococcus borealis", 100.0), row("Staphylococcus aureus", 99.83),
            row("Staphylococcus argenteus", 99.83), row("Mammaliicoccus sciuri", 98.0)]
    c = compare_suspected(rows, written, "species")
    assert c["outcome"] == outcome, c
    if outcome == "ambiguous":
        assert c["matched_names"] == ["Staphylococcus aureus"]
    if written == "E. coli":
        assert codes(c["reasons"]) == ["not_found"]


def test_best_summary_counts_the_tie():
    ranked = sanger.rank_hits([row("Staphylococcus borealis", 100.0, bitscore=1105, subject="gi|1"),
                               row("Staphylococcus taiwanensis", 100.0, bitscore=1105, subject="gi|2"),
                               row("Staphylococcus aureus", 99.8, bitscore=1100, subject="gi|3")])
    b = sanger.best_summary(ranked)
    assert b["row"]["subject"] == "gi|1" and b["tied"] == 1 and b["tied_names"] == 2
    assert sanger.best_summary([]) is None
