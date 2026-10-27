"""FastQC — per-file quality control report.

Options verified against `fastqc --help` of FastQC v0.12.1.
FastQC's PASS/WARN/FAIL flags are heuristics designed for whole-genome
shotgun Illumina libraries; ARVA reports them as FastQC's flags, not verdicts.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from arva_tools.base import ToolAdapter, ToolInfo


class FastqcAdapter(ToolAdapter):
    info = ToolInfo(
        id="fastqc",
        name="FastQC",
        description="Widely used quality-control report for high-throughput sequencing reads "
        "(per-base quality, sequence content, duplication, adapter content…).",
        homepage="https://www.bioinformatics.babraham.ac.uk/projects/fastqc/",
        license="GPL-3.0-or-later",
        citation="Andrews S. FastQC: a quality control tool for high throughput sequence data. "
        "Babraham Bioinformatics, 2010.",
        citation_url="https://www.bioinformatics.babraham.ac.uk/projects/fastqc/",
        executable="fastqc",
        categories=("qc", "report"),
        input_formats=("fastq", "fastq.gz", "bam", "sam"),
        output_formats=("html", "zip"),
        min_version="0.11.0",
        tested_versions=("0.12.1",),
        install={"conda": "bioconda::fastqc", "apt": "fastqc"},
    )
    version_pattern = re.compile(r"FastQC\s+v?(\d+\.\d+(?:\.\d+)?)")

    @staticmethod
    def argv(executable: str, input_path: Path, outdir: Path, temp_dir: Path) -> list[str]:
        return [
            executable, "--outdir", str(outdir), "--noextract", "--quiet",
            "--threads", "1", "--dir", str(temp_dir), str(input_path),
        ]

    @staticmethod
    def output_names(input_name: str) -> tuple[str, str]:
        """FastQC names outputs after the input minus .gz/.bz2 and the format extension."""
        stem = re.sub(r"\.(gz|bz2)$", "", input_name)
        stem = re.sub(r"\.(fastq|fq|txt|sam|bam)$", "", stem)
        return f"{stem}_fastqc.html", f"{stem}_fastqc.zip"

    @staticmethod
    def parse_zip(zip_path: Path) -> dict:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            summary_name = next(n for n in names if n.endswith("/summary.txt"))
            data_name = next(n for n in names if n.endswith("/fastqc_data.txt"))
            summary = z.read(summary_name).decode("utf-8", "replace")
            data = z.read(data_name).decode("utf-8", "replace")
        modules = []
        for line in summary.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                modules.append({"status": parts[0], "module": parts[1]})
        basic = {}
        in_basic = False
        for line in data.splitlines():
            if line.startswith(">>Basic Statistics"):
                in_basic = True
                continue
            if in_basic:
                if line.startswith(">>END_MODULE"):
                    break
                if not line.startswith("#") and "\t" in line:
                    k, v = line.split("\t", 1)
                    basic[k] = v
        version = re.search(r"##FastQC\s+(\S+)", data)
        return {"fastqc_version": version.group(1) if version else None, "modules": modules,
                "basic_statistics": basic}
