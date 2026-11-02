import pytest

from arva_core import newick, region


def hsp(q, s, qs, qe, ss, se, pident=99.0, qlen=300, slen=10_000, bits=None, sseqid="c1", qseqid="q"):
    length = qe - qs + 1
    return {"qseqid": qseqid, "sseqid": sseqid, "pident": pident, "length": length, "qstart": qs, "qend": qe,
            "sstart": ss, "send": se, "qlen": qlen, "slen": slen, "nident": round(length * pident / 100),
            "evalue": 1e-50, "bitscore": bits if bits is not None else float(length), "sstrand": "+" if ss <= se
            else "-", "s_lo": min(ss, se), "s_hi": max(ss, se), "mismatch": 0, "gapopen": 0, "q": q, "s": s}


def chain(hsps, **kw):
    args = {"min_identity": 80, "min_coverage": 30, "complete_coverage": 90, "max_gap": 5000, **kw}
    return region.chain_matches(hsps, **args)


def test_complete_partial_and_second_copy():
    m = chain([hsp(0, 0, 1, 300, 1001, 1300), hsp(0, 0, 1, 150, 5001, 5150, bits=100),
               hsp(0, 0, 1, 300, 9000, 8701, pident=85, bits=250)])
    assert [x["kind"] for x in m] == ["complete", "complete", "partial"]
    assert m[1]["strand"] == "-" and m[1]["start"] == 8701 and m[2]["query_coverage"] == 50.0
    assert [x["copy"] for x in m] == [1, 2, 3]


def test_split_match_across_an_insertion_on_both_strands():
    plus = chain([hsp(0, 0, 1, 140, 1001, 1140), hsp(0, 0, 141, 300, 2500, 2659)])
    assert len(plus) == 1 and plus[0]["kind"] == "split" and plus[0]["query_coverage"] == 100.0
    assert (plus[0]["start"], plus[0]["end"], len(plus[0]["pieces"])) == (1001, 2659, 2)
    minus = chain([hsp(0, 0, 1, 140, 3000, 2861), hsp(0, 0, 141, 300, 1500, 1341)])
    assert len(minus) == 1 and minus[0]["kind"] == "split" and minus[0]["strand"] == "-"


def test_not_chained_when_out_of_order_too_far_or_on_another_contig():
    assert len(chain([hsp(0, 0, 1, 140, 3000, 3139), hsp(0, 0, 141, 300, 1000, 1159)])) == 2
    assert len(chain([hsp(0, 0, 1, 140, 1001, 1140), hsp(0, 0, 141, 300, 9000, 9159)], max_gap=1000)) == 2
    assert len(chain([hsp(0, 0, 1, 140, 1001, 1140), hsp(0, 0, 141, 300, 1200, 1359, sseqid="c2")])) == 2


def test_redundant_overlapping_hsp_and_thresholds():
    m = chain([hsp(0, 0, 1, 300, 1001, 1300), hsp(0, 0, 50, 250, 1050, 1250, bits=50)])
    assert len(m) == 1 and len(m[0]["pieces"]) == 1
    assert region.redundant_hsps([hsp(0, 0, 1, 300, 1001, 1300), hsp(0, 0, 50, 250, 1050, 1250, bits=50)], m, 80) == 1
    assert chain([hsp(0, 0, 1, 300, 1001, 1300, pident=70)]) == []
    assert chain([hsp(0, 0, 1, 60, 1001, 1060)]) == []


def test_contig_edge_flag():
    assert chain([hsp(0, 0, 1, 150, 1, 150)])[0]["at_contig_edge"]
    assert chain([hsp(0, 0, 1, 300, 9701, 10000)])[0]["at_contig_edge"]
    assert not chain([hsp(0, 0, 1, 300, 5001, 5300)])[0]["at_contig_edge"]


def test_window_relative_coordinates_and_track_features():
    assert region.window(500, 900, 1000, 5000) == {"start": 1, "end": 1900, "clipped_left": True,
                                                   "clipped_right": False}
    assert region.to_relative(1000, 1100, 1000, 1500, False) == (0, 100)
    assert region.to_relative(1400, 1500, 1000, 1500, True) == (0, 100)
    feats = [{"id": 1, "contig": "c", "type": "cds", "start": 900, "end": 1600, "strand": "-"},
             {"id": 2, "contig": "c", "type": "cds", "start": 1700, "end": 2500, "strand": "+"},
             {"id": 3, "contig": "c", "type": "gap", "start": 1650, "end": 1660, "strand": "."},
             {"id": 4, "contig": "d", "type": "cds", "start": 1000, "end": 1100, "strand": "+"}]
    t = region.track_features(feats, "c", 1000, 2000, 1000, 1600, True)
    assert [f["id"] for f in t] == [2, 1]
    assert t[1]["rel_strand"] == "+" and (t[1]["rel_start"], t[1]["rel_end"]) == (0, 600) and t[1]["clipped"]
    assert (t[0]["rel_start"], t[0]["rel_end"], t[0]["rel_strand"]) == (-400, -100, "-")


def test_protein_hits_and_homology_groups():
    hs = [hsp(0, 0, 1, 280, 1, 290, pident=60, qlen=300, slen=300, qseqid="a", sseqid="b"),
          hsp(0, 0, 1, 100, 1, 100, pident=90, qlen=300, slen=100, qseqid="a", sseqid="c"),
          hsp(0, 0, 1, 300, 1, 300, pident=25, qlen=300, slen=300, qseqid="a", sseqid="d")]
    best = region.best_protein_hit(hs, 30, 50)
    assert [b["subject"] for b in best] == ["b"]
    groups = region.homology_groups(["a", "b", "c", "d", "e"], hs, 30, 50)
    assert groups["a"] == groups["b"] == 0 and len({groups["c"], groups["d"], groups["e"]}) == 3
    assert region.group_name([{"gene": "seh"}, {"gene": None, "product": "x"}, {"gene": "seh"}]) == "seh"
    assert region.group_name([{"product": "hypothetical protein"}, {"product": "IS1182 transposase"}]) == \
        "IS1182 transposase"


def test_links_follow_flips():
    upper = {"start": 1001, "anchor_start": 2001, "anchor_end": 2300, "flipped": False}
    lower = {"start": 5001, "anchor_start": 6001, "anchor_end": 6300, "flipped": True}
    h = hsp(0, 0, 1001, 1300, 1300, 1001, pident=98)
    (link,) = region.links([h], upper, lower, 70, 100)
    assert (link["upper_start"], link["upper_end"]) == (0, 299) and not link["inverted"]
    assert (link["lower_start"], link["lower_end"]) == (0, 299)
    assert region.links([h], upper, lower, 99, 100) == []


def test_newick_round_trip_supports_and_renaming():
    t = newick.parse("(s1:0.1,(s2:0.2,'s 3':0.3)95:0.05,s4:0.4);")
    assert newick.leaves(t) == ["s1", "s2", "s 3", "s4"] and t["children"][1]["support"] == 95
    r = newick.rename(t, {"s1": "MW2 seh", "s2": "b", "s 3": "it's", "s4": "d"})
    text = newick.write(r)
    assert text == "('MW2 seh':0.1,(b:0.2,'it''s':0.3)95:0.05,d:0.4);"
    assert newick.leaves(newick.parse(text)) == ["MW2 seh", "b", "it's", "d"]
    with pytest.raises(newick.NewickError):
        newick.rename(t, {"s1": "x"})
    for bad in ("(a,b)", "(a,b;", "(a,b));", "(a:x,b);", "('a,b);"):
        with pytest.raises(newick.NewickError):
            newick.parse(bad)
