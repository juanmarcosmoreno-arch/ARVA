"""Command construction and output parsing for each adapter."""
import json
import math
import zipfile
from pathlib import Path

import pytest

from arva_tools.fastp import FastpAdapter, FastpParams
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams, identity_to_phred
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
