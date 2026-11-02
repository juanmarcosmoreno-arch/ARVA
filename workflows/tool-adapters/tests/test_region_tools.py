"""Region Explorer and Custom Gene Investigation tools: BLAST+ (makeblastdb, blastn, tblastn, blastp), MAFFT, IQ-TREE
and FastTree — options against the real usage texts, the tabular parser on real outputs (fixtures/region/README.md)
and real runs: the staphylococcal enterotoxin H gene (seh) searched in NCBI S. aureus genomes, its hits aligned and
a gene tree built.

The real runs need the genomes in ARVA_TEST_GENOMES (default /root/.arva-testdata/genomes) and skip without them or
without the tool.
"""
import os
from pathlib import Path

import pytest
from arva_core import newick, region

from arva_tools import blast
from arva_tools.blast import BlastAdapter, BlastParams, parse_tabular, sibling
from arva_tools.mafft import MafftAdapter
from arva_tools.phylo import FasttreeAdapter, IqtreeAdapter, TreeParams, missing_flags
from arva_tools.registry import detect
from arva_tools.runner import run_command

FX = Path(__file__).parent / "fixtures" / "region"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
MW2, MSSA476, N315, USA300 = "GCF_000011265.1", "GCF_000011525.1", "GCF_000009645.1", "GCF_000013465.1"
SEH = FX / "seh_WP_000608674.1.faa"


def text(name: str) -> str:
    return (FX / name).read_text()


def tool(tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"{tool_id} is not available: {d.message}")
    return d.path


def genome(acc: str) -> Path:
    p = GENOMES / f"{acc}.fna"
    if not p.is_file():
        pytest.skip(f"test genome {p} is not cached (fixtures/region/README.md)")
    return p


def test_blast_options_in_the_usage_texts():
    for program in ("blastn", "tblastn", "blastp"):
        assert blast.missing_flags(program, text(f"{program}_help_2.12.0.txt")) == []
        for field in blast.FIELDS:
            assert f" {field} means " in text(f"{program}_help_2.12.0.txt")
    assert blast.missing_flags("makeblastdb", text("makeblastdb_help_2.12.0.txt")) == []
    assert "Default = `megablast'" in text("blastn_help_2.12.0.txt")
    assert "-db_gencode <Integer" in text("tblastn_help_2.12.0.txt")


def test_blast_argv():
    p = BlastParams(program="tblastn", task="tblastn", evalue=1e-5, threads=2)
    assert BlastAdapter.search_argv("tblastn", p, "q.faa", "out.tsv", db="db/g1") == [
        "tblastn", "-task", "tblastn", "-query", "q.faa", "-db", "db/g1", "-out", "out.tsv", "-outfmt", blast.OUTFMT,
        "-evalue", "1e-05", "-max_target_seqs", "500", "-seg", "yes", "-comp_based_stats", "2", "-db_gencode", "11",
        "-num_threads", "2"]
    n = BlastAdapter.search_argv("blastn", BlastParams(low_complexity_filter=False), "a", "o", subject="b")
    assert n[n.index("-dust") + 1] == "no" and "-strand" in n and "-num_threads" not in n
    with pytest.raises(ValueError, match="task must be"):
        BlastAdapter.search_argv("blastp", BlastParams(program="blastp", task="megablast"), "a", "o", db="d")
    with pytest.raises(ValueError, match="not both"):
        BlastAdapter.search_argv("blastn", BlastParams(), "a", "o", db="d", subject="s")
    assert BlastAdapter.makeblastdb_argv("makeblastdb", "g.fna", "nucl", "db/g") == [
        "makeblastdb", "-in", "g.fna", "-dbtype", "nucl", "-out", "db/g"]


def test_parse_real_tblastn_and_blastn_rows():
    rows = parse_tabular(text("tblastn_seh_mw2_n315.tsv"))
    assert len(rows) == 23 and rows[0]["pident"] == 100.0 and rows[0]["sstrand"] == "+"
    minus = rows[1]
    assert minus["sstart"] > minus["send"] and minus["sstrand"] == "-" and minus["s_lo"] == minus["send"]
    mw2 = [r for r in rows if r["sseqid"] == "NC_003923.1"]
    matches = region.chain_matches(mw2, min_identity=70, min_coverage=50, complete_coverage=90, max_gap=5000)
    assert len(matches) == 1 and matches[0]["kind"] == "complete" and (matches[0]["start"], matches[0]["end"]) == (
        61524, 62246)
    n315 = [r for r in rows if r["sseqid"] == "NC_002745.2"]
    assert region.chain_matches(n315, min_identity=70, min_coverage=50, complete_coverage=90, max_gap=5000) == []
    loose = region.chain_matches(mw2, min_identity=30, min_coverage=50, complete_coverage=90, max_gap=5000)
    assert any(m["kind"] == "split" and m["start"] == 62566 for m in loose)
    (nt,) = parse_tabular(text("blastn_seh_mw2_n315.tsv"))
    assert nt["qlen"] == 726 and nt["nident"] == 726
    with pytest.raises(ValueError, match="columns"):
        parse_tabular("a\tb\n")
    with pytest.raises(ValueError, match="out of range"):
        parse_tabular("q\ts\t100\t10\t0\t0\t5\t20\t1\t10\t1e-5\t20\t10\t100\t10\n")


def test_mafft_and_tree_options():
    assert MafftAdapter.missing_flags(text("mafft_help_7.505.txt")) == []
    assert MafftAdapter.argv("mafft", "linsi", "nucleotide", 2, "in.fna") == [
        "mafft", "--nuc", "--localpair", "--maxiterate", "1000", "--thread", "2", "in.fna"]
    with pytest.raises(ValueError):
        MafftAdapter.argv("mafft", "auto", "nucleotide", 2, "in.fna")
    assert missing_flags("iqtree", text("iqtree_help_3.0.1.txt")) == []
    assert missing_flags("fasttree", text("fasttree_help_2.1.11.txt")) == []
    p = TreeParams(threads=2)
    assert IqtreeAdapter.argv("iqtree3", p, "nucleotide", "aln.fna", "tree/gene") == [
        "iqtree3", "-s", "aln.fna", "--seqtype", "DNA", "-m", "MFP", "-B", "1000", "-T", "2", "--seed", "12345",
        "--prefix", "tree/gene"]
    assert FasttreeAdapter.argv("FastTree", TreeParams(method="fasttree"), "protein", "a", "t.nwk") == [
        "FastTree", "-lg", "-gamma", "-boot", "1000", "-seed", "12345", "-out", "t.nwk", "a"]
    for bad in (TreeParams(ufboot=100), TreeParams(model="GTR;rm -rf"), TreeParams(method="raxml")):
        with pytest.raises(ValueError):
            bad.validate()


# --- Real runs on NCBI genomes ----------------------------------------------------------------------------------

def test_real_tblastn_finds_seh_only_in_mw2_and_mssa476(tmp_path):
    exe = tool("blast")
    mk, tbn = sibling(exe, "makeblastdb"), sibling(exe, "tblastn")
    found = {}
    for acc in (MW2, MSSA476, N315, USA300):
        run_command(BlastAdapter.makeblastdb_argv(mk, str(genome(acc)), "nucl", f"db_{acc}"), cwd=tmp_path,
                    stderr_path=tmp_path / "mk.log")
        out = tmp_path / f"{acc}.tsv"
        run_command(BlastAdapter.search_argv(tbn, BlastParams(program="tblastn", task="tblastn", evalue=1e-5,
                                                              threads=2), str(SEH), out.name, db=f"db_{acc}"),
                    cwd=tmp_path, stderr_path=tmp_path / "tbn.log")
        found[acc] = region.chain_matches(parse_tabular(out.read_text()), min_identity=70, min_coverage=50,
                                          complete_coverage=90, max_gap=5000)
    assert [len(found[a]) for a in (MW2, MSSA476, N315, USA300)] == [1, 1, 0, 0]
    assert found[MW2][0]["identity"] == 100.0 and found[MSSA476][0]["start"] == 60231


def test_real_mafft_fasttree_iqtree(tmp_path):
    seqs = {}
    for acc in (MW2, MSSA476):
        if not (GENOMES / "ncbi-annotation" / f"{acc}.faa").is_file():
            pytest.skip("NCBI protein FASTA not cached (fixtures/region/README.md)")
    wanted = {"WP_000608674.1", "WP_001033320.1", "WP_000733771.1", "WP_000041898.1"}
    name = None
    for line in (GENOMES / "ncbi-annotation" / f"{MW2}.faa").read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0] if line[1:].split()[0] in wanted else None
        elif name:
            seqs[name] = seqs.get(name, "") + line.strip()
    assert set(seqs) == wanted
    (tmp_path / "in.faa").write_text("".join(f">s{i}\n{s}\n" for i, s in enumerate(seqs.values(), 1)))
    mafft = tool("mafft")
    assert MafftAdapter.missing_flags(MafftAdapter.help_text(mafft)) == []
    run_command(MafftAdapter.argv(mafft, "linsi", "protein", 2, "in.faa"), cwd=tmp_path,
                stderr_path=tmp_path / "mafft.log", stdout_path=tmp_path / "aln.faa")
    aln = (tmp_path / "aln.faa").read_text().split(">")[1:]
    assert len(aln) == 4 and len({len("".join(a.splitlines()[1:])) for a in aln}) == 1
    ft = tool("fasttree")
    run_command(FasttreeAdapter.argv(ft, TreeParams(method="fasttree"), "protein", "aln.faa", "ft.nwk"),
                cwd=tmp_path, stderr_path=tmp_path / "ft.log")
    assert sorted(newick.leaves(newick.parse((tmp_path / "ft.nwk").read_text()))) == ["s1", "s2", "s3", "s4"]
    iq = tool("iqtree")
    run_command(IqtreeAdapter.argv(iq, TreeParams(threads=1), "protein", "aln.faa", "iq"), cwd=tmp_path,
                stderr_path=tmp_path / "iq.log")
    tree = newick.parse((tmp_path / "iq.treefile").read_text())
    assert sorted(newick.leaves(tree)) == ["s1", "s2", "s3", "s4"]
    assert "Best-fit model according to BIC:" in (tmp_path / "iq.iqtree").read_text()
