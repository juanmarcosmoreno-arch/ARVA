"""Bakta and Prokka adapters: commands, validation, dependency planning, and parsers on real outputs (fixtures written
by the tools on a SYNTHETIC genome; see the fixture READMEs). Real-tool tests skip when the tool or database is absent.
"""
import json
import os
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest
from arva_core.annotation import fasta_subset, genbank_subset, gff3_subset, links

from arva_tools.bakta import (
    DEPENDENCIES,
    SKIP_FLAGS,
    BaktaAdapter,
    BaktaParams,
    check_dependencies,
    pilercr_test,
    plan_steps,
    skip_options,
)
from arva_tools.base import help_options
from arva_tools.nanoplot import python_of
from arva_tools.prokka import (
    ProkkaAdapter,
    ProkkaParams,
    contig_name_problem,
    database_files,
    database_info,
    database_source,
    link_database,
)

FIXTURES = Path(__file__).parent / "fixtures"
BAKTA = FIXTURES / "bakta"
PROKKA = FIXTURES / "prokka"
GENOME = FIXTURES / "annotation_genome" / "genome.fna"
BAKTA_HELP = help_options((BAKTA / "help_1.12.2.txt").read_text())
PROKKA_HELP = help_options((PROKKA / "help_1.14.6.txt").read_text())
J = Path("/job")
BAKTA_EXE = os.environ.get("ARVA_TOOL_BAKTA") or shutil.which("bakta") or str(Path.home() / ".arva-tools/bakta/bin/bakta")
BAKTA_DB = Path(os.environ.get("ARVA_TEST_BAKTA_DB") or Path.home() / ".arva-db/bakta-light/6.0")


def dep(name: str, status: str, found: str | None = None) -> dict:
    d = next(x for x in DEPENDENCIES if x.name == name)
    return {"name": d.name, "status": status, "found": found, "minimum": ".".join(map(str, d.minimum)),
            "steps": list(d.steps)}


# --- Bakta: command and validation ------------------------------------------------------------------------------

def test_bakta_argv_passes_every_result_changing_option():
    p = BaktaParams(locus_tag="SYNT", genus="Escherichia", species="coli", strain="K-12 MG1655", complete=True,
                    keep_contig_headers=True, threads=3, min_contig_length=200, translation_table=4)
    argv = BaktaAdapter.argv("bakta", p, J / "in.fna", Path("/db"), J / "bakta", J / "tmp", ["--skip-cds", "--skip-ori"],
                             BAKTA_HELP)
    assert argv[:2] == ["bakta", "/job/in.fna"]
    pairs = dict(pairwise(argv[2:]))
    assert pairs["--db"] == "/db" and pairs["--output"] == "/job/bakta" and pairs["--tmp-dir"] == "/job/tmp"
    assert pairs["--threads"] == "3" and pairs["--min-contig-length"] == "200" and pairs["--translation-table"] == "4"
    assert pairs["--locus-tag"] == "SYNT" and pairs["--locus-tag-increment"] == "1" and pairs["--prefix"] == "annotation"
    assert pairs["--strain"] == "K-12 MG1655"
    assert "--complete" in argv and "--keep-contig-headers" in argv
    assert argv[-2:] == ["--skip-cds", "--skip-ori"]


def test_bakta_argv_leaves_out_unset_organism_and_switches():
    argv = BaktaAdapter.argv("bakta", BaktaParams(locus_tag="ABC"), J / "in.fna", Path("/db"), J / "o", J / "t", [],
                             BAKTA_HELP)
    assert not {"--genus", "--species", "--strain", "--complete", "--keep-contig-headers"} & set(argv)


@pytest.mark.parametrize("change", [
    {"locus_tag": "ab"}, {"locus_tag": "1ABC"}, {"locus_tag": "ABC_DEF"}, {"translation_table": 1},
    {"genus": "Esch/../x"}, {"genus": "E"}, {"species": "coli"}, {"genus": "Escherichia", "species": "co$li"},
    {"strain": "K12]; rm -rf"}, {"min_contig_length": 0}, {"threads": 0},
])
def test_bakta_params_are_checked(change):
    with pytest.raises(ValueError):
        BaktaParams(**{"locus_tag": "SYNT", **change}).validate()


def test_bakta_argv_refuses_options_the_installed_help_lacks():
    with pytest.raises(ValueError, match="--complete"):
        BaktaAdapter.argv("bakta", BaktaParams(locus_tag="SYNT", complete=True), J / "a", J / "b", J / "c", J / "d", [],
                          BAKTA_HELP - {"--complete"})
    with pytest.raises(ValueError, match="unknown skip"):
        BaktaAdapter.argv("bakta", BaktaParams(locus_tag="SYNT"), J / "a", J / "b", J / "c", J / "d", ["--skip-all"],
                          BAKTA_HELP)


def test_every_skip_option_is_in_bakta_help():
    assert set(SKIP_FLAGS.values()) <= BAKTA_HELP


# --- Bakta: dependencies and steps ------------------------------------------------------------------------------

def test_plan_skips_steps_of_missing_old_or_crashing_programs():
    deps = [dep(d.name, "ok") for d in DEPENDENCIES]
    deps[[d["name"] for d in deps].index("AMRFinderPlus")] = dep("AMRFinderPlus", "missing")
    deps[[d["name"] for d in deps].index("DIAMOND")] = dep("DIAMOND", "too_old", "2.1.9")
    deps[[d["name"] for d in deps].index("BLAST+ (blastn)")] = dep("BLAST+ (blastn)", "too_old", "2.12.0")
    deps[[d["name"] for d in deps].index("PILER-CR")] = dep("PILER-CR", "crashed", "1.6.0")
    steps = plan_steps(deps, "light", skip_plot=False)
    assert [s for s, v in steps.items() if not v["run"]] == ["crispr", "cds", "pseudo", "sorf", "ori"]
    assert {d["name"] for d in steps["cds"]["dependencies"]} == {"AMRFinderPlus", "DIAMOND"}
    assert steps["pseudo"]["reason"] == "needs_cds"
    assert skip_options(steps) == ["--skip-crispr", "--skip-cds", "--skip-sorf", "--skip-ori"]


def test_pseudogenes_need_the_full_database_and_plot_can_be_switched_off():
    deps = [dep(d.name, "ok") for d in DEPENDENCIES]
    steps = plan_steps(deps, "light", skip_plot=True)
    assert steps["pseudo"] == {"run": False, "reason": "light_database", "dependencies": []}
    assert steps["plot"]["reason"] == "user"
    assert skip_options(steps) == ["--skip-plot"]
    assert plan_steps(deps, "full", skip_plot=False)["pseudo"]["run"]


# --- Bakta: parsers ------------------------------------------------------------------------------------------------

def test_bakta_console_steps_counts_and_crash():
    run = BaktaAdapter.parse_console((BAKTA / "console.log").read_text())
    assert run["skipped"] == ["crispr", "cds", "sorf", "ori"] and run["finished"]
    assert run["found"] == {"trna": 2, "tmrna": 0, "rrna": 2, "ncrna": 1, "ncrna_region": 0, "gap": 1}
    crashed = BaktaAdapter.parse_console((BAKTA / "console_pilercr_crash.log").read_text())
    assert crashed["crispr_crashed"] == -11 and "crispr" in crashed["ran"]
    assert BaktaAdapter.stage("predict CRISPR arrays...\n") == "crispr"
    assert BaktaAdapter.stage("Export annotation results to: /work/out") == "export"


def test_bakta_failure_reason_uses_its_error_line():
    console = "ERROR: Wrong Diamond version installed. Please, either install Diamond version v2.2.0 or use ...!\n"
    assert BaktaAdapter.failure_reason(console, 1).startswith("Bakta stopped: Wrong Diamond version")
    assert BaktaAdapter.failure_reason("", -9).endswith("(out of memory)")
    assert BaktaAdapter.failure_reason("", 1) is None


def test_bakta_json_features_and_sequences():
    sequences, features, meta = BaktaAdapter.parse_json(json.loads((BAKTA / "annotation.json").read_text()))
    assert [(s["id"], s["original_id"], s["length"]) for s in sequences] == [
        ("contig_1", "SYNTHETIC_annotation_chromosome", 17516), ("contig_2", "SYNTHETIC_annotation_plasmid", 1444)]
    assert [f["type"] for f in features] == ["trna", "trna", "rrna", "rrna", "ncrna", "gap"]
    rrs = features[3]
    assert (rrs["locus_tag"], rrs["gene"], rrs["product"], rrs["start"], rrs["end"]) == (
        "SYNT_04", "rrs", "16S ribosomal RNA", 4428, 5953)
    assert rrs["go"] == ["GO:0005840", "GO:0003735"] and "RFAM:RF00177" in rrs["db_xrefs"]
    assert rrs["inference"][0].startswith("Infernal: Rfam model RF00177")
    assert all(f["hypothetical"] is None for f in features)
    assert features[5]["locus_tag"] is None and features[5]["length"] == 100
    assert meta["version"] == {"bakta": "1.12.2", "db": {"version": "6.0", "type": "light"}}
    urls = [link["url"] for link in links(rrs)]
    assert "https://rfam.org/family/RF00177" in urls and "https://www.kegg.jp/entry/K01977" in urls
    assert "https://www.ebi.ac.uk/QuickGO/term/GO:0005840" in urls and "https://identifiers.org/SO:0001000" in urls


def test_bakta_json_cds_fields():
    # Constructed, not Bakta output: Bakta's CDS step needs AMRFinderPlus, which is not installed where these tests
    # were written. The field names are those of Bakta 1.12.2 (features/cds.py, psc.py, io/json.py, io/tsv.py).
    data = {"sequences": [{"id": "contig_1", "orig_id": "c1", "length": 5000}], "features": [
        {"type": "cds", "sequence": "contig_1", "start": 4801, "stop": 150, "strand": "+", "edge": True,
         "gene": "abcA", "product": "ABC transporter", "locus": "SYNT_00010", "id": "X_1", "truncated": "3-prime",
         "db_xrefs": ["EC:7.6.2.1", "COG:COG1131", "COG:V", "GO:0005524", "UniRef:UniRef90_A0A000ABC1"],
         "psc": {"uniref90_id": "UniRef90_A0A000ABC1", "identity": 0.93, "query_cov": 0.99, "subject_cov": 0.97,
                 "evalue": 1e-80}},
        {"type": "cds", "sequence": "contig_1", "start": 300, "stop": 900, "strand": "-", "product":
         "hypothetical protein", "hypothetical": True, "locus": "SYNT_00015", "id": "X_2", "db_xrefs": []},
        {"type": "cds", "sequence": "contig_1", "start": 1000, "stop": 1500, "strand": "+", "product": "transposase",
         "pseudogene": {"causes": ["insertion"]}, "locus": "SYNT_00020", "id": "X_3", "db_xrefs": []},
    ]}
    _, (edge, hypo, pseudo), _ = BaktaAdapter.parse_json(data)
    assert edge["edge"] and edge["length"] == 5000 - 4801 + 1 + 150 and edge["partial"] == "3'"
    assert edge["ec"] == ["7.6.2.1"] and edge["cog"] == ["COG1131"] and edge["cog_categories"] == ["V"]
    assert edge["hypothetical"] is False and edge["inference"][1].startswith("PSC: protein sequence cluster UniRef90")
    assert "https://www.uniprot.org/uniref/UniRef90_A0A000ABC1" in [link["url"] for link in links(edge)]
    assert hypo["hypothetical"] is True and hypo["inference"][-1] == "no function assigned (hypothetical)"
    assert pseudo["pseudo"] is True


# --- Prokka ----------------------------------------------------------------------------------------------------

def test_prokka_argv_passes_every_result_changing_option():
    p = ProkkaParams(locus_tag="SYNT", genus="Escherichia", species="coli", use_genus=True, rfam=True, threads=2,
                     evalue=1e-6, coverage=70, min_contig_length=200)
    argv = ProkkaAdapter.argv("prokka", p, J / "in.fna", J / "db", J / "prokka", PROKKA_HELP)
    pairs = dict(pairwise(argv[2:]))
    assert argv[:2] == ["prokka", "/job/in.fna"]
    assert pairs["--kingdom"] == "Bacteria" and pairs["--gcode"] == "11" and pairs["--locustag"] == "SYNT"
    assert pairs["--cpus"] == "2" and pairs["--evalue"] == "1e-06" and pairs["--coverage"] == "70"
    assert pairs["--mincontiglen"] == "200" and pairs["--dbdir"] == "/job/db" and pairs["--increment"] == "1"
    assert "--usegenus" in argv and "--rfam" in argv and "--strain" not in argv
    assert ProkkaAdapter.setupdb_argv("prokka", J / "db") == ["prokka", "--dbdir", "/job/db", "--setupdb"]


@pytest.mark.parametrize("change", [{"use_genus": True}, {"evalue": 0}, {"coverage": 101}, {"locus_tag": "x"},
                                    {"genus": "Staphylo coccus"}])
def test_prokka_params_are_checked(change):
    with pytest.raises(ValueError):
        ProkkaParams(**{"locus_tag": "SYNT", **change}).validate()


def test_prokka_gff_features():
    sequences, features = ProkkaAdapter.parse_gff((PROKKA / "annotation.gff").read_text())
    assert [s["id"] for s in sequences] == ["SYNTHETIC_annotation_chromosome", "SYNTHETIC_annotation_plasmid"]
    assert len(features) == 20 and sum(f["type"] == "cds" for f in features) == 18
    named = [f for f in features if f["type"] == "cds" and not f["hypothetical"]]
    assert [(f["gene"], f["ec"], f["cog"]) for f in named] == [
        ("alkA", ["3.2.2.21"], ["COG0122"]), ("tag", ["3.2.2.20"], ["COG2818"]), ("quiB", ["4.2.1.10"], ["COG0710"])]
    assert named[0]["accessions"] == ["UniProtKB:P04395"]
    assert "https://www.uniprot.org/uniprotkb/P04395/entry" in [link["url"] for link in links(named[0])]
    assert sum(f["hypothetical"] is True for f in features) == 15
    trna = next(f for f in features if f["type"] == "trna")
    assert trna["product"] == "tRNA-SeC(tca)" and trna["inference"] == ["COORDINATES:profile:Aragorn:001002"]
    assert next(f for f in features if f["type"] == "rrna")["inference"][0].startswith("barrnap 0.9")


def test_prokka_log_programs_mode_and_counts():
    log = ProkkaAdapter.parse_log((PROKKA / "annotation.log").read_text())
    assert log["prodigal_mode"] == "meta" and log["total_bp"] == 18960 and log["finished"]
    assert log["counts"] == {"trna": 1, "rrna": 1, "cds": 18}
    assert log["programs"]["prodigal"]["reported"].startswith("Prodigal V2.6.3")
    assert "minced" not in log["programs"] and not log["crispr_searched"] and not log["ncrna_searched"]
    assert ProkkaAdapter.stage("[19:26:02] Predicting coding sequences") == "cds"


def test_prokka_failure_reasons():
    assert "not indexed" in ProkkaAdapter.failure_reason(
        "[10:00:00] The sequence databases have not been indexed. Please run 'prokka --setupdb' first.", 2)
    assert "37 characters" in ProkkaAdapter.failure_reason(
        "[10:00:00] Contig ID must <= 37 chars long: NODE_1_length_1234567_cov_12.345678_pilon\n"
        "[10:00:00] Please rename your contigs OR try '--centre X --compliant' to generate clean contig names.", 2)
    assert ProkkaAdapter.failure_reason("[10:00:00] Something went wrong", 2) == "Prokka stopped: Something went wrong"
    assert contig_name_problem(["contig_1", "x" * 38]).startswith("1 contig name(s)")
    assert contig_name_problem(["contig_1"]) is None


def test_prokka_database_layout(tmp_path):
    src = tmp_path / "share" / "prokka" / "db"
    for rel in ("kingdom/Bacteria/sprot", "cm/Archaea", "cm/Bacteria", "cm/Viruses", "genus/Escherichia"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "prokka").write_text("")
    assert database_source(str(tmp_path / "bin" / "prokka")) == src
    info = database_info(src)
    assert info["ready"] and info["kingdoms"] == ["Bacteria"] and info["genera"] == ["Escherichia"]
    link_database(src, tmp_path / "linked", database_files(src))
    assert (tmp_path / "linked" / "cm" / "Viruses").resolve() == src / "cm" / "Viruses"
    (src / "cm" / "Viruses").unlink()
    assert not database_info(src)["ready"]


# --- Subsets of the tools' own files ----------------------------------------------------------------------------

def test_subsets_of_real_outputs():
    gff = gff3_subset((BAKTA / "annotation.gff3").read_text(), {"SYNT_04"})
    assert gff.startswith("##gff-version 3") and "##FASTA" not in gff
    assert [ln.split("\t")[2] for ln in gff.splitlines() if not ln.startswith("#")] == ["rRNA"]
    assert "##sequence-region contig_1 " in gff and "contig_2" not in gff
    gbk = genbank_subset((PROKKA / "annotation.gbk").read_text(), {"SYNT_00009"})
    assert gbk.count("LOCUS") == 1 and '/locus_tag="SYNT_00009"' in gbk and '/locus_tag="SYNT_00001"' not in gbk
    assert "ORIGIN" in gbk and gbk.rstrip().endswith("//") and "     source " in gbk
    faa = fasta_subset((PROKKA / "annotation.faa").read_text(), {"SYNT_00009", "SYNT_00014"})
    assert [ln for ln in faa.splitlines() if ln.startswith(">")] == [
        ">SYNT_00009 DNA-3-methyladenine glycosylase 2", ">SYNT_00014 Catabolic 3-dehydroquinate dehydratase"]


# --- Real tools (skipped when absent) ---------------------------------------------------------------------------

def _bakta_installed() -> bool:
    return Path(BAKTA_EXE).is_file() and os.access(BAKTA_EXE, os.X_OK)


@pytest.mark.skipif(shutil.which("pilercr") is None, reason="PILER-CR is not installed")
def test_pilercr_test_runs():
    result = pilercr_test()
    assert set(result) == {"works", "returncode"} and isinstance(result["works"], bool)


@pytest.mark.skipif(not _bakta_installed(), reason="Bakta is not installed")
def test_real_bakta_dependency_report():
    report = check_dependencies(BAKTA_EXE, None)
    assert [r["name"] for r in report] == [d.name for d in DEPENDENCIES]
    pyrodigal = next(r for r in report if r["name"] == "Pyrodigal")
    assert pyrodigal["status"] == "ok" and pyrodigal["command"][0].startswith("python")
    # Bakta's own reading of each version (bakta.utils.read_tool_output), run in Bakta's interpreter.
    script = ("import json, bakta.utils as u\nout = {}\nfor n, d in vars(u).items():\n"
              "    if n.startswith('DEPENDENCY_'):\n        try:\n            v = u.read_tool_output(d)\n"
              "            out[d[3]] = f'{v.major}.{v.minor}.{v.patch}'\n        except SystemExit:\n"
              "            out[d[3]] = None\nprint(json.dumps(out))")
    python = python_of(BAKTA_EXE)
    theirs = json.loads(subprocess.run([*python, "-c", script], capture_output=True, text=True, check=True,
                                       timeout=300).stdout.splitlines()[-1])
    names = {"tRNAscan-SE": "tRNAscan-SE", "Aragorn": "Aragorn", "Infernal (cmscan)": "CMscan", "PILER-CR": "PilerCR",
             "Pyrodigal": "Pyrodigal", "AMRFinderPlus": "AMRFinderPlus", "PyHMMER": "Pyhmmer", "DIAMOND": "Diamond",
             "BLAST+ (blastn)": "Blastn", "pyCirclize": "pyCirclize"}
    assert {r["name"]: r["found"] for r in report} == {ours: theirs[names[ours]] for ours in names}


@pytest.mark.skipif(not _bakta_installed() or not (BAKTA_DB / "version.json").is_file(),
                    reason="Bakta or its light database is not installed")
def test_real_bakta_run_on_synthetic_genome(tmp_path):
    db_type = json.loads((BAKTA_DB / "version.json").read_text())["type"]
    steps = plan_steps(check_dependencies(BAKTA_EXE, BAKTA_DB), db_type, skip_plot=True)
    (tmp_path / "tmp").mkdir()
    argv = BaktaAdapter.argv(BAKTA_EXE, BaktaParams(locus_tag="SYNT", threads=2), GENOME, BAKTA_DB,
                             tmp_path / "out", tmp_path / "tmp", skip_options(steps), BaktaAdapter.help_options(BAKTA_EXE))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    run = BaktaAdapter.parse_console(proc.stdout)
    assert run["finished"] and run["crispr_crashed"] is None
    _, features, _ = BaktaAdapter.parse_json(json.loads((tmp_path / "out" / "annotation.json").read_text()))
    if steps["rrna"]["run"]:
        assert {f["product"] for f in features if f["type"] == "rrna"} == {"5S ribosomal RNA", "16S ribosomal RNA"}
    assert any(f["type"] == "gap" for f in features)


@pytest.mark.skipif(shutil.which("prokka") is None, reason="Prokka is not installed")
def test_real_prokka_run_on_synthetic_genome(tmp_path):
    exe = shutil.which("prokka")
    src = database_source(exe)
    info = database_info(src)
    if not info["ready"]:
        pytest.skip(f"Prokka's databases are not in {src}")
    link_database(src, tmp_path / "db", info["files"])
    subprocess.run(ProkkaAdapter.setupdb_argv(exe, tmp_path / "db"), check=True, capture_output=True, timeout=600)
    argv = ProkkaAdapter.argv(exe, ProkkaParams(locus_tag="SYNT", threads=2), GENOME, tmp_path / "db",
                              tmp_path / "out", ProkkaAdapter.help_options(exe))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    assert proc.returncode == 0, proc.stderr[-2000:]
    _, features = ProkkaAdapter.parse_gff((tmp_path / "out" / "annotation.gff").read_text())
    assert {f["gene"] for f in features if f["gene"]} == {"alkA", "tag", "quiB"}
