"""Plasmid, mobile-element and VFDB adapters: options against the real --help, commands, validation and parsers on
real output (ABRicate 1.4.0, MOB-suite 3.1.9, IntegronFinder 2.0.6 on S. aureus N315, E. coli plasmid R388 and ARVA's
SYNTHETIC genome: tests/fixtures/<tool>/README.md) and on CONSTRUCTED files for ISEScan and geNomad, which are not
installed here. Real-tool tests skip when the tool or MOB-suite's database is absent."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from arva_tools import abricate as abr
from arva_tools import genomad as gn
from arva_tools import integronfinder as itf
from arva_tools import isescan as ise
from arva_tools import mobsuite as mob
from arva_tools.base import help_options
from arva_tools.registry import detect
from arva_tools.runner import isolated_home, tool_environment

FIX = Path(__file__).parent / "fixtures"
SYNTHETIC = Path(__file__).resolve().parents[3] / "examples" / "synthetic-genome" / "reference.fasta"
MOB_DB = Path(os.environ.get("ARVA_TEST_MOBSUITE_DB") or Path.home() / ".arva-db/mobsuite-3.1.8/3.1.8")
J = Path("/job")


def read(tool: str, name: str) -> str:
    return (FIX / tool / name).read_text()


# --- ABRicate ---------------------------------------------------------------------------------------------------

def test_abricate_options_and_defaults_are_in_its_help():
    text = read("abricate", "help_1.4.0.txt")
    assert set(abr.flags(abr.AbricateParams())) <= help_options(text)
    assert abr.help_defaults(text) == abr.DEFAULTS
    assert {"--setupdb", "--list"} <= help_options(text)


def test_abricate_argv_passes_every_threshold_and_never_updates():
    a = abr.AbricateAdapter.argv("/env/bin/abricate", abr.AbricateParams("plasmidfinder", 90, 60, 2), J / "in.fna",
                                 Path("/env/db"), help_options(read("abricate", "help_1.4.0.txt")))
    assert a == ["/env/bin/abricate", "--datadir", "/env/db", "--db", "plasmidfinder", "--minid", "90", "--mincov",
                 "60", "--threads", "2", "--nopath", "/job/in.fna"]
    assert "--setupdb" not in a
    with pytest.raises(ValueError, match="database must be"):
        abr.AbricateParams("card").validate()
    with pytest.raises(ValueError, match="minid"):
        abr.AbricateParams(minid=0).validate()


def test_abricate_list_and_stderr():
    dbs = {d["name"]: d for d in abr.parse_list(read("abricate", "list_1.4.0.txt"))}
    assert dbs["vfdb"] == {"name": "vfdb", "sequences": 4592, "dbtype": "nucl", "date": "2026-Apr-3"}
    assert dbs["plasmidfinder"]["sequences"] == 488
    log = abr.parse_stderr(read("abricate", "n315.vfdb.stderr.log"))
    assert (log["database"], log["sequences"], log["found"], log["errors"]) == ("vfdb", 4592, 86, [])


def test_vfdb_hits_on_n315_with_their_completeness_and_vfdb_categories():
    rows = abr.classify(abr.parse_report(read("abricate", "n315.vfdb.tsv")), {"NC_002745.2": 2814816,
                                                                             "NC_003140.1": 24653})
    assert len(rows) == 86 and {r["database"] for r in rows} == {"vfdb"}
    kinds = [r["hit_kind"] for r in rows]
    assert (kinds.count("complete"), kinds.count("complete_gaps"), kinds.count("partial")) == (59, 14, 13)
    hlb = next(r for r in rows if r["gene"] == "hlb")
    assert (hlb["hit_kind"], hlb["ref_start"], hlb["ref_end"], hlb["coverage"]) == ("partial", 170, 993, 82.98)
    cap = next(r for r in rows if r["gene"] == "capA")
    assert (cap["hit_kind"], cap["gap_openings"], cap["gap_positions"], cap["coverage"]) == ("complete_gaps", 1, 1, 100.0)
    vf = abr.parse_vfdb_product(next(r for r in rows if r["gene"] == "adsA")["product"])
    assert vf["vf_id"] and vf["vf_id"].startswith("VF") and vf["vfc_id"].startswith("VFC") and vf["vf_category"]


def test_partial_contig_end_and_split_vfdb_hits_on_the_cut_genome():
    lengths = {"NC_002745.2_part1": 31236, "NC_002745.2_part2": 139241, "NC_002745.2_part3": 2814816 - 170477,
               "NC_003140.1": 24653}
    default = abr.classify(abr.parse_report(read("abricate", "n315_cut.vfdb.tsv")), lengths)
    ads = next(r for r in default if r["gene"] == "adsA")
    assert (ads["hit_kind"], ads["ref_start"], ads["coverage"], ads["pieces"]) == ("contig_end", 232, 90.04, None)
    assert not [r for r in default if r["gene"] == "cap8D"], "each half covers 50 %: below --mincov 80"
    low = abr.classify(abr.parse_report(read("abricate", "n315_cut_mincov40.vfdb.tsv")), lengths)
    cap = [r for r in low if r["gene"] == "cap8D"]
    assert [(r["ref_start"], r["ref_end"], r["hit_kind"], r["pieces"]) for r in cap] == [
        (1, 912, "contig_end", 2), (913, 1824, "contig_end", 2)]
    codes = [w["code"] for w in abr.warnings(abr.AbricateParams(mincov=40), low)]
    assert codes[0] == "vfdb_meaning" and {"hits_contig_end", "hits_split", "low_thresholds"} <= set(codes)


def test_plasmidfinder_replicons_and_none_found():
    n315 = abr.parse_report(read("abricate", "n315.plasmidfinder.tsv"))
    assert [(r["contig"], abr.replicon_type(r["gene"])) for r in n315] == [
        ("NC_002745.2", "rep22"), ("NC_003140.1", "rep19"), ("NC_003140.1", "rep5a"), ("NC_003140.1", "rep16")]
    (r388,) = abr.parse_report(read("abricate", "r388.plasmidfinder.tsv"))
    assert (abr.replicon_type(r388["gene"]), r388["identity"], r388["coverage"]) == ("IncW", 100.0, 100.0)
    assert abr.replicon_type("Col(BS512)_1") == "Col(BS512)" and abr.replicon_type("IncFIB(K)_1_Kpn3") == "IncFIB(K)"
    for db in ("vfdb", "plasmidfinder"):
        assert abr.parse_report(read("abricate", f"synthetic.{db}.tsv")) == []


def test_abricate_report_format_is_checked():
    with pytest.raises(ValueError, match="columns"):
        abr.parse_report("#FILE\tSEQUENCE\n")
    bad = read("abricate", "r388.plasmidfinder.tsv").replace("1-243/243", "243")
    with pytest.raises(ValueError, match="COVERAGE"):
        abr.parse_report(bad)


# --- MOB-suite ----------------------------------------------------------------------------------------------------

def test_mob_recon_options_and_defaults_are_in_its_help():
    text = read("mobsuite", "help_3.1.9.txt")
    assert set(mob.flags(mob.MobParams())) <= mob.parse_help_options(text)
    assert mob.help_defaults(text) == mob.DEFAULTS


def test_mob_recon_argv_passes_every_threshold_and_the_database():
    a = mob.MobsuiteAdapter.argv("/env/bin/mob_recon", mob.MobParams(min_rep_ident=90, threads=2), J / "in.fna", J,
                                 Path("/db"), mob.parse_help_options(read("mobsuite", "help_3.1.9.txt")))
    assert a[:11] == ["/env/bin/mob_recon", "--infile", "/job/in.fna", "--outdir", "/job/mob_recon", "--num_threads",
                      "2", "--sample_id", "sample", "--database_directory", "/db"]
    opts = dict(zip(a[11::2], a[12::2], strict=True))
    assert opts["--min_rep_ident"] == "90" and opts["--min_con_cov"] == "60" and opts["--min_rep_evalue"] == "1e-05"
    assert len(opts) == len(mob.DEFAULTS) - 1
    for bad in ({"min_rep_ident": 0}, {"primary_cluster_dist": 2.0}, {"min_mob_evalue": 0.0}):
        with pytest.raises(ValueError):
            mob.MobParams(**bad).validate()


def test_mob_recon_calls_on_n315_r388_and_the_synthetic_genome():
    n315 = {c["contig_id"]: c for c in mob.parse_contig_report(read("mobsuite", "n315.contig_report.txt"))}
    plasmid, chromosome = n315["NC_003140.1"], n315["NC_002745.2"]
    assert (plasmid["molecule_type"], plasmid["primary_cluster_id"], plasmid["relaxase_type(s)"]) == (
        "plasmid", "AA409", ["MOBV"])
    assert plasmid["rep_type(s)"] == ["rep_cluster_1017", "rep_cluster_1733", "rep_cluster_2214"]
    assert (chromosome["molecule_type"], chromosome["rep_type(s)"], chromosome["circularity_status"]) == (
        "chromosome", ["rep_cluster_1018"], "not tested")
    (typed,) = mob.parse_mobtyper(read("mobsuite", "n315.mobtyper_results.txt"))
    assert (mob.plasmid_id(typed), typed["predicted_mobility"], typed["predicted_host_range_overall_name"]) == (
        "AA409", "mobilizable", "Staphylococcus")
    codes = [w["code"] for w in mob.warnings(list(n315.values()), [typed])]
    assert codes == ["chromosome_means_unassigned", "host_range_is_prediction", "replicon_on_unassigned_contig"]
    (r388,) = mob.parse_contig_report(read("mobsuite", "r388.contig_report.txt"))
    assert (r388["rep_type(s)"], r388["mpf_type"][0], r388["mash_neighbor_distance"]) == (["IncW"], "MPF_T", 0.0)
    (r388_typed,) = mob.parse_mobtyper(read("mobsuite", "r388.mobtyper_results.txt"))
    assert r388_typed["predicted_mobility"] == "conjugative"
    assert r388_typed["associated_pmid(s)"] == ["20851899", "28842132"]
    synthetic = mob.parse_contig_report(read("mobsuite", "synthetic.contig_report.txt"))
    assert {c["molecule_type"] for c in synthetic} == {"chromosome"}
    assert mob.summarise(synthetic, [])["plasmids"] == 0


def test_mob_recon_mge_and_biomarker_reports():
    mges = mob.parse_mge_report(read("mobsuite", "n315.mge.report.txt"))
    assert len(mges) == 8 and mges[0]["mge_type"] == "IS1181" and mges[0]["contig_start"] == 426680
    assert mges[0]["primary_cluster_id"] is None
    marks = mob.parse_biomarkers(read("mobsuite", "n315.biomarkers.blast.txt"))
    rep = next(m for m in marks if m["name"] == "rep_cluster_1018")
    assert (rep["biomarker"], rep["contig"], rep["start"], rep["end"], rep["strand"]) == (
        "replicon", "NC_002745.2", 37200, 38204, "-")
    with pytest.raises(ValueError, match="columns"):
        mob.parse_contig_report("sample_id\tmolecule_type\n")


def test_mobsuite_database_preparation_commands_are_mob_inits():
    assert mob.makeblastdb_plasmids("/env/bin/mob_recon", Path("/db")) == [
        "/env/bin/makeblastdb", "-in", "-", "-parse_seqids", "-dbtype", "nucl", "-title", "ncbi_plasmid_full_seqs.fas",
        "-out", "/db/ncbi_plasmid_full_seqs.fas"]
    assert mob.mash_sketch("/env/bin/mob_recon", Path("/db"), 3) == [
        "/env/bin/mash", "sketch", "-p", "3", "-i", "-o", "/db/ncbi_plasmid_full_seqs.fas.msh", "-k", "21", "-s",
        "1000", "-"]
    assert mob.makeblastdb_repetitive("/env/bin/mob_recon", Path("/db"))[-3:] == ["/db/repetitive.dna.fas",
                                                                                  "-dbtype", "nucl"]
    assert "taxdump_file=sys.argv[2]" in mob.taxonomy_build("/env/bin/mob_recon", Path("/db"), Path("/t.tar.gz"))[3]


# --- IntegronFinder -------------------------------------------------------------------------------------------------

def test_integron_finder_options_and_defaults_are_in_its_help():
    text = read("integronfinder", "help_2.0.6.txt")
    p = itf.IntegronParams(promoter_attI=True)
    assert set(itf.flags(p)) <= itf.parse_help_options(text)
    assert itf.help_defaults(text) == itf.DEFAULTS
    a = itf.IntegronfinderAdapter.argv("/env/bin/integron_finder", p, J / "contigs.fna", J, J / "topology.txt",
                                       itf.parse_help_options(text))
    assert a[-3:] == ["--local-max", "--promoter-attI", "/job/contigs.fna"]
    assert a[a.index("--cmsearch") + 1] == "/env/bin/cmsearch" and "--topology-file" in a
    assert p.as_dict()["union_integrases"] is False
    assert itf.topology_text({"c1": True, "c2": None}) == "c1 circ\nc2 lin\n"
    with pytest.raises(ValueError, match="attC sizes"):
        itf.IntegronParams(min_attc_size=300).validate()


def test_integrons_on_r388_n315_and_synthetic():
    rows = itf.parse_integrons(read("integronfinder", "r388.integrons"))
    (one,) = itf.integrons(rows)
    assert (one["type"], one["start"], one["end"], one["strand"], one["attc_sites"], one["topology"]) == (
        "complete", 29666, 32156, "-", 2, "circ")
    assert one["integrase"] == "NC_028464.1_37" and one["cassette_proteins"] == 2
    assert itf.parse_integrons(read("integronfinder", "n315.integrons")) == []
    assert itf.parse_integrons(read("integronfinder", "synthetic.integrons")) == []


# --- ISEScan and geNomad (CONSTRUCTED files; the tools are not installed here) ----------------------------------

def test_isescan_parser_on_a_constructed_file():
    rows = ise.parse_tsv(read("isescan", "constructed.tsv"))
    assert [(r["family"], r["completeness"], r["has_tir"], r["isBegin"], r["isEnd"]) for r in rows] == [
        ("ISL3", "complete", True, 1001, 2394), ("IS3", "partial", False, 1, 801)]
    a = ise.IsescanAdapter.argv("/env/bin/isescan.py", ise.IsescanParams(remove_short_is=True), J / "input" /
                                "contigs.fna", J, frozenset({"--seqfile", "--output", "--nthread", "--removeShortIS"}))
    assert a == ["/env/bin/isescan.py", "--seqfile", "/job/input/contigs.fna", "--output", "/job/isescan", "--nthread",
                 "4", "--removeShortIS"]
    assert ise.tsv_path(J) == J / "isescan" / "input" / "contigs.fna.tsv"
    with pytest.raises(ValueError, match="stage it"):
        ise.IsescanAdapter.argv("/x", ise.IsescanParams(), J / "a.fna", J, frozenset())


def test_genomad_parsers_on_constructed_files():
    (p,) = gn.parse_plasmids(read("genomad", "constructed_plasmid_summary.tsv"))
    assert (p["contig"], p["plasmid_score"], p["fdr"], p["amr_genes"]) == ("contig_2", 0.9871, None, ["blaZ", "blaR1"])
    pro, whole = gn.parse_viruses(read("genomad", "constructed_virus_summary.tsv"))
    assert (pro["contig"], pro["provirus"], pro["start"], pro["end"]) == ("contig_1", True, 2001, 42000)
    assert (whole["contig"], whole["provirus"], whole["start"]) == ("contig_3", False, None)
    assert gn.parse_plasmids(read("genomad", "constructed_empty_plasmid_summary.tsv")) == []
    a = gn.GenomadAdapter.argv("/env/bin/genomad", gn.GenomadParams(threads=2), J / "contigs.fna", J, Path("/db"),
                               frozenset(gn.flags(gn.GenomadParams())))
    assert a[:5] == ["/env/bin/genomad", "end-to-end", "--threads", "2", "--cleanup"] and a[-3:] == [
        "/job/contigs.fna", "/job/genomad", "/db"]
    assert a[a.index("--min-score") + 1] == "0.7"
    assert gn.outputs(J, J / "contigs.fna")["virus"] == J / "genomad/contigs_summary/contigs_virus_summary.tsv"


# --- Real tools -------------------------------------------------------------------------------------------------

def _run(argv: list[str], env: dict[str, str], cwd: Path, out: Path | None = None) -> None:
    with isolated_home() as home:
        with open(out or os.devnull, "w") as fh:
            subprocess.run(argv, check=True, cwd=cwd, stdout=fh, stderr=subprocess.DEVNULL,
                           env={**tool_environment(home), **env})


def _stage(tmp_path: Path) -> Path:
    staged = tmp_path / "input" / "contigs.fna"
    staged.parent.mkdir()
    staged.write_text("".join(f"{ln.split()[0]}\n" if ln.startswith(">") else ln
                              for ln in SYNTHETIC.read_text().splitlines(keepends=True)))
    return staged


def test_real_abricate_finds_nothing_on_the_synthetic_genome(tmp_path):
    d = detect("abricate", refresh=True)
    if d.path is None:
        pytest.skip("ABRicate is not installed")
    assert d.version_validated
    exe = d.path
    assert abr.help_defaults(abr.AbricateAdapter.help_text(exe)) == abr.DEFAULTS
    info = abr.database_info(abr.datadir(exe) / "vfdb")
    assert info["ready"] and info["sequences"] == 4592
    contigs = _stage(tmp_path)
    for db in abr.DATABASES:
        out = tmp_path / f"{db}.tsv"
        _run(abr.AbricateAdapter.argv(exe, abr.AbricateParams(db), contigs, abr.datadir(exe),
                                      abr.AbricateAdapter.help_options(exe)), abr.env_for(exe), tmp_path, out)
        assert abr.parse_report(out.read_text()) == []


def test_real_integron_finder_finds_nothing_on_the_synthetic_genome(tmp_path):
    d = detect("integronfinder", refresh=True)
    if d.path is None:
        pytest.skip("IntegronFinder is not installed")
    exe = d.path
    contigs = _stage(tmp_path)
    topology = tmp_path / "topology.txt"
    topology.write_text(itf.topology_text({"SYNTHETIC_chromosome": True, "SYNTHETIC_plasmid": True}))
    _run(itf.IntegronfinderAdapter.argv(exe, itf.IntegronParams(threads=2), contigs, tmp_path, topology,
                                        itf.IntegronfinderAdapter.help_options(exe)), itf.env_for(exe), tmp_path)
    assert itf.parse_integrons(itf.outputs(tmp_path)["integrons"].read_text()) == []
    assert itf.models(exe) and itf.models_checksum(itf.models(exe)).startswith("sha256:")


def test_real_mob_recon_on_the_synthetic_genome(tmp_path):
    d = detect("mobsuite", refresh=True)
    if d.path is None or not mob.database_state(MOB_DB)["ready"]:
        pytest.skip("MOB-suite or its database (ARVA_TEST_MOBSUITE_DB) is not installed")
    exe = d.path
    assert mob.help_defaults(mob.MobsuiteAdapter.help_text(exe)) == mob.DEFAULTS
    _run(mob.MobsuiteAdapter.argv(exe, mob.MobParams(threads=2), _stage(tmp_path), tmp_path, MOB_DB,
                                  mob.MobsuiteAdapter.help_options(exe)), mob.env_for(exe, tmp_path), tmp_path)
    contigs = mob.parse_contig_report((tmp_path / mob.OUTDIR / mob.OUTPUTS["contig_report"]).read_text())
    assert [(c["contig_id"], c["molecule_type"]) for c in contigs] == [("SYNTHETIC_chromosome", "chromosome"),
                                                                        ("SYNTHETIC_plasmid", "chromosome")]
    assert not (MOB_DB / ".lock").exists() and not (MOB_DB / "status.txt").exists()
    shutil.rmtree(tmp_path / mob.OUTDIR)
