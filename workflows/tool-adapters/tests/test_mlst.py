"""mlst adapter: command, validation, and parsers on real mlst 2.35.0 output (tests/fixtures/mlst/README.md: two NCBI
genomes, ARVA's SYNTHETIC genome and two derived test inputs). Real-tool runs skip when mlst is not installed."""
import gzip
from pathlib import Path

import pytest

from arva_tools.base import help_options
from arva_tools.mlst import (
    DEFAULT_EXCLUDE,
    DEFAULTS,
    OUTPUTS,
    MlstAdapter,
    MlstParams,
    check_json,
    clonal_complex,
    database_dir,
    database_info,
    database_version,
    env_for,
    flags,
    help_defaults,
    parse_call,
    parse_full,
    parse_novel,
    parse_stderr,
    warnings,
)
from arva_tools.registry import detect

FIXTURES = Path(__file__).parent / "fixtures" / "mlst"
HELP = (FIXTURES / "help_2.35.0.txt").read_text()
SYNTHETIC = Path(__file__).resolve().parents[3] / "examples" / "synthetic-genome" / "reference.fasta"


def fixture(name: str) -> tuple[dict, dict]:
    rows = parse_full((FIXTURES / f"{name}.tsv").read_text())
    check_json(rows, (FIXTURES / f"{name}.json").read_text())
    assert len(rows) == 1
    return rows[0], parse_stderr((FIXTURES / f"{name}.stderr.log").read_text())


def calls(row: dict) -> dict[str, tuple[str, str]]:
    return {a["locus"]: (a["call"], a["type"]) for a in row["alleles"]}


@pytest.mark.parametrize(("call", "kind", "alleles", "similar"), [
    ("3", "exact", ["3"], None), ("~3", "novel", [], "3"), ("725?", "partial", [], "725"), ("-", "missing", [], None),
    ("1,3", "multiple", ["1", "3"], None), ("0", "null", [], None), ("12.1", "exact", ["12.1"], None),
    ("~3?", "unrecognised", [], None),
])
def test_call_notation(call, kind, alleles, similar):
    assert parse_call(call) == {"call": call, "type": kind, "alleles": alleles, "similar_to": similar}


def test_saureus_ncbi_genome_is_st8_without_clonal_complex_column():
    row, log = fixture("saureus_NC_007795.1")
    assert (row["scheme"], row["st"], row["status"], row["score"]) == ("saureus", "8", "PERFECT", 100)
    assert calls(row) == {"arcC": ("3", "exact"), "aroE": ("3", "exact"), "glpF": ("1", "exact"),
                          "gmk": ("1", "exact"), "pta": ("4", "exact"), "tpi": ("4", "exact"), "yqiL": ("3", "exact")}
    assert log["excluded"] == sorted(DEFAULT_EXCLUDE) and log["ties"] == [] and log["novel_alleles"] == 0
    assert log["blastn"].startswith("blastn -query") and "-perc_identity 95" in log["blastn"]
    assert log["exact_by_scheme"]["efaecium"] == ["gyd"]
    assert warnings(row, log, False) == []


def test_ecoli_ncbi_genome_is_achtman_st10():
    row, log = fixture("ecoli_NC_000913.3")
    assert (row["scheme"], row["st"], row["status"]) == ("ecoli_achtman_4", "10", "PERFECT")
    assert [a["locus"] for a in row["alleles"]] == ["adk", "fumC", "gyrB", "icd", "mdh", "purA", "recA"]
    assert sorted(log["exact_by_scheme"]["salmonella"]) == ["aroC", "dnaN", "hemD", "hisD", "sucA", "thrA"]


def test_forced_scheme():
    row, log = fixture("ecoli_NC_000913.3_scheme_ecoli")
    assert (row["scheme"], row["st"]) == ("ecoli", "262") and log["excluded"] is None
    assert warnings(row, log, True) == [{"code": "scheme_forced", "params": {"scheme": "ecoli"}}]


def test_synthetic_genome_has_no_scheme():
    row, log = fixture("synthetic")
    assert (row["scheme"], row["st"], row["status"], row["score"], row["alleles"]) == (None, None, "NONE", 0, [])
    assert warnings(row, log, False) == [{"code": "no_scheme", "params": {}}]


def test_edited_genome_shows_every_inexact_call():
    row, log = fixture("saureus_edited")
    assert (row["scheme"], row["st"], row["status"], row["score"]) == ("saureus", None, "MIXED", 66)
    c = calls(row)
    assert c["arcC"] == ("~3", "novel") and c["gmk"] == ("725?", "partial") and c["tpi"] == ("-", "missing")
    assert c["yqiL"] == ("1,3", "multiple")
    assert log["additional_exact"] == [{"scheme": "saureus", "locus": "yqiL", "allele": "1"}]
    assert log["novel_alleles"] == 1
    novel = parse_novel((FIXTURES / "saureus_edited.novel.fasta").read_text())
    assert [(n["scheme"], n["locus"], len(n["md5"]), n["length"]) for n in novel] == [("saureus", "arcC", 32, 456)]
    codes = [w["code"] for w in warnings(row, log, False)]
    assert codes == ["novel_alleles", "partial_alleles", "missing_alleles", "multiple_alleles", "st_not_assigned"]


def test_mixed_genomes_tie_is_reported():
    row, log = fixture("mixed")
    assert (row["scheme"], row["st"]) == ("saureus", "8")
    assert log["ties"] == [{"scheme": "saureus", "st": "8", "other_scheme": "ecoli_achtman_4", "other_st": "10",
                            "score": 100}]
    assert warnings(row, log, False) == [{"code": "tied_schemes",
                                          "params": {"schemes": "ecoli_achtman_4, saureus", "score": 100}}]


def test_json_must_agree_with_full_output():
    rows = parse_full((FIXTURES / "saureus_NC_007795.1.tsv").read_text())
    text = (FIXTURES / "saureus_NC_007795.1.json").read_text().replace('"8"', '"9"')
    with pytest.raises(ValueError, match="disagree"):
        check_json(rows, text)
    with pytest.raises(ValueError, match="FILE SCHEME"):
        parse_full("input.fna\tsaureus\t8\tarcC(3)\n")


def test_help_lists_every_flag_and_the_recorded_defaults():
    supported = help_options(HELP)
    for params in (MlstParams(), MlstParams(scheme="saureus", minscore=0, exclude=[])):
        assert set(flags(params)) <= supported
    assert help_defaults(HELP) == DEFAULTS
    assert {"--legacy", "--csv", "--label"} <= supported


def test_argv_auto_and_forced(tmp_path):
    db, out, genome = tmp_path / "db", tmp_path / "out", tmp_path / "input" / "genome.fna"
    supported = help_options(HELP)
    a = MlstAdapter.argv("/env/bin/mlst", MlstParams(threads=4), genome, out, db, supported)
    assert a == ["/env/bin/mlst", "--full", "--outfile", str(out / OUTPUTS["tsv"]), "--json", str(out / "mlst.json"),
                 "--novel", str(out / "novel_alleles.fasta"), "--threads", "4", "--minid", "95", "--mincov", "50",
                 "--minscore", "50", "--exclude", "ecoli,abaumannii,vcholerae_2,senterica_achtman_2",
                 "--blastdb", str(db / "blast" / "mlst.fa"), "--datadir", str(db / "pubmlst"), str(genome)]
    forced = MlstAdapter.argv("mlst", MlstParams(scheme="saureus", minscore=0, exclude=[], minid=97.5), genome, out,
                              db, supported)
    assert forced[forced.index("--scheme") + 1] == "saureus" and "--exclude" not in forced
    assert forced[forced.index("--minid") + 1] == "97.5" and forced[forced.index("--minscore") + 1] == "0"
    included = MlstAdapter.argv("mlst", MlstParams(exclude=[]), genome, out, db, supported)
    assert included[included.index("--exclude") + 1] == ""
    with pytest.raises(ValueError, match="does not offer --novel"):
        MlstAdapter.argv("mlst", MlstParams(), genome, out, db, supported - {"--novel"})


@pytest.mark.parametrize(("params", "message"), [
    (MlstParams(scheme="sau reus", minscore=0, exclude=[]), "scheme must be"),
    (MlstParams(scheme="saureus"), "minimum score 0"),
    (MlstParams(exclude=["ecoli", "ecoli"]), "twice"),
    (MlstParams(exclude=["e;coli"]), "not scheme names"),
    (MlstParams(minid=0), "minid"),
    (MlstParams(mincov=101), "mincov"),
    (MlstParams(minscore=-1), "minscore"),
    (MlstParams(threads=0), "threads"),
])
def test_invalid_parameters(params, message):
    with pytest.raises(ValueError, match=message):
        params.validate()


def test_environment_puts_the_tool_folder_first(tmp_path, monkeypatch):
    bin_dir = tmp_path / "env" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "mlst"
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setenv("PERL5LIB", "/somewhere/else")
    env = env_for(str(exe), tmp_path / "tmp")
    assert env["PATH"].split(":")[0] == str(bin_dir) and env["MLST_DBDIR"] == str(tmp_path / "env" / "db")
    assert env["PERL5LIB"] == "" and env["TMPDIR"] == str(tmp_path / "tmp")


def test_database_info_of_a_small_folder(tmp_path):
    db = tmp_path / "db"
    (db / "pubmlst" / "demo").mkdir(parents=True)
    (db / "blast").mkdir()
    (db / "VERSION.txt").write_text("2025-12-29\n")
    (db / "blast" / "mlst.fa.nsq").write_text("x")
    (db / "blast" / "mlst.fa.njs").write_text('{"files": ["mlst.fa.nsq"], "last-updated": "2026-03-11T12:33:00"}')
    (db / "pubmlst" / "demo" / "demo.txt").write_text("ST\tabc\tdef\tclonal_complex\n1\t1\t2\tCC1\n2\t1\t3\t\n")
    (db / "pubmlst" / "demo" / "demo_info.json").write_text('{"download_date": "2026-03-11", '
                                                            '"last_updated": "2025-02-01", "source": "pubmlst"}')
    info = database_info(db)
    assert info["ready"] and info["scheme_count"] == 1 and info["schemes"][0]["loci"] == ["abc", "def"]
    assert info["updated_after_open_terms"] == ["demo"] and database_version(info) == "2026-03-11"
    assert clonal_complex(db, "demo", "1") == {"available": True, "column": "clonal_complex", "value": "CC1"}
    assert clonal_complex(db, "demo", "2")["value"] is None
    (db / "blast" / "mlst.fa.nsq").unlink()
    assert not database_info(db)["ready"]


# --- The installed mlst -----------------------------------------------------------------------------------------

def _mlst() -> str:
    d = detect("mlst", refresh=True)
    if d.path is None or d.version is None:
        pytest.skip(f"mlst not available: {d.message}")
    return d.path


def _st8_from_scheme_alleles(db: Path, out: Path) -> Path:
    """A test input built from the bundled saureus allele files: ST8's seven alleles separated by 100 N. Not a genome:
    it checks the tool path end to end without a download."""
    st8 = {"arcC": 3, "aroE": 3, "glpF": 1, "gmk": 1, "pta": 4, "tpi": 4, "yqiL": 3}
    parts = []
    for locus, n in st8.items():
        text = (db / "pubmlst" / "saureus" / f"{locus}.tfa").read_text().split(">")
        seq = next("".join(r.splitlines()[1:]) for r in text if r.split("\n", 1)[0].strip() in (f"{locus}_{n}",
                                                                                              f"{locus}-{n}"))
        parts.append(seq)
    with gzip.open(out, "wt") as fh:
        fh.write(">TEST_saureus_ST8_alleles\n" + ("N" * 100).join(parts) + "\n")
    return out


def _run(exe: str, params: MlstParams, genome: Path, tmp_path: Path) -> tuple[dict, dict]:
    from arva_tools import run_command

    db = database_dir(exe)
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "tmp").mkdir()
    argv = MlstAdapter.argv(exe, params, genome, out, db, MlstAdapter.help_options(exe))
    run_command(argv, cwd=out, stderr_path=out / OUTPUTS["log"], extra_env=env_for(exe, tmp_path / "tmp"))
    rows = parse_full((out / OUTPUTS["tsv"]).read_text())
    check_json(rows, (out / OUTPUTS["json"]).read_text())
    return rows[0], parse_stderr((out / OUTPUTS["log"]).read_text())


def test_real_mlst_types_the_alleles_of_st8(tmp_path):
    exe = _mlst()
    db = database_dir(exe)
    assert help_defaults(MlstAdapter.help_text(exe)) == DEFAULTS
    row, log = _run(exe, MlstParams(threads=2), _st8_from_scheme_alleles(db, tmp_path / "st8.fna.gz"), tmp_path)
    assert (row["scheme"], row["st"], row["status"], row["score"]) == ("saureus", "8", "PERFECT", 100)
    assert log["ties"] == [] and log["excluded"] == sorted(DEFAULT_EXCLUDE)
    assert clonal_complex(db, "saureus", "8")["available"] is False


def test_real_mlst_finds_no_scheme_in_the_synthetic_genome(tmp_path):
    exe = _mlst()
    if not SYNTHETIC.is_file():
        pytest.skip("examples/synthetic-genome is not generated (scripts/make_synthetic_genome.py)")
    row, _log = _run(exe, MlstParams(), SYNTHETIC, tmp_path)
    assert (row["scheme"], row["st"], row["status"]) == (None, None, "NONE")


def test_real_mlst_rejects_an_unknown_scheme(tmp_path):
    from arva_tools import ToolExecutionError

    exe = _mlst()
    with pytest.raises(ToolExecutionError):
        _run(exe, MlstParams(scheme="no_such_scheme", minscore=0, exclude=[]), tmp_path / "x.fna", tmp_path)
    reason = MlstAdapter.failure_reason((tmp_path / "out" / OUTPUTS["log"]).read_text())
    assert reason is not None and reason.startswith("mlst stopped: ")
