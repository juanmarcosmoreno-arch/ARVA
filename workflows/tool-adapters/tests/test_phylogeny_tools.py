"""Phylogeny tools: SNP-sites, IQ-TREE (SH-aLRT, -fconst, +ASC, report parser, -rf) — options against the real usage
texts, parsers on real outputs (fixtures/phylogeny/README.md) and real runs on Panaroo's core-genome alignment of
five NCBI S. aureus genomes, cached in ARVA_TEST_GENOMES/panaroo-1.8.1-core (the real runs skip without it).
"""
import os
from pathlib import Path

import pytest
from arva_core import newick, phylo

from arva_tools.phylo import (
    FasttreeAdapter,
    IqtreeAdapter,
    TreeParams,
    missing_flags,
    parse_iqtree_report,
)
from arva_tools.registry import ADAPTERS, detect
from arva_tools.runner import run_command
from arva_tools.snpsites import SnpsitesAdapter, parse_constant_counts

FX = Path(__file__).parent / "fixtures" / "phylogeny"
REGION = Path(__file__).parent / "fixtures" / "region"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
CORE = GENOMES / "panaroo-1.8.1-core" / "out" / "core_gene_alignment.aln"
CORE_SHA256 = "96ce6f2b2d70458dfbb541fe512548c7f03e8f21174e1eac411168fd20ad2904"


def tool(tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"{tool_id} is not available: {d.message}")
    return d.path


def core_alignment() -> Path:
    if not CORE.is_file():
        pytest.skip("Panaroo's core alignment is not cached (fixtures/phylogeny/README.md)")
    return CORE


def read_fasta(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for block in path.read_text().split(">")[1:]:
        lines = block.splitlines()
        out.append((lines[0].split()[0], "".join(lines[1:])))
    return out


def test_snp_sites_options_and_counts():
    usage = (FX / "snp_sites_usage_2.5.1.txt").read_text()
    assert SnpsitesAdapter.missing_flags(usage) == []
    assert SnpsitesAdapter.missing_flags(usage.replace(" -C ", " -X ")) == ["-C"]
    assert SnpsitesAdapter.snp_argv("snp-sites", "a.fa", "snp.fa", True) == ["snp-sites", "-m", "-c", "-o", "snp.fa",
                                                                             "a.fa"]
    assert SnpsitesAdapter.constant_argv("snp-sites", "a.fa", "c.txt") == ["snp-sites", "-C", "-o", "c.txt", "a.fa"]
    assert parse_constant_counts((FX / "core_constant_counts.txt").read_text()) == (775527, 315491, 409032, 655216)
    with pytest.raises(ValueError):
        parse_constant_counts("1,2,3\n")
    assert "snp-sites" in ADAPTERS


def test_iqtree_support_and_constant_site_options():
    help_text = (REGION / "iqtree_help_3.0.1.txt").read_text()
    assert missing_flags("iqtree", help_text) == []
    p = TreeParams(alrt=1000, threads=2)
    assert IqtreeAdapter.argv("iqtree3", p, "nucleotide", "snp.fa", "tree", fconst=(1, 2, 3, 4)) == [
        "iqtree3", "-s", "snp.fa", "--seqtype", "DNA", "-m", "MFP", "-B", "1000", "--alrt", "1000", "-fconst",
        "1,2,3,4", "-T", "2", "--seed", "12345", "--prefix", "tree"]
    assert IqtreeAdapter.argv("iqtree3", TreeParams(ufboot=0, alrt=1000), "nucleotide", "a", "t")[6:10] == [
        "MFP", "--alrt", "1000", "-T"]
    with pytest.raises(ValueError):
        IqtreeAdapter.argv("iqtree3", TreeParams(model="GTR+F+ASC+G4"), "nucleotide", "a", "t", fconst=(1, 2, 3, 4))
    with pytest.raises(ValueError):
        TreeParams(alrt=10).validate()
    assert TreeParams(method="fasttree", alrt=1000).as_dict() == {"method": "fasttree", "seed": 12345, "threads": 1}


def test_iqtree_reports_and_slash_supports():
    core = parse_iqtree_report((FX / "core_mfp_ufboot_alrt.iqtree").read_text())
    assert core == {"model": "TIM2+F+I", "log_likelihood": -3134049.2427, "sequences": 5, "sites": 2186160,
                    "constant_sites": 2155270, "informative_sites": 19889, "distinct_patterns": 493}
    asc = parse_iqtree_report((FX / "snp_asc_gtr.iqtree").read_text())
    assert asc["model"] == "GTR+F+ASC+G4" and asc["sites"] == 29328 and asc["constant_sites"] == 0
    tree = newick.parse((FX / "core_mfp_ufboot_alrt.treefile").read_text())
    assert sorted(newick.leaves(tree)) == ["g1", "g2", "g3", "g4", "g5"]
    assert phylo.splits(tree) == {frozenset({"g4", "g5"}), frozenset({"g3", "g4", "g5"})}
    inner = tree["children"][1]
    assert inner["supports"] == [100, 100]
    assert "ModelFactory::initFromNestedModel" in (FX / "mfp_asc_abort_3.0.1.txt").read_text()


# --- Real runs on Panaroo's core alignment ----------------------------------------------------------------------

def test_real_snp_sites_on_the_core_alignment(tmp_path):
    exe = tool("snp-sites")
    aln = core_alignment()
    assert SnpsitesAdapter.missing_flags(SnpsitesAdapter.help_text(exe)) == []
    run_command(SnpsitesAdapter.snp_argv(exe, str(aln), "snp.fa", False), cwd=tmp_path,
                stderr_path=tmp_path / "log")
    run_command(SnpsitesAdapter.snp_argv(exe, str(aln), "acgt.fa", True), cwd=tmp_path, stderr_path=tmp_path / "log")
    run_command(SnpsitesAdapter.constant_argv(exe, str(aln), "c.txt"), cwd=tmp_path, stderr_path=tmp_path / "log")
    snp, acgt = read_fasta(tmp_path / "snp.fa"), read_fasta(tmp_path / "acgt.fa")
    assert {len(s) for _, s in snp} == {30888} and {len(s) for _, s in acgt} == {29328}
    counts = parse_constant_counts((tmp_path / "c.txt").read_text())
    assert counts == (775527, 315491, 409032, 655216)
    stats = phylo.alignment_stats(read_fasta(aln))
    assert stats["columns"] == 2186160 and stats["variable"] == 30888 and stats["constant"] == sum(counts)


def test_real_iqtree_fconst_asc_and_rf(tmp_path):
    iq, snp_sites = tool("iqtree"), tool("snp-sites")
    aln = core_alignment()
    run_command(SnpsitesAdapter.snp_argv(snp_sites, str(aln), "snp.fa", False), cwd=tmp_path,
                stderr_path=tmp_path / "log")
    run_command(SnpsitesAdapter.snp_argv(snp_sites, str(aln), "acgt.fa", True), cwd=tmp_path,
                stderr_path=tmp_path / "log")
    p = TreeParams(alrt=1000, threads=2)
    run_command(IqtreeAdapter.argv(iq, p, "nucleotide", "snp.fa", "fc", fconst=(775527, 315491, 409032, 655216)),
                cwd=tmp_path, stderr_path=tmp_path / "fc.out")
    rep = parse_iqtree_report((tmp_path / "fc.iqtree").read_text())
    assert rep["sites"] == 2186154 and rep["model"]
    fc = newick.parse((tmp_path / "fc.treefile").read_text())
    expected = newick.parse((FX / "core_mfp_ufboot_alrt.treefile").read_text())
    assert phylo.robinson_foulds(fc, expected)["rf"] == 0
    run_command(IqtreeAdapter.argv(iq, TreeParams(model="GTR+F+ASC+G4", alrt=1000, threads=2), "nucleotide",
                                   "acgt.fa", "asc"), cwd=tmp_path, stderr_path=tmp_path / "asc.out")
    assert parse_iqtree_report((tmp_path / "asc.iqtree").read_text())["model"] == "GTR+F+ASC+G4"
    other = "((g1:1,g4:1):1,(g3:1,g2:1):1,g5:1);"
    (tmp_path / "other.nwk").write_text(other + "\n")
    run_command(IqtreeAdapter.rf_argv(iq, "fc.treefile", "other.nwk", "rf"), cwd=tmp_path,
                stderr_path=tmp_path / "rf.out")
    iq_rf = int((tmp_path / "rf.rfdist").read_text().split()[-1])
    assert iq_rf == phylo.robinson_foulds(fc, newick.parse(other))["rf"] == 4


def test_real_fasttree_and_nj_agree_with_the_ml_topology(tmp_path):
    ft, snp_sites = tool("fasttree"), tool("snp-sites")
    aln = core_alignment()
    run_command(SnpsitesAdapter.snp_argv(snp_sites, str(aln), "snp.fa", True), cwd=tmp_path,
                stderr_path=tmp_path / "log")
    run_command(FasttreeAdapter.argv(ft, TreeParams(method="fasttree"), "nucleotide", "snp.fa", "ft.nwk"),
                cwd=tmp_path, stderr_path=tmp_path / "ft.log")
    expected = newick.parse((FX / "core_mfp_ufboot_alrt.treefile").read_text())
    assert phylo.robinson_foulds(newick.parse((tmp_path / "ft.nwk").read_text()), expected)["rf"] == 0
    records = read_fasta(aln)
    d = phylo.pairwise_distances(records, "jc69")
    nj, negative = phylo.neighbour_joining([n for n, _ in records], d["distances"])
    assert negative == 0 and phylo.robinson_foulds(nj, expected)["rf"] == 0
