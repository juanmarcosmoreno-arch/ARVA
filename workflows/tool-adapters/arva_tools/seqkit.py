"""SeqKit `stats` — independent summary statistics for FASTA/FASTQ.

Verified against `seqkit stats --help` of SeqKit v2.3.0:
  -a/--all (quartiles, sum_gap, N50), -T/--tabular, -j/--threads.
Columns are parsed by header name so newer releases that add columns
(e.g. AvgQual) remain compatible.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from arva_tools.base import ToolAdapter, ToolInfo

_NUMERIC = {
    "num_seqs": int, "sum_len": int, "min_len": int, "avg_len": float, "max_len": int,
    "Q1": float, "Q2": float, "Q3": float, "sum_gap": int, "N50": int,
    "Q20(%)": float, "Q30(%)": float, "GC(%)": float, "AvgQual": float,
}


class SeqkitAdapter(ToolAdapter):
    info = ToolInfo(
        id="seqkit",
        name="SeqKit",
        description="Ultrafast toolkit for FASTA/FASTQ manipulation; ARVA uses `seqkit stats` as an "
        "independent cross-check of its own read statistics.",
        homepage="https://bioinf.shenwei.me/seqkit/",
        license="MIT",
        citation="Shen W, Le S, Li Y, Hu F. SeqKit: A Cross-Platform and Ultrafast Toolkit for "
        "FASTA/Q File Manipulation. PLoS ONE 2016;11(10):e0163962.",
        citation_url="https://doi.org/10.1371/journal.pone.0163962",
        executable="seqkit",
        categories=("statistics", "qc"),
        input_formats=("fastq", "fastq.gz", "fasta", "fasta.gz"),
        output_formats=("tsv",),
        min_version="2.0.0",
        tested_versions=("2.3.0",),
        install={"conda": "bioconda::seqkit", "apt": "seqkit"},
    )
    version_args = ("version",)
    version_pattern = re.compile(r"seqkit\s+v?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)

    @staticmethod
    def stats_argv(executable: str, inputs: list[Path], threads: int = 2) -> list[str]:
        return [executable, "stats", "--all", "--tabular", "--threads", str(threads), *map(str, inputs)]

    @staticmethod
    def parse_stats(tsv: str) -> list[dict]:
        rows = []
        for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
            parsed: dict = {}
            for key, value in row.items():
                if key is None:
                    continue
                conv = _NUMERIC.get(key)
                parsed[key] = conv(value) if conv and value not in ("", None) else value
            rows.append(parsed)
        return rows
