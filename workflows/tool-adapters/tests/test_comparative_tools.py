"""Comparative genomics: skani triangle, FastANI all-vs-all, minimap2 assembly alignment, NUCmer/show-coords and
dnadiff's structural differences — options against the real usage texts, parsers on real outputs
(fixtures/comparative/README.md), and real runs on four NCBI Staphylococcus genomes.

The real runs need the genomes in ARVA_TEST_GENOMES (default /root/.arva-testdata/genomes, files <accession>.fna)
and skip without them or without the tool.
"""
import os
import shutil
from pathlib import Path

import pytest

from arva_tools import fastani, skani
from arva_tools.base import help_options
from arva_tools.dnadiff import DnadiffAdapter
from arva_tools.fastani import FastaniAdapter, FastaniParams
from arva_tools.mapping import Minimap2Adapter, parse_paf
from arva_tools.nucmer import (
    NucmerAdapter,
    NucmerParams,
    missing_help_flags,
    parse_coords,
    show_coords_path,
)
from arva_tools.registry import detect
from arva_tools.runner import run_command
from arva_tools.skani import SkaniAdapter, SkaniParams

FX = Path(__file__).parent / "fixtures" / "comparative"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
N315, MU50, USA300, SEPI = "GCF_000009645.1", "GCF_000009665.1", "GCF_000013465.1", "GCF_000007645.1"


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
        pytest.skip(f"test genome {p} is not cached (fixtures/comparative/README.md)")
    return p


def test_skani_triangle_options_and_parser():
    opts = help_options(text("skani_triangle_help_0.4.0.txt"))
    assert set(skani.TRIANGLE_FLAGS) <= opts and "--sparse" in opts
    argv = SkaniAdapter.triangle_argv("skani", SkaniParams(threads=2), Path("list.txt"), Path("out"), opts)
    assert argv == ["skani", "triangle", "-l", "list.txt", "-o", "out/skani_triangle.tsv", "-t", "2", "-c", "125",
                    "-m", "1000", "-s", "80", "--min-af", "15", "-E"]
    with pytest.raises(ValueError, match="does not offer -E"):
        SkaniAdapter.triangle_argv("skani", SkaniParams(), Path("l"), Path("o"), opts - {"-E"})
    rows = skani.parse_output(text("skani_triangle_staph.tsv"))
    assert [(r["reference"], r["query"], r["ani"]) for r in rows] == [
        ("in/mu50.fna", "in/n315.fna", 99.90), ("in/mu50.fna", "in/usa300.fna", 98.86),
        ("in/n315.fna", "in/usa300.fna", 98.97)]
    assert rows[0]["af_reference"] == pytest.approx(0.9596) and rows[0]["af_query"] == pytest.approx(0.9813)
    assert not any("sepi" in r["query"] or "sepi" in r["reference"] for r in rows)
    assert skani.LEARNED in text("skani_triangle_staph.log")


def test_fastani_all_vs_all_options_and_output():
    opts = fastani.help_options((FX.parent / "species" / "fastani_help_1.34.txt").read_text())
    argv = FastaniAdapter.all_vs_all_argv("fastANI", FastaniParams(threads=2), Path("list.txt"), Path("out"), opts)
    assert argv[:7] == ["fastANI", "--ql", "list.txt", "--rl", "list.txt", "-o", "out/fastani_all.tsv"]
    rows = fastani.parse_output(text("fastani_all_staph.tsv"))
    assert len(rows) == 16 and sum(r["query"] == r["reference"] and r["ani"] == 100 for r in rows) == 4
    pair = {(r["query"], r["reference"]): r["ani"] for r in rows}
    assert pair[("in/mu50.fna", "in/n315.fna")] == 99.9032 and pair[("in/n315.fna", "in/mu50.fna")] == 99.9143
    assert 79 < pair[("in/sepi.fna", "in/n315.fna")] < 80


def test_minimap2_assembly_argv_and_paf():
    usage = text("minimap2_help_2.26.txt")
    assert "asm5/asm10/asm20" in usage and "-c           output CIGAR in PAF" in usage
    assert Minimap2Adapter.assembly_argv("minimap2", "asm10", 4, Path("r.fna"), Path("q.fna"), Path("o.paf")) == [
        "minimap2", "-x", "asm10", "-c", "-t", "4", "-o", "o.paf", "r.fna", "q.fna"]
    with pytest.raises(ValueError, match="preset"):
        Minimap2Adapter.assembly_argv("minimap2", "map-ont", 4, Path("r"), Path("q"), Path("o"))
    rows = parse_paf(text("minimap2_asm5_n315_usa300.paf"))
    assert len(rows) == 175
    first = rows[0]
    assert (first["ref"], first["ref_start"], first["ref_end"]) == ("NC_002745.2", 1142826, 1313288)
    assert (first["query"], first["query_start"], first["query_end"], first["strand"]) == (
        "NC_007793.1", 1158586, 1328910, "+")
    assert first["identity"] == pytest.approx(100 * 169414 / 170540, abs=1e-3) and first["primary"]
    assert any(not r["primary"] for r in rows)
    sepi = parse_paf(text("minimap2_asm20_n315_sepi.paf"))
    assert len(sepi) == 120 and all(70 < r["identity"] <= 100 for r in sepi)
    for bad in ("a\t10\t0\t5\t+\tb\t10\t0\t5\t6\t5\t60", "a\t10\t0\t5\tx\tb\t10\t0\t5\t5\t5\t60", "a\tb"):
        with pytest.raises(ValueError):
            parse_paf(bad)


def test_nucmer_options_argv_and_coords():
    assert missing_help_flags(text("nucmer_help_3.1.txt")) == []
    assert "-r          Sort output lines by reference IDs" in text("show_coords_help_3.23.txt")
    argv = NucmerAdapter.argv("nucmer", NucmerParams(anchors="maxmatch"), "pair", "ref.fna", "qry.fna")
    assert argv == ["nucmer", "--maxmatch", "-b", "200", "-c", "65", "-g", "90", "-l", "20", "-p", "pair", "ref.fna",
                    "qry.fna"]
    for bad in ("x;rm", "../ref.fna", "a b"):
        with pytest.raises(ValueError, match="unsafe"):
            NucmerAdapter.argv("nucmer", NucmerParams(), "p", bad, "q.fna")
    with pytest.raises(ValueError, match="anchors"):
        NucmerParams(anchors="all").validate()
    rows = parse_coords(text("nucmer_n315_sepi.coords"))
    assert len(rows) == 268 and rows[0] == {
        "ref": "NC_002745.2", "ref_length": 2814816, "ref_start": 1983, "ref_end": 3302, "query": "NC_004461.1",
        "query_length": 2499279, "query_start": 1852, "query_end": 3170, "strand": "+", "identity": 85.49,
        "length": 1320, "primary": True}
    assert any(r["strand"] == "-" for r in rows)
    with pytest.raises(ValueError, match="13"):
        parse_coords("1\t2\t3")


def test_dnadiff_structural_differences_match_its_report():
    report = DnadiffAdapter.parse_report(text("dnadiff_n315_mu50.report"))
    r = DnadiffAdapter.parse_diff(text("dnadiff_n315_mu50.rdiff"))
    q = DnadiffAdapter.parse_diff(text("dnadiff_n315_mu50.qdiff"))
    for side, rows in (("reference", r), ("query", q)):
        counts = report[side]
        assert sum(x["category"] == "inversion" for x in rows) == counts["inversions"]
        assert sum(x["category"] == "relocation" for x in rows) == counts["relocations"]
        assert sum(x["category"] == "translocation" for x in rows) == counts["translocations"]
        assert sum(x["inserted"] > 0 for x in rows) == counts["inserted_regions"]
        assert sum(x["inserted"] for x in rows) == counts["inserted_region_bases"]
    gap = r[1]
    assert gap == {"sequence": "NC_002745.2", "type": "GAP", "start": 436046, "end": 436034, "length": -11,
                   "inserted": 0, "gap_other": 25790, "gap_difference": -25801, "category": None}
    with pytest.raises(ValueError):
        DnadiffAdapter.parse_diff("NC_1\tGAP\t1\t2\t3")
    with pytest.raises(ValueError):
        DnadiffAdapter.parse_diff("NC_1\tFOO\t1\t2\t3")


# --- Real runs on NCBI genomes ----------------------------------------------------------------------------------

def test_real_skani_triangle_and_minimap2(tmp_path):
    exe = tool("skani")
    paths = [genome(a) for a in (N315, MU50, USA300, SEPI)]
    (tmp_path / "list.txt").write_text("".join(f"{p}\n" for p in paths))
    opts = help_options(SkaniAdapter.triangle_help_text(exe))
    run_command(SkaniAdapter.triangle_argv(exe, SkaniParams(threads=2), tmp_path / "list.txt", tmp_path, opts),
                cwd=tmp_path, stderr_path=tmp_path / "skani.log")
    rows = skani.parse_output((tmp_path / skani.TRIANGLE_OUTPUT).read_text())
    assert len(rows) == 3 and all(98.5 < r["ani"] < 100 for r in rows)
    mm = tool("minimap2")
    run_command(Minimap2Adapter.assembly_argv(mm, "asm5", 2, paths[0], paths[0], tmp_path / "self.paf"),
                cwd=tmp_path, stderr_path=tmp_path / "mm.log")
    primary = [b for b in parse_paf((tmp_path / "self.paf").read_text()) if b["primary"]]
    chrom = [b for b in primary if b["ref"] == "NC_002745.2" and b["query"] == "NC_002745.2"]
    assert max(b["identity"] for b in chrom) == 100.0


def test_real_nucmer_and_dnadiff(tmp_path):
    exe = tool("nucmer")
    shutil.copy(genome(N315), tmp_path / "ref.fna")
    shutil.copy(genome(MU50), tmp_path / "qry.fna")
    run_command(NucmerAdapter.argv(exe, NucmerParams(), "pair", "ref.fna", "qry.fna"), cwd=tmp_path,
                stderr_path=tmp_path / "nucmer.log")
    sc = show_coords_path(exe)
    assert sc
    run_command(NucmerAdapter.coords_argv(sc, "pair.delta"), cwd=tmp_path, stderr_path=tmp_path / "sc.log",
                stdout_path=tmp_path / "pair.coords")
    rows = parse_coords((tmp_path / "pair.coords").read_text())
    weight = sum(r["length"] for r in rows)
    assert weight > 2_700_000 and sum(r["identity"] * r["length"] for r in rows) / weight > 99
    dd = tool("dnadiff")
    run_command(DnadiffAdapter.argv(dd, "dd", "ref.fna", "qry.fna"), cwd=tmp_path, stderr_path=tmp_path / "dd.log")
    report = DnadiffAdapter.parse_report((tmp_path / "dd.report").read_text())
    assert report["reference"]["inversions"] == len(
        [x for x in DnadiffAdapter.parse_diff((tmp_path / "dd.rdiff").read_text()) if x["category"] == "inversion"])
