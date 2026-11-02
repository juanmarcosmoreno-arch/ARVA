"""Pangenome tools: Panaroo options against its real usage text, the parsers on real Panaroo 1.8.1 output and a real
run on three Bakta-annotated NCBI S. aureus genomes (fixtures/pangenome/README.md); the PPanGGOLiN adapter against
constructed files in its writers' formats (not validated).

The real run needs the GFF3 files in ARVA_TEST_GENOMES/bakta-1.12.2-light6 and skips without them or Panaroo.
"""
import os
from pathlib import Path

import pytest
from arva_core import pangenome as core

from arva_tools import pangenome as pg
from arva_tools.pangenome import PanarooAdapter, PanarooParams, PpanggolinAdapter, PpanggolinParams
from arva_tools.registry import detect
from arva_tools.runner import run_command

FX = Path(__file__).parent / "fixtures" / "pangenome"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes")) / "bakta-1.12.2-light6"


def test_every_panaroo_option_is_in_its_usage_text():
    help_text = (FX / "panaroo_help.txt").read_text()
    assert pg.missing_flags("panaroo", help_text) == []
    assert pg.missing_flags("panaroo", help_text.replace("--refind-mode", "--x")) == ["--refind-mode"]


def test_mode_settings_follow_panaroos_set_default_args():
    assert pg.mode_settings("strict", 5) == {"min_trailing_support": 2, "trailing_recursive": 99999999,
                                             "edge_support_threshold": 2.0, "remove_by_consensus": True,
                                             "min_edge_support_sv": 2}
    assert pg.mode_settings("strict", 100)["min_trailing_support"] == 5
    assert pg.mode_settings("moderate", 300)["min_trailing_support"] == 3
    assert pg.mode_settings("moderate", 300)["remove_by_consensus"] is False
    assert pg.mode_settings("sensitive", 300) == {"min_trailing_support": 2, "trailing_recursive": 0,
                                                  "edge_support_threshold": 0.0, "remove_by_consensus": False,
                                                  "min_edge_support_sv": 2}


def test_panaroo_argv_passes_every_result_changing_option():
    argv = PanarooAdapter.argv("panaroo", PanarooParams(threads=4), ["in/g1.gff3", "in/g2.gff3"], "out")
    assert argv[:6] == ["panaroo", "-i", "in/g1.gff3", "in/g2.gff3", "-o", "out"]
    for flag, value in (("--clean-mode", "strict"), ("-c", "0.98"), ("-f", "0.7"), ("--len_dif_percent", "0.98"),
                        ("--family_len_dif_percent", "0"), ("--length_outlier_support_proportion", "0.1"),
                        ("--remove_by_consensus", "True"), ("--edge_support_threshold", "2"),
                        ("--codon-table", "11"), ("-t", "4")):
        assert argv[argv.index(flag) + 1] == value
    assert "-a" not in argv and "--merge_paralogs" not in argv
    aligned = PanarooAdapter.argv("panaroo", PanarooParams(alignment="core", merge_paralogs=True),
                                  ["a.gff3", "b.gff3"], "o")
    assert aligned[-5:] == ["--merge_paralogs", "-a", "core", "--aligner", "mafft"]
    for bad in (PanarooParams(clean_mode="loose"), PanarooParams(identity=0.2), PanarooParams(alignment="all")):
        with pytest.raises(ValueError):
            PanarooAdapter.argv("panaroo", bad, ["a", "b"], "o")
    with pytest.raises(ValueError):
        PanarooAdapter.argv("panaroo", PanarooParams(), ["a"], "o")


def test_panaroo_outputs_parse():
    assert pg.parse_summary((FX / "summary_statistics.txt").read_text()) == {
        "core": 2310, "soft_core": 0, "shell": 780, "cloud": 0, "total": 3090}
    t = pg.parse_presence_csv((FX / "gene_presence_absence.csv").read_text())
    assert t["genomes"] == ["g1", "g2", "g3", "g4", "g5"]
    by_name = {f["family"]: f for f in t["families"]}
    assert by_name["lpl5~~~lpl1"]["gene_names"] == ["lpl5", "lpl1"]
    refound = next(f for f in t["families"] if any("pseudo" in m["flags"] for m in f["members"].values()))
    assert refound["members"]["g1"]["ids"][0].endswith("_refound_1")
    assert any(len(m["ids"]) == 2 for m in by_name["group_2430"]["members"].values())
    rows = list(pg.iter_gene_data(FX / "gene_data.csv"))
    assert len(rows) == 47
    ids = {r["annotation_id"] for _o, r in rows}
    assert all(i in ids for f in t["families"] for m in f["members"].values() for i in m["ids"])
    offset, first = rows[3]
    assert pg.read_gene_data_row(FX / "gene_data.csv", offset) == first
    assert pg.gene_position("0_0_1837") == (0, 1837) and pg.gene_position("0_refound_1") is None
    assert pg.refound_location("location:656641-656750;strand:+") == {"start": 656641, "end": 656750, "strand": "+"}
    with pytest.raises(ValueError):
        pg.parse_presence_csv("Gene,Annotation\n")


def test_ppanggolin_adapter_on_constructed_files():
    argv = PpanggolinAdapter.argv("ppanggolin", PpanggolinParams(threads=2), "anno.tsv", "out", "tmp")
    assert argv[:4] == ["ppanggolin", "workflow", "--anno", "anno.tsv"]
    assert argv[argv.index("--identity") + 1] == "0.8" and argv[argv.index("-K") + 1] == "-1"
    assert PpanggolinAdapter.info.tested_versions == ()
    d = FX / "ppanggolin_constructed"
    assert pg.parse_ppanggolin_matrix((d / "matrix.csv").read_text()) == {"famA": "persistent", "famB": "shell",
                                                                           "famC": "cloud"}
    fams = pg.parse_ppanggolin_families((d / "gene_families.tsv").read_text())
    assert [m["fragment"] for m in fams["famB"]] == [False, True, False]
    assert core.parse_rtab((d / "gene_presence_absence.Rtab").read_text())["presence"] == [[1, 1, 1], [1, 1, 0],
                                                                                         [0, 0, 1]]


def test_real_panaroo_on_three_genomes(tmp_path):
    d = detect("panaroo", refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"Panaroo is not available: {d.message}")
    accs = ("GCF_000009645.1", "GCF_000009665.1", "GCF_000011265.1")
    gffs = [GENOMES / a / f"{a}.gff3" for a in accs]
    if not all(p.is_file() for p in gffs):
        pytest.skip(f"Bakta GFF3 files are not cached in {GENOMES} (fixtures/pangenome/README.md)")
    assert d.version_validated
    assert pg.missing_flags("panaroo", PanarooAdapter.help_text(d.path)) == []
    (tmp_path / "input").mkdir()
    for n, p in enumerate(gffs, 1):
        os.symlink(p, tmp_path / "input" / f"g{n}.gff3")
    argv = PanarooAdapter.argv(d.path, PanarooParams(threads=4), [f"input/g{n}.gff3" for n in (1, 2, 3)], "out")
    run_command(argv, cwd=tmp_path, stderr_path=tmp_path / "panaroo.log", stdout_path=tmp_path / "panaroo.out",
                timeout_seconds=1800, extra_env=PanarooAdapter().environment(d.path))
    out = tmp_path / "out"
    rtab = core.parse_rtab((out / "gene_presence_absence.Rtab").read_text())
    assert rtab["genomes"] == ["g1", "g2", "g3"]
    s = core.summary(rtab["presence"], core.DEFAULT_THRESHOLDS)
    own = pg.parse_summary((out / "summary_statistics.txt").read_text())
    assert s["category_counts"] == {k: own[k] for k in core.CATEGORIES} and s["families"] == own["total"]
    assert 2200 < s["category_counts"]["core"] < 2700
    table = pg.parse_presence_csv((out / "gene_presence_absence.csv").read_text())
    assert [f["family"] for f in table["families"]] and {f["family"] for f in table["families"]} == \
        set(rtab["families"])
    ids = {r["annotation_id"] for _o, r in pg.iter_gene_data(out / "gene_data.csv")}
    assert all(i in ids for f in table["families"] for m in f["members"].values() for i in m["ids"])
