"""AMRFinderPlus adapter: options against the real --help, commands, validation, organism choice and parsers on real
AMRFinderPlus 4.2.7 output (tests/fixtures/amrfinderplus/README.md: S. aureus N315 from NCBI, a derived test input,
ARVA's SYNTHETIC genome, and constructed rows). Real-tool tests skip when AMRFinderPlus or its database is absent."""
import os
import subprocess
from pathlib import Path

import pytest

from arva_tools.amrfinderplus import (
    DEFAULTS,
    OUTPUTS,
    AmrfinderplusAdapter,
    AmrParams,
    data_compatible,
    database_check,
    failure,
    flags,
    help_defaults,
    list_organisms,
    method_kind,
    organism_for,
    parse_help_options,
    parse_organisms,
    parse_report,
    parse_stderr,
    point_mutation_screen,
    warnings,
)
from arva_tools.registry import detect

FIXTURES = Path(__file__).parent / "fixtures" / "amrfinderplus"
HELP = (FIXTURES / "help_4.2.7.txt").read_text()
ORGANISMS = parse_organisms((FIXTURES / "list_organisms_2026-08-07.1.txt").read_text())
SYNTHETIC = Path(__file__).resolve().parents[3] / "examples" / "synthetic-genome" / "reference.fasta"
DB = Path(os.environ.get("ARVA_TEST_AMRFINDER_DB") or Path.home() / ".arva-db/amrfinderplus/2026-08-07.1")
J = Path("/job")


def rows(name: str) -> list[dict]:
    return parse_report((FIXTURES / f"{name}.tsv").read_text())


def by_symbol(report: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in report:
        out.setdefault(r["element_symbol"], []).append(r)
    return out


def test_every_option_arva_passes_is_in_the_help_and_defaults_match():
    options = parse_help_options(HELP)
    for p in (AmrParams(), AmrParams(mode="combined", annotation_format="bakta", organism="Escherichia", plus=False)):
        assert set(flags(p)) <= options
    assert help_defaults(HELP) == DEFAULTS
    assert {"-n", "-p", "-g", "-O", "--update", "--force_update"} <= options


def test_nucleotide_argv_passes_every_result_changing_option():
    p = AmrParams(organism="Staphylococcus_aureus", threads=2)
    argv = AmrfinderplusAdapter.argv("/env/bin/amrfinder", p, J / "in.fna", J, Path("/db"), parse_help_options(HELP))
    assert argv == ["/env/bin/amrfinder", "--nucleotide", "/job/in.fna", "--database", "/db",
                    "--output", "/job/amrfinder.tsv", "--nucleotide_output", "/job/nucleotide_hits.fna",
                    "--ident_min", "-1", "--coverage_min", "0.5", "--translation_table", "11", "--threads", "2",
                    "--blast_bin", "/env/bin", "--hmmer_bin", "/env/bin", "--print_node",
                    "--organism", "Staphylococcus_aureus", "--mutation_all", "/job/mutation_all.tsv", "--plus"]
    assert "--update" not in argv and "-u" not in argv


def test_combined_argv_ties_proteins_and_gff():
    p = AmrParams(mode="combined", annotation_format="prokka", plus=False, ident_min=0.95, coverage_min=0.6)
    argv = AmrfinderplusAdapter.argv("/env/bin/amrfinder", p, J / "a.fna", J, Path("/db"), parse_help_options(HELP),
                                     J / "a.faa", J / "a.gff")
    assert argv[1:9] == ["--nucleotide", "/job/a.fna", "--protein", "/job/a.faa", "--gff", "/job/a.gff",
                         "--annotation_format", "prokka"]
    assert "--protein_output" in argv and "--plus" not in argv and "--organism" not in argv
    assert argv[argv.index("--ident_min") + 1] == "0.95" and argv[argv.index("--coverage_min") + 1] == "0.6"
    with pytest.raises(ValueError, match="combined search needs"):
        AmrfinderplusAdapter.argv("amrfinder", p, J / "a.fna", J, Path("/db"), parse_help_options(HELP))
    with pytest.raises(ValueError, match="does not offer --protein, --gff"):
        AmrfinderplusAdapter.argv("amrfinder", p, J / "a.fna", J, Path("/db"), frozenset(flags(AmrParams())),
                                  J / "a.faa", J / "a.gff")


@pytest.mark.parametrize("change", [{"mode": "protein"}, {"mode": "combined"}, {"annotation_format": "bakta"},
                                    {"organism": "staph aureus; rm"}, {"ident_min": 0}, {"ident_min": 1.5},
                                    {"coverage_min": 0}, {"translation_table": 40}, {"threads": 0}])
def test_params_are_checked(change):
    with pytest.raises(ValueError):
        AmrParams(**change).validate()


def test_n315_known_genes_and_methods():
    report = rows("n315")
    genes = by_symbol(report)
    assert len(report) == 49
    for symbol in ("mecA", "mecR1", "mecI", "aadD1", "fosB", "tet(38)", "mepA", "blaZ", "blaI", "blaR1", "bleO"):
        assert symbol in genes, symbol
    assert len(genes["erm(A)"]) == 5 and len(genes["ant(9)-Ia"]) == 5
    mec = genes["mecA"][0]
    assert (mec["contig"], mec["start"], mec["stop"], mec["strand"], mec["method"]) == \
        ("NC_002745.2", 45034, 47037, "-", "EXACTX")
    assert (mec["type"], mec["subtype"], mec["class"], mec["subclass"]) == ("AMR", "AMR", "BETA-LACTAM", "METHICILLIN")
    assert (mec["identity"], mec["coverage"], mec["closest_accession"], mec["protein_id"]) == \
        (100.0, 100.0, "WP_000721310.1", None)
    assert mec["method_info"] == {"kind": "complete", "search": "translated", "full_length": True, "exact": True}
    assert genes["blaZ"][0]["contig"] == "NC_003140.1"
    assert genes["sen"][0]["method_info"]["kind"] == "internal_stop"
    assert genes["seu"][0]["method_info"]["kind"] == "partial" and genes["seu"][0]["coverage"] == 52.11
    assert genes["tst"][0]["type"] == "VIRULENCE" and genes["tst"][0]["scope"] == "plus"
    assert {r["type"] for r in report} == {"AMR", "VIRULENCE", "STRESS"}
    assert sum(r["type"] == "VIRULENCE" for r in report) == 23
    assert not any(r["subtype"] == "POINT" for r in report)
    screen = point_mutation_screen(parse_report((FIXTURES / "n315.mutation_all.tsv").read_text()))
    assert "DNA gyrase subunit A GyrA" in screen["genes"] and screen["mutations"] == 0 and screen["wildtype_positions"]
    log = parse_stderr((FIXTURES / "n315.stderr.log").read_text())
    assert log == {"software_version": "4.2.7", "database_version": "2026-08-07.1",
                   "search": "translated nucleotide and mutation", "includes": [],
                   "warnings": ["This was compiled for running under bioconda, but $CONDA_PREFIX was not found"],
                   "error": None}


def test_edited_genome_point_mutation_contig_end_and_internal_stop():
    genes = by_symbol(rows("n315_edited"))
    gyr = genes["gyrA_S84L"][0]
    assert (gyr["type"], gyr["subtype"], gyr["class"], gyr["method"]) == ("AMR", "POINT", "QUINOLONE", "POINTX")
    assert gyr["method_info"]["kind"] == "point" and gyr["method_info"]["full_length"] is None
    mec = genes["mecA"][0]
    assert (mec["contig"], mec["start"], mec["method"], mec["coverage"]) == \
        ("NC_002745.2_part2", 3, "PARTIAL_CONTIG_ENDX", 59.88)
    assert mec["method_info"]["kind"] == "contig_end" and mec["method_info"]["full_length"] is False
    assert genes["blaZ"][0]["method"] == "INTERNAL_STOP" and genes["blaZ"][0]["identity"] == 99.64
    screen = point_mutation_screen(parse_report((FIXTURES / "n315_edited.mutation_all.tsv").read_text()))
    assert screen["mutations"] == 1
    codes = [w["code"] for w in warnings(AmrParams(organism="Staphylococcus_aureus"), rows("n315_edited"), screen)]
    assert codes == ["genotype_not_phenotype", "hits_partial", "hits_contig_end", "hits_internal_stop"]


def test_synthetic_genome_finds_nothing_and_says_what_was_not_searched():
    assert rows("synthetic") == []
    log = parse_stderr((FIXTURES / "synthetic.stderr.log").read_text())
    assert log["search"] == "translated nucleotide"
    assert log["includes"] == ["-O ORGANISM, --organism ORGANISM option to add mutation searches and suppress common "
                               "proteins"]
    codes = [w["code"] for w in warnings(AmrParams(), [], None)]
    assert codes == ["genotype_not_phenotype", "point_mutations_not_searched"]


def test_constructed_rows_hmm_nucleotide_point_stx_and_protein_contig_end():
    genes = by_symbol(rows("constructed"))
    assert genes["blaOXA"][0]["method_info"]["kind"] == "hmm" and genes["blaOXA"][0]["identity"] is None
    assert genes["23S_A2058G"][0]["method_info"] == {"kind": "point", "search": "nucleotide", "full_length": None,
                                                     "exact": False}
    assert genes["stx2"][0]["method_info"]["kind"] == "complete" and genes["stx2"][0]["method_info"]["stx"]
    assert genes["mgrB_@_C28STOP"][0]["subtype"] == "POINT_DISRUPT"
    tet = genes["tet(M)"][0]
    assert tet["protein_id"] == "prot_12" and tet["method_info"]["search"] == "protein"
    assert method_kind("FRAMESHIFT")["kind"] == "frameshift" and method_kind("SOMETHING")["kind"] == "other"


def test_report_problems_are_refused():
    header = (FIXTURES / "n315.tsv").read_text().splitlines()[0]
    with pytest.raises(ValueError, match="empty"):
        parse_report("")
    with pytest.raises(ValueError, match="lacks the columns"):
        parse_report("Protein id\tContig id\n")
    with pytest.raises(ValueError, match="does not know"):
        parse_report(header + "\tExtra\n")
    with pytest.raises(ValueError, match="fields instead of"):
        parse_report(header + "\nNA\tc\t1\n")
    with pytest.raises(ValueError, match="line 2"):
        parse_report(header + "\n" + "\t".join(["x"] * len(header.split("\t"))) + "\n")


def test_organism_from_species_by_the_wiki_table():
    assert len(ORGANISMS) == 32 and "Staphylococcus_aureus" in ORGANISMS
    assert organism_for("Staphylococcus aureus", ORGANISMS)["organism"] == "Staphylococcus_aureus"
    assert organism_for("Shigella sonnei", ORGANISMS) == {"organism": "Escherichia", "rule": "genus",
                                                           "complex_note": None}
    assert organism_for("Salmonella enterica", ORGANISMS)["organism"] == "Salmonella"
    assert organism_for("Klebsiella aerogenes", ORGANISMS)["rule"] == "wiki_note"
    assert organism_for("Campylobacter jejuni", ORGANISMS)["organism"] == "Campylobacter"
    other = organism_for("Klebsiella variicola", ORGANISMS)
    assert other["organism"] is None and other["complex_option"] == "Klebsiella_pneumoniae"
    assert organism_for("Bacillus subtilis", ORGANISMS)["rule"] == "not_curated"
    assert organism_for("Staphylococcus aureus", [])["organism"] is None
    assert organism_for(None, ORGANISMS)["rule"] == "no_species"
    assert organism_for("uncultured", ORGANISMS)["rule"] == "not_a_species_name"


def test_database_compatibility_rules_and_refusal_text():
    text = (FIXTURES / "database_version_bakta_light_6.0.txt").read_text()
    assert failure(text) == "Software requires database version at least 2025-09-22.2"
    assert data_compatible("4.2.7", "2024-12-18.1", "4.0.1")["status"] == "data_too_old"
    assert data_compatible("4.2.7", "2026-08-07.1", "4.2.0")["status"] == "compatible"
    assert data_compatible("4.2.7", "2026-08-07.1", "4.3.0")["status"] == "software_too_old"
    assert data_compatible("4.3.0", "2026-08-07.1", "4.2.0")["status"] == "unknown"
    assert set(OUTPUTS) == {"report", "mutation_all", "nucleotide_hits", "protein_hits", "log"}


# --- Real tool (skipped when absent) ---------------------------------------------------------------------------

def _tool():
    d = detect("amrfinderplus", refresh=True)
    if d.path is None:
        pytest.skip("AMRFinderPlus is not installed")
    return d


def test_real_help_and_version():
    d = _tool()
    assert d.version == "4.2.7" and d.version_validated
    assert set(flags(AmrParams(mode="combined", annotation_format="bakta", organism="Escherichia"))) <= \
        AmrfinderplusAdapter.help_options(d.path)
    assert help_defaults(AmrfinderplusAdapter.help_text(d.path)) == DEFAULTS


def test_real_database_checks_and_run_on_synthetic_genome(tmp_path):
    d = _tool()
    if not (DB / "AMRProt.fa.phr").is_file():
        pytest.skip(f"no indexed AMRFinderPlus database at {DB} (ARVA_TEST_AMRFINDER_DB)")
    assert database_check(d.path, DB) == {"ok": True, "version": DB.name, "software": "4.2.7", "error": None}
    assert list_organisms(d.path, DB) == ORGANISMS
    bakta_copy = Path.home() / ".arva-db/bakta-light/6.0/amrfinderplus-db/latest"
    if bakta_copy.is_dir():
        refused = database_check(d.path, bakta_copy)
        assert refused["ok"] is False and refused["version"] == "2024-12-18.1"
        assert refused["error"] == "Software requires database version at least 2025-09-22.2"
    (tmp_path / "tmp").mkdir()
    argv = AmrfinderplusAdapter.argv(d.path, AmrParams(threads=2), SYNTHETIC, tmp_path, DB,
                                     AmrfinderplusAdapter.help_options(d.path))
    env = {**os.environ, **AmrfinderplusAdapter().environment(d.path), "TMPDIR": str(tmp_path / "tmp")}
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600, env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert parse_report((tmp_path / OUTPUTS["report"]).read_text()) == []
