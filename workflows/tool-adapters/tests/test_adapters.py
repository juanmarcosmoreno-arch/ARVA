"""Command construction and output parsing for each adapter."""
import json
import math
import zipfile
from pathlib import Path

import pytest

from arva_tools.fastp import FastpAdapter, FastpParams
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams, identity_to_phred
from arva_tools.multiqc import ENVIRONMENT as MULTIQC_ENV
from arva_tools.multiqc import MultiqcAdapter, ReportInput, report_text, staged_name
from arva_tools.seqkit import SeqkitAdapter

P = Path("/data")


def test_fastp_defaults_are_explicit_in_command():
    argv = FastpAdapter.argv("fastp", FastpParams(), P / "r1.fq.gz", P / "o1.fq.gz", P / "f.json", P / "f.html",
                             in2=P / "r2.fq.gz", out2=P / "o2.fq.gz")
    joined = " ".join(argv)
    for expected in ("--in2 /data/r2.fq.gz", "--qualified_quality_phred 15", "--unqualified_percent_limit 40",
                     "--n_base_limit 5", "--average_qual 0", "--length_required 15", "--detect_adapter_for_pe",
                     "--thread 3"):
        assert expected in joined
    assert "--dedup" not in argv and "--disable_trim_poly_g" not in argv


def test_fastp_options_toggle():
    params = FastpParams(adapter_trimming=False, quality_filtering=False, length_filtering=False,
                         cut_tail=True, cut_mean_quality=25, poly_g="disable", dedup=True)
    argv = FastpAdapter.argv("fastp", params, P / "r.fq", P / "o.fq.gz", P / "j", P / "h")
    for flag in ("--disable_adapter_trimming", "--disable_quality_filtering", "--disable_length_filtering",
                 "--cut_tail", "--disable_trim_poly_g", "--dedup"):
        assert flag in argv
    assert argv[argv.index("--cut_mean_quality") + 1] == "25"
    assert "--qualified_quality_phred" not in argv and "--in2" not in argv


@pytest.mark.parametrize("bad", [dict(unqualified_percent_limit=150), dict(cut_mean_quality=40),
                                 dict(threads=0), dict(poly_g="sometimes")])
def test_fastp_validation(bad):
    with pytest.raises(ValueError):
        FastpParams(**bad).validate()


def test_fastp_report_parsing(tmp_path):
    report = {
        "summary": {"fastp_version": "0.23.4", "sequencing": "paired end",
                    "before_filtering": {"total_reads": 10, "total_bases": 1500},
                    "after_filtering": {"total_reads": 8, "total_bases": 1100}},
        "filtering_result": {"passed_filter_reads": 8, "low_quality_reads": 2},
        "adapter_cutting": {"adapter_trimmed_reads": 3, "adapter_trimmed_bases": 90,
                            "read1_adapter_sequence": "AGATCGGAAGAGC"},
        "duplication": {"rate": 0.01}, "insert_size": {"peak": 72}, "command": "fastp -i x",
    }
    path = tmp_path / "f.json"
    path.write_text(json.dumps(report))
    parsed = FastpAdapter.parse_report(path)
    assert parsed["after_filtering"]["total_reads"] == 8
    assert parsed["adapter_trimmed_reads"] == 3 and parsed["insert_size_peak"] == 72


def test_filtlong_requires_a_threshold():
    with pytest.raises(ValueError, match="at least one threshold"):
        FiltlongAdapter.argv("filtlong", FiltlongParams(), P / "r.fq.gz")


@pytest.mark.parametrize("bad", [dict(min_mean_q=100), dict(min_mean_q=-1), dict(keep_percent=0),
                                 dict(min_length=500, max_length=100), dict(target_bases=0)])
def test_filtlong_validation(bad):
    with pytest.raises(ValueError):
        FiltlongParams(**bad).validate()


def test_filtlong_command():
    argv = FiltlongAdapter.argv("filtlong", FiltlongParams(min_length=1000, keep_percent=90.0, min_mean_q=90.5),
                                P / "r.fq.gz")
    assert argv[:5] == ["filtlong", "--min_length", "1000", "--min_mean_q", "90.5"]
    assert argv[argv.index("--keep_percent") + 1] == "90"
    assert argv[-1] == "/data/r.fq.gz"


def test_identity_to_phred():
    assert identity_to_phred(90) == pytest.approx(10.0)
    assert identity_to_phred(99) == pytest.approx(20.0)
    assert math.isinf(identity_to_phred(100))


def test_filtlong_log_parsing():
    log = ("\nScoring long reads\n\r  137 reads (485687 bp)\r  400 reads (1580952 bp)\n\n"
           "Filtering long reads\n  target: 1422856 bp\n  keeping 1425385 bp\n")
    assert FiltlongAdapter.parse_log(log) == {
        "input_reads": 400, "input_bases": 1580952,
        "target_bases_reported": 1422856, "kept_bases_reported": 1425385,
    }


def test_filtlong_logs_written_with_digit_grouping():
    from arva_tools.filtlong import ENVIRONMENT, plain_counts

    # Filtlong formats counts with the process locale: en_US groups with commas, es_ES with dots.
    plain = ("\nScoring long reads\n\r  137 reads (485687 bp)\r  400 reads (1580952 bp)\n\n"
             "Filtering long reads\n  target: 1422856 bp\n  keeping 1425385 bp\n")
    en = plain.replace("485687", "485,687").replace("1580952", "1,580,952").replace("1422856", "1,422,856") \
        .replace("1425385", "1,425,385")
    es = en.replace(",", ".")
    assert plain_counts(en) == plain_counts(es) == plain_counts(plain) == plain
    assert FiltlongAdapter.parse_log(en) == FiltlongAdapter.parse_log(es) == FiltlongAdapter.parse_log(plain)
    assert ENVIRONMENT == {"LC_ALL": "C"}


def test_seqkit_parsing_by_column_name():
    tsv = ("file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\tQ1\tQ2\tQ3\tsum_gap\tN50\t"
           "Q20(%)\tQ30(%)\tAvgQual\tGC(%)\n"
           "/x.fq.gz\tFASTQ\tDNA\t2000\t300000\t150\t150.0\t150\t150.0\t150.0\t150.0\t0\t150\t99.76\t74.22\t30.1\t33.79\n")
    (row,) = SeqkitAdapter.parse_stats(tsv)
    assert row["num_seqs"] == 2000 and row["N50"] == 150 and row["GC(%)"] == 33.79
    assert row["AvgQual"] == 30.1 and row["file"] == "/x.fq.gz"
    argv = SeqkitAdapter.stats_argv("seqkit", [P / "x.fq.gz"], threads=2)
    assert argv == ["seqkit", "stats", "--all", "--tabular", "--threads", "2", "/data/x.fq.gz"]


def test_fastqc_names_and_zip_parsing(tmp_path):
    assert FastqcAdapter.output_names("S1_R1_001.fastq.gz") == ("S1_R1_001_fastqc.html", "S1_R1_001_fastqc.zip")
    assert FastqcAdapter.output_names("reads.fq") == ("reads_fastqc.html", "reads_fastqc.zip")
    zpath = tmp_path / "x_fastqc.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("x_fastqc/summary.txt", "PASS\tBasic Statistics\tx.fq\nWARN\tAdapter Content\tx.fq\n")
        z.writestr("x_fastqc/fastqc_data.txt",
                   "##FastQC\t0.12.1\n>>Basic Statistics\tpass\n#Measure\tValue\nTotal Sequences\t2000\n"
                   "%GC\t33\n>>END_MODULE\n")
    parsed = FastqcAdapter.parse_zip(zpath)
    assert parsed["fastqc_version"] == "0.12.1"
    assert parsed["modules"][1] == {"status": "WARN", "module": "Adapter Content"}
    assert parsed["basic_statistics"]["Total Sequences"] == "2000"


# --- MultiQC ------------------------------------------------------------------------------------

MQC_FIXTURES = Path(__file__).parent / "fixtures" / "multiqc"
MQC_INPUTS = [
    ReportInput("fastqc", Path("/job/inputs/arva-0001_fastqc.zip"), "ISO-001 R1"),
    ReportInput("fastqc", Path("/job/inputs/arva-0002_fastqc.zip"), "ISO-001 R2"),
    ReportInput("fastp", Path("/job/inputs/arva-0003.fastp.json"), "ISO-001 R1+R2"),
    ReportInput("seqkit", Path("/job/inputs/arva-0004.seqkit_stats.tsv"), "ISO-001 R1"),
    ReportInput("seqkit", Path("/job/inputs/arva-0005.seqkit_stats.tsv"), "ISO-001 R2"),
    ReportInput("seqkit", Path("/job/inputs/arva-0006.seqkit_stats.tsv"), "ISO-002 SYNTHETIC_nanopore_reads"),
    ReportInput("filtlong", Path("/job/inputs/arva-0007.filtlong.log"), "ISO-002 SYNTHETIC_nanopore_reads"),
]


def mqc_argv(**overrides):
    kwargs = dict(file_list=P / "inputs.txt", outdir=P / "out", config=P / "c.yaml", names=P / "n.tsv",
                  title="Proj", comment="ARVA analysis job 42", modules=["fastqc", "fastp"])
    return MultiqcAdapter.argv("multiqc", **{**kwargs, **overrides})


def test_multiqc_command_is_explicit_and_offline():
    argv = mqc_argv()
    pairs = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    assert pairs["--file-list"] == "/data/inputs.txt" and pairs["--outdir"] == "/data/out"
    assert pairs["--filename"] == "arva_multiqc_report.html" and pairs["--data-format"] == "tsv"
    assert pairs["--config"] == "/data/c.yaml" and pairs["--replace-names"] == "/data/n.tsv"
    assert pairs["--title"] == "Proj" and pairs["--comment"] == "ARVA analysis job 42"
    for flag in ("--force", "--no-version-check", "--no-ai", "--no-ansi", "--no-megaqc-upload", "--interactive",
                 "--fn_as_s_name", "--fullnames", "--require-logs"):
        assert flag in argv
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--module"] == ["fastqc", "fastp"]
    forbidden = {"--development", "--dev", "-p", "--export", "--pdf", "--ai", "--ai-summary", "--ai-summary-full",
                 "--ai-provider", "--flat", "-fp"}
    assert not forbidden & set(argv)
    assert MULTIQC_ENV == {"MULTIQC_NO_VERSION_CHECK": "true"}


@pytest.mark.parametrize("modules", [[], ["fastqc", "nanostat"]])
def test_multiqc_rejects_unknown_or_missing_modules(modules):
    with pytest.raises(ValueError):
        mqc_argv(modules=modules)


def test_multiqc_user_text_cannot_form_markup():
    # MultiQC 1.35 writes sample names and the title into its HTML without escaping them.
    argv = mqc_argv(title="<script>alert(1)</script> Perú\tlab", comment='x" onmouseover="y')
    title, comment = argv[argv.index("--title") + 1], argv[argv.index("--comment") + 1]
    for text in (title, comment, report_text("<img src=x onerror=alert(1)>"), report_text("a&b'c`d")):
        assert not set(text) & set("<>&\"'`=")
    assert title == "_script_alert(1)__script_ Perú lab"
    assert report_text("ISO-001 R1+R2") == "ISO-001 R1+R2"
    assert report_text("  \n ") == "_" and len(report_text("x" * 500)) == 120


def test_multiqc_config_and_names():
    cfg = json.loads(MultiqcAdapter.config(["fastqc", "filtlong"]))
    assert cfg["no_version_check"] is True and cfg["no_ai"] is True and cfg["show_analysis_paths"] is False
    assert cfg["read_count_multiplier"] == 1 and cfg["base_count_multiplier"] == 1
    assert cfg["long_read_count_multiplier"] == 1 and cfg["read_count_prefix"] == ""
    assert cfg["sample_names_replace_exact"] is True
    assert cfg["module_order"] == [{"fastqc": {"doi": []}}, {"filtlong": {"doi": []}}]
    assert cfg["sp"]["filtlong"]["num_lines"] == 20
    assert MultiqcAdapter.replace_names(MQC_INPUTS[:2]) == (
        "arva-0001_fastqc.zip\tISO-001 R1\narva-0002_fastqc.zip\tISO-001 R2\n"
    )
    assert [staged_name(3, m) for m in ("fastqc", "fastp", "seqkit", "filtlong")] == [
        "arva-0003_fastqc.zip", "arva-0003.fastp.json", "arva-0003.seqkit_stats.tsv", "arva-0003.filtlong.log",
    ]


def test_multiqc_sources_match_inputs_one_to_one():
    sources = MultiqcAdapter.parse_sources((MQC_FIXTURES / "multiqc_sources.txt").read_text())
    assert sources[0] == {"module": "FastQC", "section": "all_sections", "sample": "ISO-001 R1",
                          "source": "/job/inputs/arva-0001_fastqc.zip"}
    assert MultiqcAdapter.check_sources(MQC_INPUTS, sources) == []


def test_multiqc_silent_name_collision_is_detected():
    # Real MultiQC 1.35 output after two FastQC inputs were given the same name: exit status 0,
    # one input silently dropped (logged only at DEBUG level).
    sources = MultiqcAdapter.parse_sources((MQC_FIXTURES / "multiqc_sources_collision.txt").read_text())
    problems = MultiqcAdapter.check_sources(MQC_INPUTS, sources)
    assert problems == ["FastQC: 'ISO-001 R2' (arva-0002_fastqc.zip) is missing from the report"]


def test_multiqc_sources_problems_are_listed():
    sources = MultiqcAdapter.parse_sources((MQC_FIXTURES / "multiqc_sources.txt").read_text())
    renamed = [dict(s, sample="other") if s["source"].endswith("0004.seqkit_stats.tsv") else s for s in sources]
    extra = [*sources, {"module": "FastQC", "section": "all_sections", "sample": "ISO-001 R1",
                        "source": "/job/inputs/arva-0099_fastqc.zip"}]
    assert MultiqcAdapter.check_sources(MQC_INPUTS, renamed) == [
        "SeqKit: arva-0004.seqkit_stats.tsv was reported as ['other'] instead of 'ISO-001 R1'"
    ]
    assert MultiqcAdapter.check_sources(MQC_INPUTS, extra) == [
        "FastQC: sample 'ISO-001 R1' was built from 2 files", "FastQC: unexpected input arva-0099_fastqc.zip",
    ]


def test_multiqc_general_stats_are_raw_values_with_units(tmp_path):
    data = json.loads((MQC_FIXTURES / "multiqc_data.json").read_text())
    stats = MultiqcAdapter.parse_general_stats(data)
    cols = {(c["module"], c["key"]): c for c in stats["columns"]}
    rows = {r["name"]: r["values"] for r in stats["rows"]}
    assert stats["unmapped"] == []
    assert rows["ISO-001 R1"]["fastqc"]["total_sequences"] == 2000
    assert rows["ISO-001 R1"]["seqkit"]["num_seqs"] == 2000 and "file" not in rows["ISO-001 R1"]["seqkit"]
    # fastp rates stay fractions (the report shows them x100); MultiQC's own percentages are flagged.
    fastp = rows["ISO-001 R1+R2"]["fastp"]
    assert fastp["after_filtering_q30_rate"] == pytest.approx(0.698063)
    assert cols[("fastp", "after_filtering_q30_rate")]["unit"] == "fraction"
    assert (cols[("fastp", "pct_surviving_reads")]["unit"], cols[("fastp", "pct_surviving_reads")]["origin"]) == (
        "%", "multiqc")
    assert fastp["filtering_result_passed_filter_reads"] == 3688
    assert rows["ISO-002 SYNTHETIC_nanopore_reads"]["filtlong"] == {"Target bases": 1362402, "Bases kept": 1366991}
    assert cols[("filtlong", "Target bases")]["unit"] == "bases"
    assert cols[("fastqc", "percent_fails")]["hidden"] is True

    data["report_general_stats_headers"]["fastqc"]["new_metric"] = {"title": "New"}
    assert MultiqcAdapter.parse_general_stats(data)["unmapped"] == ["fastqc:new_metric"]

    (tmp_path / "multiqc_data.json").write_text(json.dumps(data))
    (tmp_path / "multiqc_software_versions.txt").write_text((MQC_FIXTURES / "multiqc_software_versions.txt").read_text())
    parsed = MultiqcAdapter.parse_data(tmp_path)
    assert parsed["multiqc_version"] == "1.35"
    assert parsed["software_versions"] == {"FastQC": "0.12.1", "fastp": "0.23.4"}
    assert MultiqcAdapter.parse_software_versions("") == {}


# --- NanoPlot ------------------------------------------------------------------
# Fixtures written by NanoPlot 1.48.0: the synthetic nanopore reads, and a 32-record FASTQ with one
# zero-length read and one 10 bp Q40 read ("edge"), which NanoPlot reports as 31 reads and then 30.
NP_FIXTURES = Path(__file__).parent / "fixtures" / "nanoplot"


def test_nanoplot_command_is_fixed_and_offline():
    from arva_tools.nanoplot import NanoplotAdapter

    argv = NanoplotAdapter.argv("NanoPlot", P / "in" / "reads.fastq.gz", P / "out", "reads_", 2)
    assert argv == ["NanoPlot", "--fastq", "/data/in/reads.fastq.gz", "--outdir", "/data/out", "--prefix", "reads_",
                    "--threads", "2", "--no_static", "--only-report", "--include-js", "embedded", "--tsv_stats"]
    for never in ("--downsample", "--info_in_report", "--minqual", "--store", "--raw", "-f", "--format"):
        assert never not in argv


@pytest.mark.parametrize("name, prefix, threads", [
    ("reads.txt", "reads_", 1), ("reads.fastq.gzip", "reads_", 1), ("reads.fastq", "-x_", 1),
    ("reads.fastq", "reads", 1), ("reads.fastq", "a b_", 1), ("reads.fastq", "reads_", 0),
])
def test_nanoplot_command_validation(name, prefix, threads):
    from arva_tools.nanoplot import NanoplotAdapter

    with pytest.raises(ValueError):
        NanoplotAdapter.argv("NanoPlot", P / name, P, prefix, threads)


def test_nanoplot_names():
    from arva_tools.nanoplot import input_name, output_names, output_prefix

    assert output_prefix("SYNTHETIC_nanopore_reads.fastq.gz") == "SYNTHETIC_nanopore_reads_"
    assert output_prefix("-run 1 (pass).FQ") == "run_1_pass_"
    assert output_prefix("....fastq") == "reads_"
    assert len(output_prefix("x" * 300 + ".fq")) == 81
    assert input_name("run_1_pass_", True) == "run_1_pass.fastq.gz" and input_name("r_", False) == "r.fastq"
    names = output_names("r_")
    assert (names.stats, names.post_filtering, names.report, names.log_glob) == (
        "r_NanoStats.txt", "r_NanoStats_post_filtering.txt", "r_NanoPlot-report.html", "r_NanoPlot_*.log")


def test_nanoplot_stats_are_parsed_by_key():
    from arva_tools.nanoplot import NanoplotAdapter

    s = NanoplotAdapter.parse_stats((NP_FIXTURES / "synthetic_NanoStats.txt").read_text())
    assert (s["number_of_reads"], s["number_of_bases"], s["n50"]) == (400, 1513780, 4817)
    assert isinstance(s["number_of_bases"], int)
    assert (s["mean_read_length"], s["median_read_length"], s["read_length_stdev"]) == (3784.4, 2946.0, 3113.3)
    assert (s["mean_qual"], s["median_qual"]) == (10.2, 11.7)
    assert s["reads_above_quality"][0] == {"threshold": 10, "reads": 341, "percent": 85.2, "megabases": 1.3}
    assert [r["threshold"] for r in s["reads_above_quality"]] == [10, 15, 20, 25, 30]
    assert s["longest_reads"][0] == {"rank": 1, "length": 26593, "quality": 11.7}
    assert s["highest_quality_reads"][0] == {"rank": 1, "quality": 12.1, "length": 1110}
    assert len(s["longest_reads"]) == len(s["highest_quality_reads"]) == 5 and s["unparsed"] == []


def test_nanoplot_post_filtering_and_artefacts():
    from arva_tools.nanoplot import NanoplotAdapter

    pre = NanoplotAdapter.parse_stats((NP_FIXTURES / "edge_NanoStats.txt").read_text())
    post = NanoplotAdapter.parse_stats((NP_FIXTURES / "edge_NanoStats_post_filtering.txt").read_text())
    # 32 records: nanoget drops the zero-length one; the 10 bp Q40 read is removed only after NanoStats.txt.
    assert (pre["number_of_reads"], pre["number_of_bases"]) == (31, 56431)
    assert (post["number_of_reads"], post["number_of_bases"]) == (30, 56421)
    assert NanoplotAdapter.artefact_reads_removed((NP_FIXTURES / "edge_NanoPlot.log").read_text()) == 1
    assert NanoplotAdapter.artefact_reads_removed("Finished!") == 0


def test_nanoplot_parser_tolerates_new_keys_and_rejects_other_files():
    from arva_tools.nanoplot import NanoplotAdapter

    text = (NP_FIXTURES / "synthetic_NanoStats.txt").read_text() + "active_channels\t12\n"
    assert NanoplotAdapter.parse_stats(text)["unparsed"] == ["active_channels"]
    with pytest.raises(ValueError, match="Metrics"):
        NanoplotAdapter.parse_stats("General summary:\nMean read length: 3,784.4\n")
    with pytest.raises(ValueError, match="n50"):
        NanoplotAdapter.parse_stats("Metrics\tdataset\nnumber_of_reads\t1\n")


def test_nanoplot_browser_traces(tmp_path):
    from arva_tools.nanoplot import browser_traces

    assert browser_traces(tmp_path) == []
    (tmp_path / "unrelated").mkdir()
    (tmp_path / ".local" / "share" / "choreographer" / "deps").mkdir(parents=True)
    (tmp_path / "google-chrome-for-testing").mkdir()
    assert browser_traces(tmp_path) == [".local/share/choreographer", "google-chrome-for-testing"]
