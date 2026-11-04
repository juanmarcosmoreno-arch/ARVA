"""Flye adapter: command construction, validation, version-dependent options, output parsing, helpers."""
import math
import os
import stat
import sys
from pathlib import Path

import pytest

from arva_tools.base import ToolStatus
from arva_tools.flye import (
    STAGES,
    FlyeAdapter,
    FlyeParams,
    pooled_error_rate,
    read_checkpoint,
    read_link_name,
    samtools_helper,
    suggest_read_type,
)

FIXTURES = Path(__file__).parent / "fixtures" / "flye"
P = Path("/data")
HELP = (FIXTURES / "help_2.9.3.txt").read_text()
SUPPORTED_293 = frozenset(
    {"--pacbio-raw", "--pacbio-corr", "--pacbio-hifi", "--nano-raw", "--nano-corr", "--nano-hq", "--genome-size",
     "--out-dir", "--threads", "--iterations", "--min-overlap", "--asm-coverage", "--read-error", "--meta",
     "--keep-haplotypes", "--no-alt-contigs", "--scaffold"}
)


def exe(dirpath: Path, name: str, body: str) -> Path:
    path = dirpath / name
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_default_command_passes_threads_and_iterations_explicitly():
    argv = FlyeAdapter.argv("flye", FlyeParams(read_type="nano-hq", threads=4), [P / "01_r.fastq.gz"], P / "out",
                            SUPPORTED_293)
    assert argv == ["flye", "--nano-hq", "/data/01_r.fastq.gz", "--out-dir", "/data/out", "--threads", "4",
                    "--iterations", "1"]


def test_every_option_reaches_the_command():
    params = FlyeParams(read_type="pacbio-hifi", genome_size_bp=5_000_000, genome_size_basis="entered", iterations=3,
                        min_overlap=5000, asm_coverage=40, read_error=0.03, keep_haplotypes=True,
                        no_alt_contigs=True, scaffold=True, threads=2)
    argv = FlyeAdapter.argv("flye", params, [P / "01_a.fastq", P / "02_b.fq.gz"], P / "out", SUPPORTED_293)
    assert argv[:4] == ["flye", "--pacbio-hifi", "/data/01_a.fastq", "/data/02_b.fq.gz"]
    joined = " ".join(argv)
    for expected in ("--genome-size 5000000", "--iterations 3", "--min-overlap 5000", "--asm-coverage 40",
                     "--read-error 0.03", "--keep-haplotypes", "--no-alt-contigs", "--scaffold", "--threads 2"):
        assert expected in joined
    assert "--meta" not in argv
    meta = FlyeParams(read_type="nano-raw", meta=True, iterations=0)
    assert "--meta" in FlyeAdapter.argv("flye", meta, [P / "01_a.fastq"], P / "out", SUPPORTED_293)


def test_options_missing_from_this_versions_help_are_refused():
    older = SUPPORTED_293 - {"--no-alt-contigs"}
    params = FlyeParams(read_type="nano-hq", no_alt_contigs=True)
    with pytest.raises(ValueError, match=r"does not offer --no-alt-contigs \(not in its --help\)"):
        FlyeAdapter.argv("flye", params, [P / "01_a.fastq"], P / "out", older)
    FlyeAdapter.argv("flye", FlyeParams(read_type="nano-hq"), [P / "01_a.fastq"], P / "out", older)


@pytest.mark.parametrize("bad, message", [
    (dict(read_type="nanopore"), "read_type must be one of"),
    (dict(iterations=11), "iterations must be between 0 and 10"),
    (dict(min_overlap=999), "min_overlap must be between 1,000 and 10,000"),
    (dict(asm_coverage=40), "asm_coverage requires genome_size_bp"),
    (dict(asm_coverage=40, genome_size_bp=5_000_000, genome_size_basis="entered", meta=True),
     "cannot be combined with meta"),
    (dict(read_type="nano-raw", read_error=0.03), "read_error can only be used with"),
    (dict(read_error=1.0), "read_error is a fraction"),
    (dict(threads=0), "threads must be between 1 and 128"),
    (dict(genome_size_bp=999, genome_size_basis="entered"), "genome_size_bp must be between"),
    (dict(genome_size_bp=5_000_000), "a genome size needs its basis"),
    (dict(genome_size_bp=5_000_000, genome_size_basis="reads_over_depth"), "assumed_depth_x is required"),
    (dict(genome_size_bp=5_000_000, genome_size_basis="entered", assumed_depth_x=50), "assumed_depth_x is required"),
    (dict(genome_size_basis="entered"), "none was given"),
])
def test_validation(bad, message):
    with pytest.raises(ValueError, match=message):
        FlyeParams(**{"read_type": "nano-hq", **bad}).validate()


def test_paths_with_spaces_and_unsafe_names_are_refused():
    params = FlyeParams(read_type="nano-hq")
    with pytest.raises(ValueError, match="spaces"):
        FlyeAdapter.argv("flye", params, [Path("/my data/01_a.fastq")], P / "out", SUPPORTED_293)
    for name in ("reads.bam", "-x.fastq", "a.fasta", "a;b.fastq"):
        with pytest.raises(ValueError, match="read file name"):
            FlyeAdapter.argv("flye", params, [P / name], P / "out", SUPPORTED_293)
    with pytest.raises(ValueError, match="at least one read file"):
        FlyeAdapter.argv("flye", params, [], P / "out", SUPPORTED_293)


def test_link_names_carry_the_extension_flye_needs():
    assert read_link_name(1, "run 1 pass.FQ.GZ", compressed=True) == "01_run_1_pass.fastq.gz"
    assert read_link_name(12, "reads.fastq", compressed=False) == "12_reads.fastq"
    assert read_link_name(3, "../..", compressed=False) == "03_reads.fastq"


def test_stages_depend_on_polishing():
    assert FlyeParams(read_type="nano-hq").stages() == (
        "configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize")
    assert "polishing" not in FlyeParams(read_type="nano-hq", iterations=0).stages()
    assert FlyeAdapter.stage("[2026-10-28 13:37:13] INFO: >>>STAGE: consensus") == "consensus"
    assert FlyeAdapter.stage("[2026-10-28 13:37:13] INFO: Running Minimap2") is None


def test_help_options_are_read_from_the_installed_flye(tmp_path):
    fake = exe(tmp_path, "flye", f"import sys; sys.stdout.write({HELP!r})")
    options = FlyeAdapter.help_options(str(fake))
    assert SUPPORTED_293 <= options and "--deterministic" in options


def test_assembly_info_from_real_runs():
    rows = FlyeAdapter.parse_assembly_info((FIXTURES / "synthetic150_assembly_info.txt").read_text())
    assert rows == [
        {"name": "contig_1", "length": 150001, "coverage": 52.0, "circular": True, "repeat": False, "multiplicity": 1,
         "alt_group": None, "graph_path": "1"},
        {"name": "contig_2", "length": 15000, "coverage": 95.0, "circular": True, "repeat": False, "multiplicity": 2,
         "alt_group": None, "graph_path": "2"},
    ]
    unresolved = FlyeAdapter.parse_assembly_info((FIXTURES / "synthetic60_assembly_info.txt").read_text())
    assert [(r["name"], r["repeat"], r["alt_group"], r["graph_path"]) for r in unresolved] == [
        ("contig_4", True, "2", "*,4,*"), ("contig_1", False, None, "1"), ("contig_3", True, "2", "*,3,*"),
        ("contig_2", False, None, "2")]


HEADER = "#seq_name\tlength\tcov.\tcirc.\trepeat\tmult.\talt_group\tgraph_path\n"


@pytest.mark.parametrize("text, message", [
    ("", "no '#seq_name' header"),
    ("#seq_name\tlength\n", "lacks the column"),
    (HEADER, "lists no contigs"),
    (HEADER + "c1\t10\t5\tY\tN\t1\t*\n", "line 2: 7 columns"),
    (HEADER + "c1\tten\t5\tY\tN\t1\t*\t1\n", "line 2: length, cov. and mult. must be numbers"),
    (HEADER + "c1\t10\t5\tyes\tN\t1\t*\t1\n", "circ. must be Y or N"),
    (HEADER + "c1\t10\t5\tY\tN\t1\t*\t1\nc1\t10\t5\tY\tN\t1\t*\t1\n", "line 3: missing or repeated"),
    (HEADER + "c1\t0\t5\tY\tN\t1\t*\t1\n", "impossible length"),
])
def test_assembly_info_is_rejected_when_malformed(text, message):
    with pytest.raises(ValueError, match=message):
        FlyeAdapter.parse_assembly_info(text)


def test_log_values_flye_chose_are_recorded():
    log = FlyeAdapter.parse_log((FIXTURES / "synthetic150_flye.log").read_text())
    assert (log["total_read_length"], log["reads_n50"], log["reads_n90"], log["min_overlap"]) == (
        8_967_348, 8591, 4001, 4000)
    assert (log["total_length"], log["fragments"], log["largest_fragment"], log["mean_coverage"]) == (
        165_001, 2, 150_001, 55)
    assert log["alignment_error_rate"] == {"consensus": 0.071531, "polishing": 0.04064}
    assert log["stages_seen"] == ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"]
    assert log["warnings"] == []
    warned = FlyeAdapter.parse_log("Input genome size: 100000000\n[x] root: WARNING: Expected read coverage is 0, the "
                                   "assembly is not guaranteed to be optimal in this setting. Are you sure?\n")
    assert warned["input_genome_size"] == 100_000_000 and warned["warnings"][0].startswith("Expected read coverage is 0")


def test_failure_reasons_from_real_logs():
    reason = FlyeAdapter.failure_reason((FIXTURES / "short_reads.stderr.log").read_text(), 1)
    assert reason.startswith("Flye found no read longer than the minimum overlap (No reads above minimum length "
                             "threshold (1000))")
    reason = FlyeAdapter.failure_reason((FIXTURES / "no_contigs.stderr.log").read_text(), 1)
    assert reason.startswith("Flye could not assemble the reads during the contigger stage: No contigs were assembled")
    reason = FlyeAdapter.failure_reason((FIXTURES / "no_flye_samtools.stderr.log").read_text(), 1)
    assert reason.startswith("Flye could not run flye-samtools during the repeat stage")
    oom = ">>>STAGE: assembly\nERROR: Looks like the system ran out of memory\n"
    assert FlyeAdapter.failure_reason(oom, 1).startswith("Flye ran out of memory during the assembly stage")
    assert FlyeAdapter.failure_reason(">>>STAGE: repeat\n", -9).startswith("Flye ran out of memory")
    assert FlyeAdapter.failure_reason("ERROR: Can't open x\nERROR: Pipeline aborted\n", 1) == "Flye failed: Can't open x"
    assert FlyeAdapter.failure_reason("Traceback ...", 1) is None


def test_failures_carry_a_code_and_parameters_for_the_interface():
    """Known reasons are coded (job.error.<code> in the interface) with the stage and Flye's own error line, so the
    Spanish interface does not show them in English (registro de prueba, item 28)."""
    oom = ">>>STAGE: assembly\nERROR: Looks like the system ran out of memory\n"
    message, code, params = FlyeAdapter.failure(oom, 1)
    assert code == "flye_out_of_memory" and params == {"stage": "assembly", "need_gb": 9}
    assert "about 9 GB whatever the reads" in message
    assert FlyeAdapter.failure("", -9)[1:] == ("flye_out_of_memory", {"stage": "", "need_gb": 9})
    short = FlyeAdapter.failure((FIXTURES / "short_reads.stderr.log").read_text(), 1)
    assert short[1] == "flye_no_long_reads" and short[2]["detail"] == "No reads above minimum length threshold (1000)"
    none = FlyeAdapter.failure((FIXTURES / "no_contigs.stderr.log").read_text(), 1)
    assert none[1:] == ("flye_nothing_assembled", {"stage": "contigger", "detail": none[2]["detail"]})
    assert none[2]["detail"].startswith("No contigs were assembled")
    assert FlyeAdapter.failure((FIXTURES / "no_flye_samtools.stderr.log").read_text(), 1)[1:] == (
        "flye_samtools_not_run", {"stage": "repeat"})
    assert FlyeAdapter.failure("ERROR: Can't open x\n", 1)[1:] == ("flye_error", {"stage": "", "detail": "Can't open x"})
    assert FlyeAdapter.failure("Traceback ...", 1) is None


def test_help_of_flye_2_9_6_lists_every_option_arva_offers(tmp_path):
    """help_2.9.6.txt is the real `flye --help` of the Flye 2.9.6 ARVA ships; every optional option the dialog
    offers (app.services.flye.OPTIONAL_OPTIONS) is in it, --asm-coverage and --genome-size included."""
    help_296 = (FIXTURES / "help_2.9.6.txt").read_text()
    fake = exe(tmp_path, "flye", f"import sys; sys.stdout.write({help_296!r})")
    options = FlyeAdapter.help_options(str(fake))
    assert {"--genome-size", "--min-overlap", "--asm-coverage", "--read-error", "--meta", "--keep-haplotypes",
            "--no-alt-contigs", "--scaffold"} <= options


def fake_flye(dirpath: Path) -> Path:
    return exe(dirpath, "flye", "import sys; print('2.9.3-b1797') if '--version' in sys.argv else None")


def test_samtools_helper_and_detection(tmp_path, monkeypatch):
    flye_dir, other = tmp_path / "flye-bin", tmp_path / "other-bin"
    flye_dir.mkdir()
    other.mkdir()
    flye = fake_flye(flye_dir)
    monkeypatch.setenv("ARVA_TOOL_FLYE", str(flye))
    monkeypatch.delenv("ARVA_TOOL_SAMTOOLS", raising=False)
    monkeypatch.delenv("ARVA_TOOLS_PATH", raising=False)
    monkeypatch.setenv("PATH", str(other))

    assert samtools_helper(str(flye))["provided_by"] == "missing"
    d = FlyeAdapter().detect()
    assert (d.status, d.reason) == (ToolStatus.failed, "samtools_missing") and "Install samtools" in d.message

    samtools = exe(other, "samtools", "print('samtools 1.19.2')")
    assert samtools_helper(str(flye)) == {"provided_by": "arva_link", "samtools": str(samtools), "path_prepend": None}
    d = FlyeAdapter().detect()
    assert (d.status, d.version, d.version_validated, d.reason) == (ToolStatus.available, "2.9.3", True,
                                                                    "samtools_linked")
    assert "links it to" in d.message

    beside = exe(flye_dir, "flye-samtools", "")
    assert samtools_helper(str(flye)) == {"provided_by": "installation", "samtools": str(beside),
                                          "path_prepend": str(flye_dir)}
    # Flye's own folder comes first (Bioconda's flye-samtools, flye-modules and flye-minimap2 sit next to flye), so
    # another installation's programs on PATH are not mixed with this Flye.
    on_path = exe(other, "flye-samtools", "")
    assert samtools_helper(str(flye)) == {"provided_by": "installation", "samtools": str(beside),
                                          "path_prepend": str(flye_dir)}
    assert FlyeAdapter().detect().reason is None
    beside.unlink()
    assert samtools_helper(str(flye)) == {"provided_by": "installation", "samtools": str(on_path), "path_prepend": None}
    assert FlyeAdapter().detect().reason is None


def test_pooled_error_rate_weights_files_by_bases():
    assert pooled_error_rate([]) is None
    assert pooled_error_rate([(20.0, 100)]) == pytest.approx(0.01)
    assert pooled_error_rate([(10.0, 100), (20.0, 300)]) == pytest.approx((0.1 * 100 + 0.01 * 300) / 400)


@pytest.mark.parametrize("platform, error, models, pacbio, value, basis", [
    ("nanopore", 0.02, [], [], "nano-hq", "error_at_most_3_percent"),
    ("nanopore", 0.03, [], [], "nano-hq", "error_at_most_3_percent"),
    ("nanopore", 0.04, [], [], "nano-hq", "error_3_to_5_percent"),
    ("nanopore", 0.05, [], [], "nano-hq", "error_3_to_5_percent"),
    ("nanopore", 0.08, [], [], "nano-raw", "error_above_5_percent"),
    ("nanopore", None, ["dna_r10.4.1_e8.2_400bps_sup@v4.2.0"], [], "nano-hq", "sup_basecall_model"),
    ("nanopore", None, ["dna_r9.4.1_450bps_hac"], [], None, "no_quality_or_model"),
    ("pacbio", 0.001, [], ["ccs"], "pacbio-hifi", "quality_at_least_q20"),
    ("pacbio", None, [], ["ccs"], "pacbio-hifi", "ccs_read_names"),
    ("pacbio", 0.1, [], ["subread"], "pacbio-raw", "subread_read_names"),
    ("pacbio", None, [], [], None, "no_quality_or_read_names"),
    (None, 0.01, [], [], None, "platform_unknown"),
])
def test_read_type_suggestion_is_a_labelled_heuristic(platform, error, models, pacbio, value, basis):
    s = suggest_read_type(platform, error, models, pacbio)
    assert (s["value"], s["basis"], s["heuristic"]) == (value, basis, True)


def test_read_type_suggestion_notes():
    q20 = suggest_read_type("nanopore", 0.008, [], [])
    assert q20["q20_read_error_note"] is True and q20["mean_base_quality"] == pytest.approx(-10 * math.log10(0.008))
    low = suggest_read_type("nanopore", 0.09, ["dna_r10.4.1_e8.2_400bps_sup@v4.2.0"], [])
    assert (low["value"], low["sup_model_but_low_quality"]) == ("nano-raw", True)


def test_read_type_suggestion_adds_flyes_read_error_only_for_3_to_5_percent():
    # Flye 2.9.6 USAGE.md: "--nano-hq --read-error 0.05" for <5% error; R10 (3%) parameters are --nano-hq's default.
    assert suggest_read_type("nanopore", 0.04, [], [])["read_error"] == 0.05
    assert suggest_read_type("nanopore", 0.025, [], [])["read_error"] is None
    assert suggest_read_type("nanopore", 0.08, [], [])["read_error"] is None
    assert suggest_read_type("pacbio", 0.001, [], ["ccs"])["read_error"] is None


def test_a_samtools_override_that_does_not_exist_counts_as_missing(tmp_path, monkeypatch):
    flye = fake_flye(tmp_path)
    monkeypatch.setenv("ARVA_TOOL_FLYE", str(flye))
    monkeypatch.setenv("PATH", os.defpath)
    monkeypatch.setenv("ARVA_TOOL_SAMTOOLS", str(tmp_path / "missing"))
    assert FlyeAdapter().detect().reason == "samtools_missing"


def test_resume_reuses_the_command_and_needs_the_flag_in_help():
    params = FlyeParams(read_type="nano-hq", threads=2)
    fresh = FlyeAdapter.argv("flye", params, [P / "01_r.fastq.gz"], P / "out", SUPPORTED_293 | {"--resume"})
    resumed = FlyeAdapter.argv("flye", params, [P / "01_r.fastq.gz"], P / "out", SUPPORTED_293 | {"--resume"},
                               resume=True)
    assert resumed == [*fresh, "--resume"]
    assert "--resume  " in HELP  # Flye 2.9.3's own --help lists it
    with pytest.raises(ValueError, match="does not offer --resume"):
        FlyeAdapter.argv("flye", params, [P / "01_r.fastq.gz"], P / "out", SUPPORTED_293, resume=True)


def test_a_resumed_log_counts_each_stage_once():
    """Recorded with Flye 2.9.3: a run killed during repeat (synthetic genome, 2 threads), moved and resumed; Flye
    appends the resumed run to the same flye.log."""
    log = FlyeAdapter.parse_log((FIXTURES / "resumed_from_repeat_flye.log").read_text())
    assert log["stages_seen"] == list(STAGES) and log["resumed_at"] == ["repeat"]
    assert log["min_overlap"] == 4000 and log["fragments"] == 2
    assert "resumed_at" not in FlyeAdapter.parse_log((FIXTURES / "synthetic150_flye.log").read_text())


def test_checkpoints_need_a_completed_stage_after_configure(tmp_path):
    stages = FlyeParams(read_type="nano-hq").stages()

    def kept(stage_name, dirs=(), text=None):
        out = tmp_path / stage_name / "flye"
        out.mkdir(parents=True)
        for d in dirs:
            (out / d).mkdir()
        (out / "params.json").write_text(text or f'{{"pipeline_version": 3, "stage_name": "{stage_name}"}}')
        return out

    assert read_checkpoint(kept("assembly", ["00-assembly"]), stages) is None
    assert read_checkpoint(kept("repeat", ["00-assembly", "10-consensus", "20-repeat"]), stages) == {
        "resume_stage": "repeat", "completed_stages": ["configure", "assembly", "consensus"]}
    assert read_checkpoint(kept("contigger", ["00-assembly", "20-repeat"]), stages) is None
    assert read_checkpoint(kept("polishing", ["00-assembly"], text="{not json"), stages) is None
    no_polishing = FlyeParams(read_type="nano-hq", iterations=0).stages()
    done = ["00-assembly", "10-consensus", "20-repeat", "30-contigger"]
    assert read_checkpoint(kept("finalize", done), no_polishing)["completed_stages"] == list(no_polishing[:-1])
    assert read_checkpoint(tmp_path / "missing", stages) is None


def test_only_runs_stopped_from_outside_are_resumable():
    assert FlyeAdapter.resumable_failure("", -9) and FlyeAdapter.resumable_failure("", 137)
    assert FlyeAdapter.resumable_failure("ERROR: Looks like the system ran out of memory", 1)
    no_contigs = (FIXTURES / "no_contigs.stderr.log").read_text()
    assert not FlyeAdapter.resumable_failure(no_contigs, 1) and not FlyeAdapter.resumable_failure("", None)


def test_memory_estimate_scales_flyes_documented_e_coli_figure():
    from arva_tools.flye import MEMORY_REFERENCE_BASES, SUGGESTED_ASM_COVERAGE, memory_estimate

    assert MEMORY_REFERENCE_BASES == 230_000_000 and SUGGESTED_ASM_COVERAGE == 40
    # The documented case itself: 2 GB for 50x of 4.6 Mb (the scaled part; the fixed k-mer floor is larger).
    assert memory_estimate(230_000_000, 16)["scaled_gb"] == 2.0
    # Reads that would need more than the floor: 2.3 Gb (20 GB scaled) in 16 GB, genome 5 Mb (460x).
    est = memory_estimate(2_300_000_000, 16, genome_size_bp=5_000_000)
    assert est["verdict"] == "may_not_fit" and est["estimate_gb"] == 20.0
    # --asm-coverage 40 cuts the reads to 200 Mb (1.74 GB scaled), but never below the k-mer floor.
    assert est["suggestion"] == {"asm_coverage": 40, "needs_genome_size": False, "genome_size_bp": 5_000_000,
                                 "estimate_gb": 8.6, "coverage_x": 460.0}
    # 40x of 60 Mb (2.4 Gb) is more than the 2.3 Gb of reads: --asm-coverage would not reduce them, so no suggestion.
    big = memory_estimate(2_300_000_000, 16, genome_size_bp=60_000_000)
    assert big["verdict"] == "may_not_fit" and big["suggestion"] is None
    with_asm = memory_estimate(2_300_000_000, 16, asm_coverage=50, genome_size_bp=5_000_000)
    assert with_asm["verdict"] == "fits" and with_asm["bases_used"] == 250_000_000 and with_asm["suggestion"] is None
    assert with_asm["estimate_gb"] == 8.6 and with_asm["scaled_gb"] == 2.17
    # No genome size: the suggestion says one is needed; --meta cannot take --asm-coverage, so none is suggested.
    assert memory_estimate(2_300_000_000, 16)["suggestion"]["needs_genome_size"] is True
    assert memory_estimate(2_300_000_000, 16, meta=True)["suggestion"] is None
    assert memory_estimate(None, 16)["verdict"] == "unknown"
    assert memory_estimate(413_000_000, None)["verdict"] == "unknown"
    # asm_coverage above the reads' coverage reads every base.
    assert memory_estimate(100_000_000, 16, asm_coverage=500, genome_size_bp=2_800_000)["bases_used"] == 100_000_000


def test_memory_estimate_has_flyes_fixed_kmer_counter_floor():
    """Flye 2.9.6 allocates a flat k-mer counter of 4^17 / 2 bytes = 8 GiB whatever the reads (vertex_index.cpp), so
    the estimate is never below about 8.6 GB, and a container with less memory cannot run Flye at all: --asm-coverage
    does not help, so it is not suggested."""
    from arva_tools.flye import KMER_COUNTER_FLOOR, memory_estimate

    assert KMER_COUNTER_FLOOR["gb"] == 8.6 and KMER_COUNTER_FLOOR["kmer_size"] == 17
    assert 4 ** KMER_COUNTER_FLOOR["kmer_size"] // 2 == KMER_COUNTER_FLOOR["counter_gib"] * 1024 ** 3
    # The user's Mac: 413 Mb of filtered reads (147.5x of 2.8 Mb) and 5.9 GB in the Docker container. ARVA used to
    # say 3.59 GB (0.97 GB with --asm-coverage 40) "fits"; Flye was killed both ways.
    mac = memory_estimate(413_000_000, 5.9, genome_size_bp=2_800_000)
    assert mac["verdict"] == "below_floor" and mac["estimate_gb"] == 8.6 and mac["scaled_gb"] == 3.59
    assert mac["suggestion"] is None
    with_asm = memory_estimate(413_000_000, 5.9, asm_coverage=40, genome_size_bp=2_800_000)
    assert with_asm["verdict"] == "below_floor" and with_asm["scaled_gb"] == 0.97 and with_asm["estimate_gb"] == 8.6
    # The floor does not depend on the reads: known before any statistics exist.
    assert memory_estimate(None, 5.9)["verdict"] == "below_floor"
    # Enough memory for the floor: small reads fit.
    assert memory_estimate(413_000_000, 15.7, genome_size_bp=2_800_000)["verdict"] == "fits"


def test_memory_estimate_is_tight_within_a_gigabyte_of_the_floor():
    """The container's memory is shared with ARVA's database, queue, API and worker, and the measured peak (8787 MB)
    is above the floor: a container with less than the floor plus FLOOR_HEADROOM_GB is "tight", not "fits"."""
    from arva_tools.flye import FLOOR_HEADROOM_GB, memory_estimate

    assert FLOOR_HEADROOM_GB == 1.0
    tight = memory_estimate(413_000_000, 8.7)
    assert tight["verdict"] == "tight" and tight["suggestion"] is None and tight["floor_headroom_gb"] == 1.0
    assert memory_estimate(413_000_000, 8.6)["verdict"] == "tight"
    assert memory_estimate(413_000_000, 9.6)["verdict"] == "fits"
    # Reads that need more than the container are "may not fit" whatever the headroom.
    assert memory_estimate(1_100_000_000, 9.0)["verdict"] == "may_not_fit"


def test_memory_estimate_compares_a_batch_share_with_the_reads_part_only():
    """A batch reserves memory per job (other jobs may run beside it). Flye allocates its fixed k-mer table whatever
    that share is, so the floor is decided by the container's memory, and the share is compared with the part of the
    estimate that depends on the reads."""
    from arva_tools.flye import memory_estimate

    # 11.7 GB container, 8 GB per job: few reads fit (the 8.6 GB floor is within the container).
    small = memory_estimate(413_000_000, 8, genome_size_bp=2_800_000, container_gb=11.7)
    assert small["verdict"] == "fits" and small["available_gb"] == 8 and small["container_gb"] == 11.7
    # 2.5 Gb of reads of a 5 Mb genome (about 21.7 GB) do not fit; --asm-coverage 40 (200 Mb, about 1.74 GB) would.
    big = memory_estimate(2_500_000_000, 8, genome_size_bp=5_000_000, container_gb=11.7)
    assert big["verdict"] == "may_not_fit" and big["suggestion"]["estimate_gb"] == 8.6
    after = memory_estimate(2_500_000_000, 8, asm_coverage=40, genome_size_bp=5_000_000, container_gb=11.7)
    assert after["verdict"] == "fits" and after["scaled_gb"] == 1.74
    # Reads whose scaled part fits the container but not the share.
    assert memory_estimate(1_000_000_000, 4, container_gb=11.7)["verdict"] == "may_not_fit"
    # Below the floor only when the container itself is.
    assert memory_estimate(413_000_000, 4, container_gb=5.9)["verdict"] == "below_floor"
    # A share larger than the container is capped by it.
    assert memory_estimate(413_000_000, 64, container_gb=11.7)["available_gb"] == 11.7
