"""Integration tests that run the real tools on the synthetic example reads.

Skipped automatically for any tool that is not installed.
"""
import gzip
from pathlib import Path

import pytest

from arva_tools import ToolStatus, run_command
from arva_tools.fastp import FastpAdapter, FastpParams
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams
from arva_tools.registry import detect

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"


def tool(tool_id):
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available:
        pytest.skip(f"{tool_id} not available: {d.message}")
    return d.path


def count_fastq(path: Path) -> int:
    with gzip.open(path, "rt") as fh:
        return sum(1 for _ in fh) // 4


def test_seqkit_stats(tmp_path):
    from arva_tools.seqkit import SeqkitAdapter

    exe = tool("seqkit")
    out = tmp_path / "stats.tsv"
    run_command(SeqkitAdapter.stats_argv(exe, [R1, ONT]), cwd=tmp_path, stderr_path=tmp_path / "e.log",
                stdout_path=out)
    rows = {Path(r["file"]).name: r for r in SeqkitAdapter.parse_stats(out.read_text())}
    assert rows[R1.name]["num_seqs"] == 2000 and rows[R1.name]["sum_len"] == 300000
    assert rows[ONT.name]["num_seqs"] == 400


def test_fastp_paired_end_filters_and_trims(tmp_path):
    exe = tool("fastp")
    argv = FastpAdapter.argv(exe, FastpParams(threads=2), R1, tmp_path / "o1.fq.gz", tmp_path / "f.json",
                             tmp_path / "f.html", in2=R2, out2=tmp_path / "o2.fq.gz")
    run_command(argv, cwd=tmp_path, stderr_path=tmp_path / "fastp.log")
    report = FastpAdapter.parse_report(tmp_path / "f.json")
    before, after = report["before_filtering"]["total_reads"], report["after_filtering"]["total_reads"]
    assert before == 4000 and after < before
    assert report["filtering_result"]["low_quality_reads"] > 0
    assert report["adapter_trimmed_reads"] > 0
    assert count_fastq(tmp_path / "o1.fq.gz") * 2 == after
    assert (tmp_path / "f.html").stat().st_size > 1000


def test_filtlong_keeps_subset(tmp_path):
    exe = tool("filtlong")
    out = tmp_path / "filtered.fastq.gz"
    run_command(FiltlongAdapter.argv(exe, FiltlongParams(min_length=1000, min_mean_q=90), ONT),
                cwd=tmp_path, stderr_path=tmp_path / "filtlong.log", stdout_path=out)
    kept = count_fastq(out)
    assert 0 < kept < 400
    with gzip.open(out, "rt") as fh:
        lines = fh.read().splitlines()
    assert all(len(seq) >= 1000 for seq in lines[1::4])
    assert FiltlongAdapter.parse_log((tmp_path / "filtlong.log").read_text())["input_reads"] == 400


def test_fastqc_report(tmp_path):
    exe = tool("fastqc")
    (tmp_path / "tmp").mkdir()
    run_command(FastqcAdapter.argv(exe, R1, tmp_path, tmp_path / "tmp"), cwd=tmp_path,
                stderr_path=tmp_path / "fastqc.log")
    html, zipname = FastqcAdapter.output_names(R1.name)
    assert (tmp_path / html).exists()
    parsed = FastqcAdapter.parse_zip(tmp_path / zipname)
    assert parsed["basic_statistics"]["Total Sequences"] == "2000"
    assert {m["module"] for m in parsed["modules"]} >= {"Basic Statistics", "Adapter Content"}
