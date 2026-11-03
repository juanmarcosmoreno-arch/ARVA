"""S. aureus typing adapters (sccmec, spaTyper, AgrVATE): options against the real help texts, commands, parsers on
real output for N315, USA300_FPR3757 and ARVA's SYNTHETIC genome (tests/fixtures/<tool>/README.md, with the published
types and their sources), on CONSTRUCTED Ridom-format files and on constructed tables for the cases the genomes do not
show. Real-tool tests skip when the tool is not installed."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from arva_tools import agrvate as ag
from arva_tools import sccmec as sc
from arva_tools import spatyper as sp
from arva_tools.base import help_options
from arva_tools.registry import detect
from arva_tools.runner import isolated_home, tool_environment

FIX = Path(__file__).parent / "fixtures"
SYNTHETIC = Path(__file__).resolve().parents[3] / "examples" / "synthetic-genome" / "reference.fasta"
CONSTRUCTED = FIX / "spatyper" / "constructed"
J = Path("/job")


def read(tool: str, name: str) -> str:
    return (FIX / tool / name).read_text()


def _run(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    with isolated_home() as home:
        return subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=900,
                              env={**tool_environment(home), **env}, check=False)


# --- sccmec -----------------------------------------------------------------------------------------------------

def test_sccmec_options_and_defaults_are_in_its_help():
    text = read("sccmec", "help_1.2.0.txt")
    assert set(sc.flags()) <= sc.parse_help_options(text)
    assert sc.help_defaults(text) == sc.DEFAULTS
    p = sc.SccmecParams()
    assert {k.replace("_", "-"): str(v) for k, v in p.as_dict().items()} == sc.DEFAULTS


def test_sccmec_argv_passes_the_schema_files_and_every_threshold():
    a = sc.SccmecAdapter.argv("/env/bin/sccmec", sc.SccmecParams(min_targets_pident=95), J / "contigs.fasta", J,
                              sc.parse_help_options(read("sccmec", "help_1.2.0.txt")))
    assert a[:3] == ["/env/bin/sccmec", "--input", "/job/contigs.fasta"]
    assert a[a.index("--yaml-targets") + 1] == "/env/share/sccmec/sccmec-targets.yaml"
    assert a[a.index("--regions") + 1] == "/env/share/sccmec/sccmec-regions.fasta"
    assert a[a.index("--min-targets-pident") + 1] == "95" and a[a.index("--min-regions-coverage") + 1] == "83"
    assert a[-4:] == ["--prefix", "sccmec", "--outdir", "/job/sccmec"]
    with pytest.raises(ValueError, match="between 1 and 100"):
        sc.SccmecParams(min_regions_coverage=0).validate()
    with pytest.raises(ValueError, match="does not offer"):
        sc.SccmecAdapter.argv("/env/bin/sccmec", sc.SccmecParams(), J / "c.fa", J, frozenset({"--input"}))


SCHEMA = {"aliases": [{"name": "ccr Type 2", "targets": ["ccrA2", "ccrB2"]},
                      {"name": "ccr Type 5", "targets": ["ccrC1"]},
                      {"name": "mec Class A", "targets": ["IS431", "mecA", "mecR1", "mecI"]},
                      {"name": "mec Class B", "targets": ["IS431", "mecA", "mecR1", "IS1272"]}]}


def test_sccmec_n315_is_type_ii_subtype_iia():
    r = sc.parse_result(read("sccmec", "n315.tsv"))
    assert (r["type"], r["subtype"], r["mecA"], r["coverage"], r["hits"]) == ("II", "IIa", True, 100.0, 47)
    assert r["targets"] == ["ccrA2", "ccrB2", "IS431", "IS431_1", "IS431_2", "mecA", "mecI", "mecR1"]
    assert (r["target_schema_version"], r["region_schema_version"], r["camlhmp_version"]) == ("1.2.0", "1.2.0", "1.1.4")
    assert sc.interpret(r) == {"status": "typed", "call": "IIa"}
    assert sc.complexes(r["targets"], SCHEMA) == {"ccr": ["ccr Type 2"], "mec": ["mec Class A"]}
    details = sc.parse_target_details(read("sccmec", "n315.targets.details.tsv"))
    assert [d["type"] for d in details if d["status"]] == ["II"]
    regions = sc.parse_region_details(read("sccmec", "n315.regions.details.tsv"))
    assert [(x["subtype"], x["coverage"]) for x in regions if x["status"]] == [("IIa", 100.0)]
    hits = {h["target"]: h for h in sc.target_hits(sc.parse_blast(read("sccmec", "n315.targets.blastn.tsv")), 90, 80)}
    assert hits["mecA"]["passes"] and hits["mecA"]["contig"] == "NC_002745.2" and hits["ccrA2"]["identity"] == 100.0


def test_sccmec_usa300_is_type_iv_subtype_iva_and_synthetic_is_not_typeable():
    r = sc.parse_result(read("sccmec", "usa300.tsv"))
    assert (r["type"], r["subtype"], r["coverage"]) == ("IV", "IVa", 94.12)
    assert sc.complexes(r["targets"], SCHEMA) == {"ccr": ["ccr Type 2"], "mec": ["mec Class B"]}
    s = sc.parse_result(read("sccmec", "synthetic.tsv"))
    assert (s["type"], s["subtype"], s["mecA"], s["targets"]) == (None, None, False, [])
    assert "could not be determined" in s["comment"]
    assert sc.interpret(s) == {"status": "not_typeable", "call": None}
    assert sc.parse_blast(read("sccmec", "synthetic.targets.blastn.tsv")) == []


def test_sccmec_several_subtypes_of_one_type_keep_the_type():
    """Real sccmec 1.2.0 output (fixtures/sccmec/README.md): type IV with subtypes IVa and IVn both above the
    threshold, one coverage and one hit count per region, comma-separated."""
    r = sc.parse_result((FIX / "sccmec" / "jkd6159_subset.tsv").read_text())
    assert (r["type"], r["subtype"], r["regions"]) == ("IV", "multiple", ["IVa", "IVn"])
    assert (r["coverage"], r["hits"]) == (None, None)
    assert (r["region_coverage"], r["region_hits"]) == ([96.32, 83.92], [23, 17])
    assert sc.interpret(r) == {"status": "multiple_subtypes", "call": "IV"}


def test_sccmec_constructed_rows_for_partial_and_multiple_evidence():
    header = "\t".join(sc.RESULT_COLUMNS)
    row = "x\t-\t-\t+\tIS431,mecA,mecR1\t\t\t\tt\t1.2.0\tr\t1.2.0\t1.1.4\tp\t\t\t"
    r = sc.parse_result(f"{header}\n{row}\n")
    assert sc.interpret(r) == {"status": "mec_without_type", "call": None}
    assert sc.interpret({**r, "type": "IV", "subtype": None}) == {"status": "type_only", "call": "IV"}
    assert sc.interpret({**r, "type": "multiple", "subtype": "-"})["status"] == "multiple"
    with pytest.raises(ValueError, match="other columns"):
        sc.parse_result("sample\ttype\nx\tII\n")
    with pytest.raises(ValueError, match="mecA"):
        sc.parse_result(f"{header}\n{row.replace(chr(9) + '+' + chr(9), chr(9) + '?' + chr(9))}\n")


# --- spaTyper ---------------------------------------------------------------------------------------------------

def test_spatyper_options_are_in_its_help_and_enrichment_is_not_offered():
    text = read("spatyper", "help_0.3.3.txt")
    assert set(sp.flags()) <= help_options(text)
    assert sp.SpatyperAdapter.version_pattern.search(text).group(1) == "0.3.3"
    a = sp.SpatyperAdapter.argv("/env/bin/spaTyper", sp.SpaParams(), J / "contigs.fasta", Path("/ridom"), J,
                                help_options(text))
    assert a == ["/env/bin/spaTyper", "--repeat_file", "/ridom/sparepeats.fasta", "--repeat_order_file",
                 "/ridom/spatypes.txt", "--fasta", "/job/contigs.fasta", "--output", "/job/spatyper.tsv"]
    assert "-e" not in a and "--do_enrich" not in a and "--folder" not in a
    with pytest.raises(ValueError, match="standard output"):
        sp.SpaParams(do_enrich=True).validate()


def test_spa_types_of_n315_usa300_and_synthetic():
    n315 = sp.parse_output(read("spatyper", "n315.spatyper.tsv"))
    assert sp.interpret(n315) == {"status": "typed", "call": "t002", "repeats": "26-23-17-34-17-20-17-12-17-16"}
    usa300 = sp.parse_output(read("spatyper", "usa300.spatyper.tsv"))
    assert usa300[0]["contig"] == "NC_007793.1" and usa300[0]["repeat_count"] == 10
    assert sp.interpret(usa300) == {"status": "typed", "call": "t008", "repeats": "11-19-12-21-17-34-24-34-22-25"}
    assert sp.interpret(sp.parse_output(read("spatyper", "synthetic.spatyper.tsv")))["status"] == "not_found"


def test_spa_constructed_edge_cases():
    head = "Sequence name\tRepeats\tType\n"
    new = sp.parse_output(head + "c\t93-91\t93-91\n")
    assert sp.interpret(new) == {"status": "new_repeat_succession", "call": None, "repeats": "93-91"}
    gap = sp.parse_output(head + "c\t91-xx-92\t91-xx-92\n")
    assert sp.interpret(gap)["status"] == "unknown_repeat"
    two = sp.parse_output(head + "a\t91-92-93\tt9001\nb\t93-91\t93-91\n")
    assert sp.interpret(two) == {"status": "multiple", "call": None, "repeats": None}
    with pytest.raises(ValueError, match="neither"):
        sp.parse_output(head + "c\t91-92\tt12x\n")
    with pytest.raises(ValueError, match="other columns"):
        sp.parse_output("contig\trepeats\n")


def test_constructed_ridom_folder_counts_and_checksums():
    assert sp.count_entries(CONSTRUCTED) == {"repeats": 3, "types": 1}
    assert set(sp.file_checksums(CONSTRUCTED)) == {"sparepeats.fasta", "spatypes.txt"}


# --- AgrVATE ----------------------------------------------------------------------------------------------------

def test_agrvate_options_are_in_its_help():
    text = read("agrvate", "help_1.0.2.txt")
    assert set(ag.flags()) <= ag.parse_help_options(text)
    assert "--typing-only" in ag.parse_help_options(text)
    a = ag.AgrvateAdapter.argv("/env/bin/agrvate", ag.AgrParams(), ag.parse_help_options(text))
    assert a[:4] == ["/env/bin/agrvate", "--input", "contigs.fasta", "--mummer"]
    assert a[-1].endswith("agrvate_databases/") and "--force" not in a
    with pytest.raises(ValueError, match="32-bit"):
        ag.AgrParams(mode="usearch").validate()


def test_agr_groups_of_n315_usa300_and_synthetic():
    n315 = ag.parse_summary(read("agrvate", "n315.summary.tab"))
    assert n315 == {"agr_group": "II", "agr_group_code": "gp2", "match_score": 15, "canonical_agrD": "canonical",
                    "multiple_agr": "single", "frameshifts": 0}
    assert ag.interpret(n315) == {"status": "typed", "call": "II"}
    coords = ag.parse_coords(read("agrvate", "n315.out.1coords"))
    assert (len(coords["fragments"]), coords["reference_length"], coords["covered_bases"]) == (2, 3482, 2241)
    assert coords["covered_fraction"] == 0.6436
    assert ag.parse_variants(read("agrvate", "n315.agr_operon_frameshifts.tab")) == []
    usa = ag.parse_summary(read("agrvate", "usa300.summary.tab"))
    assert ag.interpret(usa) == {"status": "typed", "call": "I"} and usa["match_score"] == 13
    assert ag.parse_coords(read("agrvate", "usa300.out.1coords"))["covered_fraction"] == 1.0
    assert ag.parse_error_report(read("agrvate", "usa300.error-report.tab"))["snippy_check"] == "pass"
    syn = ag.parse_summary(read("agrvate", "synthetic.summary.tab"))
    assert (syn["agr_group"], syn["frameshifts"], syn["canonical_agrD"]) == (None, None, "unknown")
    assert ag.interpret(syn) == {"status": "untypeable", "call": None}
    assert ag.parse_error_report(read("agrvate", "synthetic.error-report.tab"))["snippy_check"] == "fail"


def test_agr_constructed_rows():
    head = "\t".join(ag.SUMMARY_COLUMNS) + "\n"
    low = ag.parse_summary(head + "contigs\tgp3\t3\tu\ts\tu\n")
    assert ag.interpret(low) == {"status": "low_confidence", "call": "III"} and low["frameshifts"] is None
    multi = ag.parse_summary(head + "contigs\tgp1\t12\t1\tm\t0\n")
    assert ag.interpret(multi) == {"status": "multiple", "call": None}
    variants = ag.parse_variants("\t".join(ag.VARIANT_COLUMNS) + "\ncontigs\t2013\tdel\tframeshift_variant c.16del\t"
                                 "agrC\n")
    assert variants == [{"position": 2013, "type": "del", "effect": "frameshift_variant c.16del", "gene": "agrC"}]
    with pytest.raises(ValueError, match="unknown agr group"):
        ag.parse_summary(head + "contigs\tgp5\t9\t1\ts\t0\n")


# --- Real tools ---------------------------------------------------------------------------------------------------

def _stage(tmp_path: Path, src: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copy(src, dest)
    return dest


def test_real_sccmec_on_the_synthetic_genome(tmp_path):
    d = detect("sccmec", refresh=True)
    if d.path is None:
        pytest.skip("sccmec is not installed")
    assert d.version == "1.2.0"
    contigs = _stage(tmp_path, SYNTHETIC, "contigs.fasta")
    proc = _run(sc.SccmecAdapter.argv(d.path, sc.SccmecParams(), contigs, tmp_path,
                                      sc.SccmecAdapter.help_options(d.path)), sc.env_for(d.path), tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert sc.interpret(sc.parse_result(sc.outputs(tmp_path)["result"].read_text()))["status"] == "not_typeable"
    schema = sc.read_schema(d.path, sc.schema_files(d.path)[0])
    assert schema["engine"]["params"] == {"min_pident": 90, "min_coverage": 80}
    assert {t["name"] for t in schema["types"]} == {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI",
                                                     "XII", "XIII", "XIV", "XV"}
    regions = sc.read_schema(d.path, sc.schema_files(d.path)[1])
    assert regions["engine"]["params"] == {"min_pident": 85, "min_coverage": 83}
    assert "IVh" not in regions["targets"] and {"IIe", "IVn", "Vc"} <= set(regions["targets"])


@pytest.mark.parametrize("genome,expected", [("typed", ("typed", "t9001")), ("new_succession",
                                              ("new_repeat_succession", None)), ("gap", ("unknown_repeat", None)),
                                              ("two_contigs", ("multiple", None)), ("lower_case", ("not_found", None))])
def test_real_spatyper_on_constructed_ridom_files(tmp_path, genome, expected):
    d = detect("spatyper", refresh=True)
    if d.path is None:
        pytest.skip("spaTyper is not installed")
    assert d.version == "0.3.3"
    prefix = Path(os.path.realpath(d.path)).parent.parent
    assert not list(prefix.glob("bin/sparepeats.fasta")), "the Ridom copies bundled in the package must be removed"
    contigs = _stage(tmp_path, CONSTRUCTED / f"{genome}.fasta", "contigs.fasta")
    proc = _run(sp.SpatyperAdapter.argv(d.path, sp.SpaParams(), contigs, CONSTRUCTED, tmp_path,
                                        sp.SpatyperAdapter.help_options(d.path)), sp.env_for(d.path), tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    call = sp.interpret(sp.parse_output((tmp_path / sp.OUTPUT).read_text()))
    assert (call["status"], call["call"]) == expected


def test_real_agrvate_mummer_mode_on_the_synthetic_genome(tmp_path):
    d = detect("agrvate", refresh=True)
    if d.path is None:
        pytest.skip("AgrVATE is not installed")
    assert d.version == "1.0.2"
    _stage(tmp_path, SYNTHETIC, ag.INPUT)
    proc = _run(ag.AgrvateAdapter.argv(d.path, ag.AgrParams(), ag.AgrvateAdapter.help_options(d.path)),
                ag.env_for(d.path), tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = ag.outputs(tmp_path)
    assert ag.interpret(ag.parse_summary(out["summary"].read_text()))["status"] == "untypeable"
    assert "Unable to find agr operon" in proc.stdout
    files = ag.database_files(d.path)
    assert any(f.name == "gp1234_all_motifs.fna" for f in files)
    assert ag.database_checksum(files, ag.databases_dir(d.path)).startswith("sha256:")
