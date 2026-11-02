import copy

import pytest

from arva_core import workflow as wf


def _def(nodes, edges):
    return {"format": wf.FORMAT, "format_version": wf.FORMAT_VERSION,
            "nodes": [{"id": i, "kind": k, "params": p} for i, k, p in nodes],
            "edges": [{"id": f"e{n}", "source": s, "source_port": sp, "target": t, "target_port": tp}
                      for n, (s, sp, t, tp) in enumerate(edges)]}


def codes(d):
    return sorted(p["code"] for p in wf.validate(d))


def test_every_template_is_a_valid_graph():
    for key, d in wf.TEMPLATES.items():
        assert wf.validate(d) == [], key
        assert all(n["position"]["x"] >= 40 for n in d["nodes"])


def test_incompatible_types_are_refused():
    d = _def([("r", "reads_short_input", {}), ("f", "flye", {})], [("r", "reads", "f", "reads")])
    assert codes(d) == ["wf_edge_type", "wf_input_missing"]
    p = wf.edge_problem({n["id"]: n for n in d["nodes"]}, d["edges"][0])
    assert p["params"] == {"port": "reads", "given": "reads_short", "expected": "reads_long"}


def test_scope_rules():
    sample_to_set = _def([("a", "assembly_input", {}), ("ani", "comparative_ani", {"method": "skani"})],
                         [("a", "assembly", "ani", "set")])
    assert "wf_edge_type" in codes(sample_to_set)
    into_plain_port = _def([("a", "assembly_input", {}), ("s", "comparison_set", {}),
                            ("x", "comparison_set_input", {}), ("q", "quast", {})],
                           [("a", "assembly", "s", "genomes"), ("x", "set", "s", "genomes")])
    assert codes(into_plain_port) == ["wf_edge_type", "wf_input_missing"]
    ok = _def([("a", "assembly_input", {}), ("n", "annotation_input", {}), ("s", "comparison_set", {})],
              [("a", "assembly", "s", "genomes"), ("n", "annotation", "s", "genomes")])
    assert codes(ok) == []


def test_set_output_never_feeds_a_sample_node():
    d = _def([("x", "comparison_set_input", {}), ("p", "pangenome", {"method": "panaroo"}),
              ("t", "phylogeny", {"source_kind": "core_alignment"}), ("q", "quast", {})],
             [("x", "set", "p", "set"), ("p", "core_alignment", "t", "alignment")])
    assert codes(d) == ["wf_input_missing"]


def test_single_input_ports_take_one_edge_and_required_ports_need_one():
    d = _def([("a", "assembly_input", {}), ("b", "assembly_input", {}), ("q", "quast", {})],
             [("a", "assembly", "q", "assembly"), ("b", "assembly", "q", "assembly")])
    assert codes(d) == ["wf_input_many"]
    optional = _def([("s", "reads_short_input", {}), ("u", "unicycler", {})], [("s", "reads", "u", "short_reads")])
    assert codes(optional) == []


def test_cycles_and_bad_definitions():
    d = _def([("p", "polishing", {"strategy": "racon"}), ("q", "polishing", {"strategy": "racon"})],
             [("p", "assembly", "q", "assembly"), ("q", "assembly", "p", "assembly")])
    assert "wf_cycle" in codes(d)
    with pytest.raises(ValueError):
        wf.topological_order(d)
    assert codes({"format": "x"}) == ["wf_format"]
    assert codes(_def([], [])) == ["wf_empty"]
    assert codes(_def([("a", "nope", {})], [])) == ["wf_node_kind"]
    assert codes(_def([("a", "quast", {}), ("a", "quast", {})], [])) == ["wf_node_duplicate"]


def test_phylogeny_source_kind_must_suit_its_upstream():
    d = _def([("x", "comparison_set_input", {}), ("g", "gene_investigation", {}),
              ("t", "phylogeny", {"source_kind": "core_alignment"})],
             [("x", "set", "g", "set"), ("g", "alignment", "t", "alignment")])
    assert codes(d) == ["wf_phylo_source"]
    d["nodes"][2]["params"]["source_kind"] = "gene_alignment"
    assert codes(d) == []


def test_topological_order_and_descendants():
    d = wf.TEMPLATES["illumina_assembly"]
    assert wf.topological_order(d) == ["short", "fastp", "spades", "quast"]
    assert wf.descendants(d, ["fastp"]) == {"fastp", "spades", "quast"}


def test_tools_follow_the_method_parameter():
    assert wf.NODES["species"].tool_ids({"method": "fastani"}) == ("fastani",)
    assert wf.NODES["polishing"].tool_ids({"strategy": "pilon"}) == ("pilon", "bwa", "samtools")
    assert wf.NODES["phylogeny"].tool_ids({"method": "nj"}) == ()
    assert wf.NODES["comparison_set"].tool_ids({}) == ()
    assert wf.tools_of(wf.TEMPLATES["virulence_screening"]) == {"asm": (), "vir": ("abricate",)}


def test_checksum_ignores_layout_and_order():
    d = copy.deepcopy(wf.TEMPLATES["illumina_assembly"])
    other = copy.deepcopy(d)
    other["nodes"].reverse()
    other["nodes"][0]["position"] = {"x": 999, "y": 1}
    assert wf.checksum(d) == wf.checksum(other)
    other["nodes"][0]["params"] = {"min_contig": 1000}
    assert wf.checksum(d) != wf.checksum(other)


def test_reusable_nodes_stop_at_the_first_change():
    before = wf.TEMPLATES["illumina_assembly"]
    after = wf.with_params(before, "spades", {"params": {"careful": True}})
    assert wf.reusable_nodes(before, after) == {"short": "short", "fastp": "fastp"}
    assert wf.reusable_nodes(before, before) == {n: n for n in ("short", "fastp", "spades", "quast")}


def test_param_diff():
    assert wf.param_diff({"a": 1, "b": {"c": 2, "d": 3}}, {"a": 1, "b": {"c": 5}}) == [
        {"path": "b.c", "before": 2, "after": 5}, {"path": "b.d", "before": 3, "after": None}]
