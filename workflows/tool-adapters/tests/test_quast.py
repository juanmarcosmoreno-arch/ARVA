"""QUAST adapter: command construction, validation, version-dependent options, report parsing, minimap2 lookup."""
import stat
import sys
from pathlib import Path

import pytest

from arva_tools.base import ToolStatus
from arva_tools.quast import (
    CONTIG_THRESHOLDS,
    REFERENCE_OPTIONS,
    QuastAdapter,
    QuastParams,
    aligner,
    assembly_label,
    input_name,
    stages,
)

FIXTURES = Path(__file__).parent / "fixtures" / "quast"
P = Path("/job/input")
HELP = (FIXTURES / "help_5.2.0.txt").read_text()
TWO = [(P / "assembly_01.fasta", "edited"), (P / "assembly_02.fasta.gz", "perfect")]


def exe(dirpath: Path, name: str, body: str) -> Path:
    path = dirpath / name
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def fake_quast(tmp_path: Path, help_text: str = HELP) -> Path:
    (tmp_path / "help.txt").write_text(help_text)
    return exe(tmp_path, "quast.py", "import sys\nfrom pathlib import Path\n"
               "if sys.argv[1:] == ['--version']:\n    print('WARNING: x\\nQUAST v5.2.0')\n"
               f"elif sys.argv[1:] == ['--help']:\n    print(Path({str(tmp_path / 'help.txt')!r}).read_text())\n")


@pytest.fixture(scope="module")
def supported(tmp_path_factory):
    return QuastAdapter.help_options(str(fake_quast(tmp_path_factory.mktemp("quast"))))


def test_help_lists_every_option_arva_uses(supported):
    assert {"-r", "--features", "--min-contig", "--labels", "--no-plots", "--ambiguity-score"} <= supported
    assert {flag for flag, _ in REFERENCE_OPTIONS} <= supported


def test_command_without_reference_passes_every_default_explicitly(supported):
    argv = QuastAdapter.argv("quast.py", QuastParams(min_contig=500, threads=2), TWO, Path("/job/quast"), supported)
    assert argv == ["quast.py", "/job/input/assembly_01.fasta", "/job/input/assembly_02.fasta.gz",
                    "--output-dir", "/job/quast", "--threads", "2", "--min-contig", "500", "--labels", "edited,perfect",
                    "--contig-thresholds", "0,1000,5000,10000,25000,50000", "--x-for-Nx", "90", "--no-plots"]
    assert ",".join(map(str, CONTIG_THRESHOLDS)) in argv


def test_reference_options_are_explicit_but_never_the_ambiguity_score(supported):
    argv = QuastAdapter.argv("quast.py", QuastParams(), TWO[:1], Path("/out"), supported,
                             reference=P / "reference.fasta.gz", features=P / "genes.gff")
    tail = argv[argv.index("-r"):]
    assert tail == ["-r", "/job/input/reference.fasta.gz", "--min-alignment", "65", "--min-identity", "95.0",
                    "--ambiguity-usage", "one", "--extensive-mis-size", "1000", "--local-mis-size", "200",
                    "--scaffold-gap-max-size", "10000", "--unaligned-part-size", "500", "--features", "/job/input/genes.gff"]
    # QUAST switches --ambiguity-usage to "all" whenever --ambiguity-score is given, even at its default.
    assert "--ambiguity-score" not in argv
    assert argv[argv.index("--min-contig") + 1] == "500" and argv[argv.index("--threads") + 1] == "1"


@pytest.mark.parametrize("kwargs, message", [
    ({"assemblies": []}, "between 1 and 10"),
    ({"assemblies": [(P / f"assembly_{i:02d}.fasta", f"a{i}") for i in range(11)]}, "between 1 and 10"),
    ({"assemblies": [(P / "a.fasta", "x"), (P / "b.fasta", "x")]}, "must be unique"),
    ({"assemblies": [(P / "a.fasta", "Flye, 2.9")]}, "letters, digits"),
    ({"assemblies": [(P / "a.fasta", '"quoted"')]}, "letters, digits"),
    ({"assemblies": [(P / "contigs", "a")]}, "unrecognised name: contigs"),
    ({"assemblies": [(P / "my contigs.fasta", "a")]}, "unrecognised name"),
    ({"reference": P / "reference.gb"}, "unrecognised name: reference.gb"),
    ({"features": P / "genes.gff"}, "need a reference"),
    ({"features": Path("/job/x:y/genes.gff"), "reference": P / "r.fasta"}, "cannot contain ':'"),
    ({"params": QuastParams(min_contig=-1)}, "min_contig must be between 0"),
    ({"params": QuastParams(threads=0)}, "threads must be between 1"),
])
def test_invalid_requests_are_refused(supported, kwargs, message):
    args = {"params": QuastParams(), "assemblies": TWO[:1], "reference": None, "features": None, **kwargs}
    with pytest.raises(ValueError, match=message):
        QuastAdapter.argv("quast.py", args["params"], args["assemblies"], Path("/out"), supported,
                          reference=args["reference"], features=args["features"])


def test_options_missing_from_this_versions_help_are_refused(tmp_path):
    older = QuastAdapter.help_options(str(fake_quast(tmp_path, HELP.replace("--unaligned-part-size", "--unaligned-xx"))))
    QuastAdapter.argv("quast.py", QuastParams(), TWO[:1], Path("/out"), older)
    with pytest.raises(ValueError, match="does not offer --unaligned-part-size"):
        QuastAdapter.argv("quast.py", QuastParams(), TWO[:1], Path("/out"), older, reference=P / "r.fasta")


def test_labels_and_input_names_are_safe_for_quast():
    assert assembly_label("Flye", "2.9.3", "3f9c2a1b-0000-4000-8000-000000000000") == "Flye 2.9.3 3f9c2a1b"
    assert assembly_label("Odd,\"name'", "1.0", "abcdef0123") == "Odd_name_ 1.0 abcdef01"
    assert assembly_label("", "", "abcdef0123") == "assembly abcdef01"
    assert input_name("assembly", 3, compressed=True) == "assembly_03.fasta.gz"
    assert input_name("reference", 1, compressed=False) == "reference.fasta"


def test_both_reports_are_read_by_field_name_and_agree():
    for run in ("reference", "no_reference"):
        report = QuastAdapter.parse_report((FIXTURES / run / "report.tsv").read_text())
        assert report == QuastAdapter.parse_transposed_report((FIXTURES / run / "transposed_report.tsv").read_text())
        assert report["labels"] == ["edited", "perfect"]
    values = {r["field"]: r["values"] for r in report["rows"]}  # no reference
    assert "Genome fraction (%)" not in values and "Reference length" not in values
    ref = {r["field"]: r["values"] for r in QuastAdapter.parse_report((FIXTURES / "reference" / "report.tsv").read_text())["rows"]}
    assert ref["# contigs (>= 0 bp)"] == [8, 2] and ref["# contigs"] == [6, 2]
    assert ref["Total length (>= 0 bp)"] == [338_399, 315_000] and ref["Total length"] == [337_500, 315_000]
    assert (ref["N50"], ref["L50"], ref["N90"], ref["L90"]) == ([140_000, 300_000], [2, 1], [20_000, 300_000], [3, 1])
    assert ref["GC (%)"] == [49.45, 49.62] and ref["auN"] == [135_790.4, 286_428.6]
    assert ref["# misassemblies"] == [1, 0] and ref["Misassembled contigs length"] == [20_000, 0]
    assert ref["# unaligned contigs"] == [{"full": 1, "partial": 0}, {"full": 0, "partial": 0}]
    assert ref["Unaligned length"] == [1950, 0] and ref["Genome fraction (%)"] == [100.0, 99.683]
    assert ref["# N's per 100 kbp"] == [14.81, 0.0] and ref["# mismatches per 100 kbp"] == [0.89, 0.0]
    assert ref["Duplication ratio"] == [1.065, 1.0] and ref["NGA50"] == [160_000, 299_000]
    # QUAST's own order is kept.
    fields = [r["field"] for r in report["rows"]]
    assert fields[0] == "# contigs (>= 0 bp)" and fields[-1] == "# N's per 100 kbp"


def test_values_that_are_not_numbers_are_kept_as_text_or_none():
    report = QuastAdapter.parse_report("Assembly\ta\tb\nN50\t-\t12\nOdd\tn/a\t1.5\n")
    assert report["rows"] == [{"field": "N50", "values": [None, 12]}, {"field": "Odd", "values": ["n/a", 1.5]}]


@pytest.mark.parametrize("text, message", [
    ("", "not the 'Assembly' header"),
    ("Contig\ta\nN50\t1\n", "not the 'Assembly' header"),
    ("Assembly\ta\ta\nN50\t1\t2\n", "repeated assembly labels"),
    ("Assembly\ta\tb\nN50\t1\n", "has 1 values for 2 assemblies"),
    ("Assembly\ta\nN50\t1\nN50\t2\n", "repeated field 'N50'"),
    ("Assembly\ta\n", "no metrics"),
])
def test_malformed_reports_are_rejected(text, message):
    with pytest.raises(ValueError, match=message):
        QuastAdapter.parse_report(text)


def test_malformed_transposed_report_is_rejected():
    with pytest.raises(ValueError, match="line 2 has 2 columns"):
        QuastAdapter.parse_transposed_report("Assembly\tN50\tL50\na\t1\n")


def test_console_gives_versions_warnings_stages_and_skipped_assemblies():
    c = QuastAdapter.parse_console((FIXTURES / "reference" / "console.log").read_text())
    assert (c["quast_version"], c["python_version"]) == ("5.2.0", "3.12.3")
    # The minimap2 warning appears once per assembly and once more; it is kept once.
    assert c["warnings"] == ["Python locale settings can't be changed",
                             "Version of installed minimap2 differs from its version in the QUAST package (2.24). "
                             "Please make sure that you use an actual version of software."]
    assert c["stages_seen"] == list(stages(reference=True)) and c["skipped"] == [] and c["errors"] == []
    n = QuastAdapter.parse_console((FIXTURES / "no_reference" / "console.log").read_text())
    assert n["stages_seen"] == list(stages(reference=False)) == ["basic_stats", "visual_summaries"]
    s = QuastAdapter.parse_console((FIXTURES / "failures" / "skipped.console.log").read_text())
    assert s["skipped"] == [{"label": "short", "min_contig": 500}]
    assert QuastAdapter.stage("Running Contig analyzer...\n") == "contig_analyzer"
    assert QuastAdapter.stage("  Running Contig analyzer...") == "contig_analyzer"
    assert QuastAdapter.stage("Running BWA...") is None


def test_aligner_is_read_from_quasts_alignment_log():
    a = QuastAdapter.parse_aligner((FIXTURES / "reference" / "contigs_report_edited.stderr").read_text())
    assert a == {"name": "minimap2", "executable": "/usr/bin/minimap2", "version": "2.26-r1175"}
    assert QuastAdapter.parse_aligner("nothing here") is None


def test_failure_reasons_come_from_quasts_own_errors():
    none = (FIXTURES / "failures" / "none_correct.console.log").read_text()
    assert "no contig at least as long as the minimum contig length" in QuastAdapter.failure_reason(none, 4)
    bad = (FIXTURES / "failures" / "non_acgtn.console.log").read_text()
    assert QuastAdapter.failure_reason(bad, 4).startswith("QUAST refused /job/input/assembly_01.fasta:")
    reason = QuastAdapter.failure_reason(bad, 4, {"/job/input/assembly_01.fasta": "Flye 2.9.3 abcdef01"})
    assert reason.startswith("QUAST refused Flye 2.9.3 abcdef01: it accepts only A, C, G, T, N")
    assert QuastAdapter.failure_reason("ERROR! Reference file r.fasta is empty", 1).startswith(
        "QUAST could not read the reference")
    assert QuastAdapter.failure_reason("ERROR! Something else", 2) == "QUAST failed: Something else"
    assert "out of memory" in QuastAdapter.failure_reason("", -9)
    assert QuastAdapter.failure_reason("Traceback", 1) is None


def test_params_bounds():
    QuastParams(min_contig=0).validate()
    QuastParams(min_contig=1_000_000, threads=256).validate()
    with pytest.raises(ValueError):
        QuastParams(min_contig=1_000_001).validate()


def _minimap2(dirpath: Path, version: str) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    return exe(dirpath, "minimap2", f"print({version!r})")


def test_minimap2_is_found_the_way_quast_looks_for_it(tmp_path, monkeypatch):
    quast = fake_quast(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert aligner(str(quast)) == {"provided_by": "missing", "found": None, "version": None}
    old = _minimap2(tmp_path / "old", "2.17-r941")
    monkeypatch.setenv("PATH", str(old.parent))
    assert aligner(str(quast)) == {"provided_by": "missing", "found": str(old), "version": "2.17-r941"}
    new = _minimap2(tmp_path / "new", "2.24-r1122")
    monkeypatch.setenv("PATH", f"{new.parent}:{old.parent}")
    assert aligner(str(quast)) == {"provided_by": "path", "executable": str(new), "version": "2.24-r1122"}
    # A compiled copy inside QUAST's own package is used first, as QUAST itself does.
    libs = tmp_path / "site" / "quast_libs"
    (libs / "minimap2").mkdir(parents=True)
    (libs / "__init__.py").write_text("")
    bundled = _minimap2(libs / "minimap2", "2.24-r1122")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))
    assert aligner(str(quast)) == {"provided_by": "quast_bundled", "executable": str(bundled), "version": "2.24-r1122"}


def test_detection_notes_a_missing_minimap2_without_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVA_TOOL_QUAST", str(fake_quast(tmp_path)))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    d = QuastAdapter().detect()
    assert (d.status, d.version, d.version_validated, d.reason) == (ToolStatus.available, "5.2.0", True,
                                                                    "minimap2_missing")
    assert "Evaluation without a reference works" in d.message
