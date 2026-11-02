import math

import pytest

from arva_core import newick, phylo


def _patristic(tree, a, b):
    nodes, adj, edges = phylo._graph(tree)
    idx = {n["name"]: i for i, n in enumerate(nodes) if n["leaf"]}
    dist, _ = phylo._distances_from(adj, edges, idx[a])
    return dist[idx[b]]


def test_slash_supports_round_trip():
    t = newick.parse("(A:1,B:1,(C:1,D:1)97.5/100:0.5);")
    inner = t["children"][2]
    assert inner["support"] == 97.5 and inner["supports"] == [97.5, 100]
    assert newick.write(t) == "(A:1,B:1,(C:1,D:1)97.5/100:0.5);"


def test_midpoint_root_on_the_longest_path():
    t = newick.parse("((A:1,B:1):1,(C:1,D:5):1);")
    rooted, info = phylo.midpoint_root(t)
    assert info["leaves"] == ["A", "D"] and info["path_length"] == 8
    sides = {frozenset(phylo.leaf_names(c)): c["length"] for c in rooted["children"]}
    assert sides == {frozenset("D"): 4, frozenset("ABC"): 1}
    for a, b in (("A", "D"), ("B", "C"), ("C", "D")):
        assert math.isclose(_patristic(rooted, a, b), _patristic(t, a, b))


def test_outgroup_root_keeps_supports_on_their_bipartitions():
    t = newick.parse("(A:1,B:1,(C:1,(D:1,E:1)90:2)80:1);")
    rooted, info = phylo.outgroup_root(t, ["E", "D"])
    assert info == {"method": "outgroup", "outgroup": ["D", "E"]}
    de = next(c for c in rooted["children"] if set(phylo.leaf_names(c)) == {"D", "E"})
    rest = next(c for c in rooted["children"] if c is not de)
    assert de["support"] == 90 and de["length"] == 1 and rest["length"] == 1
    ab = next(c for c in rest["children"] if c["children"])
    assert set(phylo.leaf_names(ab)) == {"A", "B"} and ab["support"] == 80
    assert phylo.splits(rooted) == phylo.splits(t)
    with pytest.raises(phylo.PhyloError, match="monophyletic"):
        phylo.outgroup_root(t, ["A", "D"])
    with pytest.raises(phylo.PhyloError):
        phylo.outgroup_root(t, ["Z"])


def test_unroot_merges_a_two_child_root():
    rooted, _ = phylo.midpoint_root(newick.parse("((A:1,B:1):1,(C:1,D:5):1);"))
    u = phylo.unroot(rooted)
    assert len(u["children"]) == 3 and phylo.splits(u) == {frozenset("CD")}


def test_robinson_foulds_matches_iqtree_on_a_known_pair():
    a = newick.parse("((A,B),(C,D),(E,F));")
    b = newick.parse("((A,C),(B,D),(E,F));")
    rf = phylo.robinson_foulds(a, b)
    assert rf["rf"] == 4 and rf["max"] == 6 and rf["shared"] == 1 and rf["normalized"] == pytest.approx(4 / 6)
    assert rf["only_a"] == [["C", "D"], ["C", "D", "E", "F"]] and rf["only_b"] == [["B", "D"], ["B", "D", "E", "F"]]
    rooted, _ = phylo.outgroup_root(newick.parse("((A:1,B:1):1,(C:1,D:1):1,(E:1,F:1):1);"), ["E", "F"])
    assert phylo.robinson_foulds(rooted, a)["rf"] == 0


def test_robinson_foulds_on_shared_leaves_only():
    a = newick.parse("((A,B),(C,D),(E,X));")
    b = newick.parse("((A,B),(C,E),(D,Y));")
    rf = phylo.robinson_foulds(a, b)
    assert rf["common_leaves"] == 5 and rf["only_in_a_leaves"] == ["X"] and rf["only_in_b_leaves"] == ["Y"]
    assert rf["splits_a"] == 2 and rf["splits_b"] == 2 and rf["rf"] == 2


def test_neighbour_joining_recovers_an_additive_tree():
    names = list("abcde")
    d = [[0, 5, 9, 9, 8], [5, 0, 10, 10, 9], [9, 10, 0, 8, 7], [9, 10, 8, 0, 3], [8, 9, 7, 3, 0]]
    tree, negative = phylo.neighbour_joining(names, d)
    assert negative == 0 and sorted(phylo.leaf_names(tree)) == names
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i < j:
                assert math.isclose(_patristic(tree, a, b), d[i][j])
    assert phylo.splits(tree) == {frozenset("cde"), frozenset("de")}


def test_neighbour_joining_rejects_bad_matrices():
    with pytest.raises(phylo.PhyloError):
        phylo.neighbour_joining(list("abc"), [[0, 1, 2], [1, 0, 3], [2, 4, 0]])
    with pytest.raises(phylo.PhyloError):
        phylo.neighbour_joining(list("ab"), [[0, 1], [1, 0]])


def test_alignment_stats_and_distances():
    recs = [("a", "ACGTACGTAA-N"), ("b", "ACGTTCGTAAAA"), ("c", "ACGAACGTCAAG"), ("d", "ACGTACGTCA-A")]
    st = phylo.alignment_stats(recs, chunk=5)
    assert (st["constant"], st["variable"], st["parsimony_informative"], st["no_base"]) == (8, 4, 1, 0)
    assert st["missing_fraction"][0] == pytest.approx(2 / 12)
    pd = phylo.pairwise_distances(recs, "p", chunk=5)
    assert pd["compared_sites"][0][1] == 10 and pd["distances"][0][1] == pytest.approx(1 / 10)
    jc = phylo.pairwise_distances(recs, "jc69")
    assert jc["distances"][0][1] == pytest.approx(-0.75 * math.log(1 - 4 / 30))
    with pytest.raises(phylo.PhyloError):
        phylo.alignment_stats([("a", "AC"), ("b", "A")])


def test_summary():
    s = phylo.summary(newick.parse("((A:1,B:2)90:1,C:3);"))
    assert s == {"leaves": 3, "internal_nodes": 2, "total_length": 7, "max_root_to_tip": 3, "bifurcating_root": True,
                 "support_min": 90, "support_max": 90}
