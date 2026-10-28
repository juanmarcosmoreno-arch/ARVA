"""fastp — short-read quality control, adapter trimming and filtering.

Every option below was checked against `fastp --help` of fastp 0.23.4 and 0.23.2.
ARVA always passes every filtering option explicitly — including values equal
to fastp's defaults — so the recorded command fully describes what was removed.
fastp.json was verified for 0.23.4: numbers have 6 significant digits and zeros may be integers;
duplication holds only 'rate'; the insert-size histogram comes from worker thread 0 alone.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from arva_tools.base import ToolAdapter, ToolInfo

# fastp's insertSizeMax: pairs without a detected overlap and inserts of 512 bp or more are 'unknown'.
INSERT_SIZE_MAX = 512
_QUALITY_CURVES = ("mean", "A", "T", "C", "G")
_CONTENT_CURVES = ("A", "T", "C", "G", "GC", "N")


def _curves(section: dict) -> dict:
    quality, content = section.get("quality_curves") or {}, section.get("content_curves") or {}
    return {
        "total_reads": section.get("total_reads"),
        "total_cycles": section.get("total_cycles"),
        "quality": {k: [float(v) for v in quality[k]] for k in _QUALITY_CURVES if k in quality},
        "content": {k: [float(v) for v in content[k]] for k in _CONTENT_CURVES if k in content},
    }


def _adapter_cutting(block: dict) -> dict:
    def counts(name: str) -> list[dict]:
        return [{"sequence": seq, "count": int(n)} for seq, n in (block.get(name) or {}).items()]

    return {
        "adapter_trimmed_reads": block.get("adapter_trimmed_reads"),
        "adapter_trimmed_bases": block.get("adapter_trimmed_bases"),
        "read1_adapter_sequence": block.get("read1_adapter_sequence"),
        "read2_adapter_sequence": block.get("read2_adapter_sequence"),
        "read1_adapter_counts": counts("read1_adapter_counts"),
        "read2_adapter_counts": counts("read2_adapter_counts"),
    }


def _insert_size(block: dict) -> dict:
    histogram = [int(v) for v in block.get("histogram") or []]
    unknown = int(block.get("unknown") or 0)
    overlapping = sum(histogram)
    evaluated = overlapping + unknown
    return {
        # fastp reports peak 0 when no pair overlapped.
        "peak": block.get("peak") if overlapping else None,
        "unknown": unknown,
        "overlapping_pairs": overlapping,
        "evaluated_pairs": evaluated,
        "histogram": histogram,
        "histogram_percent": [100 * v / evaluated for v in histogram] if evaluated else [],
        "unknown_percent": 100 * unknown / evaluated if evaluated else None,
        "insert_size_max": INSERT_SIZE_MAX,
    }

@dataclass
class FastpParams:
    # Adapter trimming (fastp default: enabled; auto-detection for SE, overlap analysis for PE)
    adapter_trimming: bool = True
    detect_adapter_for_pe: bool = True
    # Quality filtering (fastp defaults: enabled, Q15, 40 % unqualified bases allowed)
    quality_filtering: bool = True
    qualified_quality_phred: int = 15
    unqualified_percent_limit: int = 40
    n_base_limit: int = 5
    average_qual: int = 0
    # Length filtering (fastp default: enabled, 15 bp)
    length_filtering: bool = True
    length_required: int = 15
    # Sliding-window trimming (fastp default: off)
    cut_front: bool = False
    cut_tail: bool = False
    cut_window_size: int = 4
    cut_mean_quality: int = 20
    # PolyG trimming: fastp enables it automatically for NextSeq/NovaSeq data
    poly_g: Literal["auto", "force", "disable"] = "auto"
    # Deduplication (fastp default: off)
    dedup: bool = False
    threads: int = 3

    def validate(self) -> None:
        checks = [
            (0 <= self.qualified_quality_phred <= 93, "qualified_quality_phred must be 0–93"),
            (0 <= self.unqualified_percent_limit <= 100, "unqualified_percent_limit must be 0–100"),
            (self.n_base_limit >= 0, "n_base_limit must be ≥ 0"),
            (0 <= self.average_qual <= 93, "average_qual must be 0–93"),
            (self.length_required >= 0, "length_required must be ≥ 0"),
            (1 <= self.cut_window_size <= 1000, "cut_window_size must be 1–1000"),
            (1 <= self.cut_mean_quality <= 36, "cut_mean_quality must be 1–36"),
            (1 <= self.threads <= 16, "threads must be 1–16"),
            (self.poly_g in ("auto", "force", "disable"), "poly_g must be auto, force or disable"),
        ]
        errors = [msg for ok, msg in checks if not ok]
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict:
        return asdict(self)


class FastpAdapter(ToolAdapter):
    info = ToolInfo(
        id="fastp",
        name="fastp",
        description="All-in-one FASTQ preprocessor for short reads: quality control, adapter "
        "trimming, quality/length filtering and an HTML/JSON report.",
        homepage="https://github.com/OpenGene/fastp",
        license="MIT",
        citation="Chen S, Zhou Y, Chen Y, Gu J. fastp: an ultra-fast all-in-one FASTQ "
        "preprocessor. Bioinformatics 2018;34(17):i884–i890.",
        citation_url="https://doi.org/10.1093/bioinformatics/bty560",
        executable="fastp",
        categories=("qc", "filtering", "trimming"),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("fastq.gz", "json", "html"),
        min_version="0.23.0",
        tested_versions=("0.23.2", "0.23.4"),
        install={"conda": "bioconda::fastp", "apt": "fastp"},
    )
    version_pattern = re.compile(r"fastp\s+v?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)

    @staticmethod
    def argv(
        executable: str,
        params: FastpParams,
        in1: Path,
        out1: Path,
        json_path: Path,
        html_path: Path,
        in2: Path | None = None,
        out2: Path | None = None,
        title: str = "ARVA fastp report",
    ) -> list[str]:
        params.validate()
        a = [executable, "--in1", str(in1), "--out1", str(out1)]
        if in2 is not None:
            if out2 is None:
                raise ValueError("paired-end input requires out2")
            a += ["--in2", str(in2), "--out2", str(out2)]
        a += ["--json", str(json_path), "--html", str(html_path), "--report_title", title]
        a += ["--thread", str(params.threads), "--compression", "6"]

        if not params.adapter_trimming:
            a.append("--disable_adapter_trimming")
        elif in2 is not None and params.detect_adapter_for_pe:
            a.append("--detect_adapter_for_pe")

        if params.quality_filtering:
            a += [
                "--qualified_quality_phred", str(params.qualified_quality_phred),
                "--unqualified_percent_limit", str(params.unqualified_percent_limit),
                "--n_base_limit", str(params.n_base_limit),
                "--average_qual", str(params.average_qual),
            ]
        else:
            a.append("--disable_quality_filtering")

        if params.length_filtering:
            a += ["--length_required", str(params.length_required)]
        else:
            a.append("--disable_length_filtering")

        if params.cut_front or params.cut_tail:
            if params.cut_front:
                a.append("--cut_front")
            if params.cut_tail:
                a.append("--cut_tail")
            a += ["--cut_window_size", str(params.cut_window_size),
                  "--cut_mean_quality", str(params.cut_mean_quality)]

        if params.poly_g == "force":
            a.append("--trim_poly_g")
        elif params.poly_g == "disable":
            a.append("--disable_trim_poly_g")

        if params.dedup:
            a.append("--dedup")
        return a

    @staticmethod
    def parse_report(json_path: Path) -> dict:
        d = json.loads(Path(json_path).read_text())
        s = d["summary"]
        adapters = d.get("adapter_cutting") or {}
        return {
            "fastp_version": s.get("fastp_version"),
            "sequencing": s.get("sequencing"),
            "before_filtering": s["before_filtering"],
            "after_filtering": s["after_filtering"],
            "filtering_result": d.get("filtering_result", {}),
            "adapter_trimmed_reads": adapters.get("adapter_trimmed_reads"),
            "adapter_trimmed_bases": adapters.get("adapter_trimmed_bases"),
            "read1_adapter_sequence": adapters.get("read1_adapter_sequence"),
            "read2_adapter_sequence": adapters.get("read2_adapter_sequence"),
            "duplication_rate": (d.get("duplication") or {}).get("rate"),
            "insert_size_peak": (d.get("insert_size") or {}).get("peak"),
            "command": d.get("command"),
        }

    @staticmethod
    def parse_data(json_path: Path) -> dict:
        """Per-cycle curves, adapter trimming, duplication rate and insert sizes for charts. Each block may be
        absent: adapter_cutting without adapter trimming (or when single-end detection finds no adapter),
        duplication with --dont_eval_duplication, insert_size for single-end data."""
        d = json.loads(Path(json_path).read_text())
        s = d.get("summary") or {}
        reads = {}
        for mate in ("read1", "read2"):
            stages = {stage: _curves(d[key]) for stage in ("before", "after")
                      if isinstance(d.get(key := f"{mate}_{stage}_filtering"), dict)}
            if stages:
                reads[mate] = stages
        adapters, insert = d.get("adapter_cutting"), d.get("insert_size")
        rate = (d.get("duplication") or {}).get("rate")
        return {
            "fastp_version": s.get("fastp_version"),
            "sequencing": s.get("sequencing"),
            "reads": reads,
            "adapter_cutting": _adapter_cutting(adapters) if isinstance(adapters, dict) else None,
            "duplication_rate": None if rate is None else float(rate),
            "insert_size": _insert_size(insert) if isinstance(insert, dict) else None,
        }
